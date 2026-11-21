import base64
import datetime
import json
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from lxml import etree

from ledgerx_tax.adapters import custom, egypt as eg_ad, get, uae as uae_ad, zatca as sa_ad
from ledgerx_tax.engine import common, egypt, generic, uae, zatca


def sample(cur="EGP", rate=1.0, tax_rate=14, kind="invoice", buyer_tax=""):
	lines, totals = common.build_lines([{"description": "Item A", "code": "A1", "unit": "EA", "qty": 2, "rate": 50, "discount_amount": 10, "tax_rate": tax_rate}, {"description": "Item B", "code": "B1", "unit": "EA", "qty": 1, "rate": 20.5, "discount_amount": 0, "tax_rate": tax_rate}])
	return {"id": "SINV-1", "issue_dt": datetime.datetime(2026, 11, 21, 10, 0, 0), "kind": kind, "currency": cur, "rate": rate, "reference": "", "notes": "",
		"seller": {"name": "Seller Co", "tax_id": "100200300", "reg_no": "55", "branch": "0", "address": {"country": "EG", "governate": "Cairo", "city": "Nasr City", "street": "Main", "building": "10"}},
		"buyer": {"name": "Buyer", "tax_id": buyer_tax, "type": "B" if buyer_tax else "P", "address": {"country": "EG", "governate": "Cairo", "city": "X", "street": "Y", "building": "1"}},
		"lines": lines, "totals": totals, "payment": {}}


class Fake:
	def __init__(self, *answers):
		self.answers, self.calls = list(answers), []

	def __call__(self, method, url, headers=None, json=None, data=None, timeout=60):
		self.calls.append((method, url, headers, json, data))
		st, body = self.answers.pop(0)
		return st, body, (body if isinstance(body, str) else __import__("json").dumps(body))


class Common(unittest.TestCase):
	def test_lines(self):
		inv = sample()
		self.assertAlmostEqual(inv["totals"]["net"], 110.5)
		self.assertAlmostEqual(inv["totals"]["tax"], 15.47)
		self.assertAlmostEqual(inv["totals"]["grand"], 125.97)
		self.assertAlmostEqual(inv["totals"]["discount"], 10)


class Egypt(unittest.TestCase):
	cfg = {"taxpayer_activity_code": "4620"}

	def test_document_shape(self):
		d = egypt.build_document(sample(), self.cfg)
		self.assertEqual(d["documentType"], "i")
		self.assertEqual(d["documentTypeVersion"], "1.0")
		self.assertEqual(d["dateTimeIssued"], "2026-11-21T10:00:00Z")
		self.assertEqual(len(d["invoiceLines"]), 2)
		self.assertAlmostEqual(d["totalAmount"], 125.97)
		self.assertEqual(d["issuer"]["address"]["branchId"], "0")
		self.assertEqual(d["taxTotals"][0]["taxType"], "T1")

	def test_foreign_currency_fields(self):
		d = egypt.build_document(sample("USD", 48.0), self.cfg)
		v = d["invoiceLines"][0]["unitValue"]
		self.assertEqual(v["currencySold"], "USD")
		self.assertEqual(v["amountEGP"], 2400.0)
		self.assertEqual(v["amountSold"], 50.0)
		self.assertEqual(v["currencyExchangeRate"], 48.0)

	def test_serialize_matches_the_published_rule(self):
		self.assertEqual(egypt.serialize({"name": "Item", "qty": 0.0, "taxableItems": [{"code": "T1"}]}), '"NAME""Item""QTY""0.0""TAXABLEITEMS""TAXABLEITEMS""CODE""T1"')

	def test_hash_ignores_signature(self):
		d = egypt.build_document(sample(), self.cfg)
		a = egypt.canonical_hash(d)[1]
		b = egypt.canonical_hash(egypt.with_signature(d, "AAA"))[1]
		self.assertEqual(a, b)

	def test_parse(self):
		self.assertEqual(egypt.parse_response({"acceptedDocuments": [{"uuid": "U", "longId": "L"}], "rejectedDocuments": []})[:3], ("Accepted", "U", "L"))
		st, _, _, err = egypt.parse_response({"rejectedDocuments": [{"error": {"message": "bad", "details": [{"message": "x"}]}}]})
		self.assertEqual(st, "Rejected")
		self.assertIn("x", err)

	def test_send_flow(self):
		cfg = {"name": "C", "environment": "Test", "auth_user": "id", "auth_secret": "s", "activity_code": "4620", "signer": "External Signing Service", "signer_url": "http://sign", "signer_token": "k"}
		http = Fake((200, {"access_token": "T", "expires_in": 3600}), (200, {"signature": "SIG"}), (202, {"submissionUUID": "S", "acceptedDocuments": [{"uuid": "U", "longId": "L", "internalId": "SINV-1"}], "rejectedDocuments": []}))
		out = eg_ad.send(cfg, sample(), {"http": http})
		self.assertEqual(out["status"], "Submitted")
		self.assertEqual(out["uuid"], "U")
		sent = http.calls[2][3]["documents"][0]
		self.assertEqual(sent["signatures"][0]["value"], "SIG")
		self.assertTrue(http.calls[2][1].endswith("/api/v1.0/documentsubmissions"))
		self.assertTrue(http.calls[0][1].startswith("https://id.preprod.eta.gov.eg"))
		self.assertEqual(http.calls[1][3]["sha256"], egypt.canonical_hash(egypt.build_document(sample(), {"taxpayer_activity_code": "4620"}))[1].hex())

	def test_check_states(self):
		cfg = {"name": "C", "environment": "Test", "auth_user": "id", "auth_secret": "s"}
		http = Fake((200, {"access_token": "T"}), (200, {"status": "Valid"}))
		self.assertEqual(eg_ad.check(cfg, {"uuid": "U"}, {"http": http})["status"], "Accepted")
		http = Fake((200, {"access_token": "T"}), (200, {"status": "Invalid", "validationResults": {"validationSteps": [{"name": "s1", "status": "Invalid", "error": {"error": "bad code"}}]}}))
		r = eg_ad.check(cfg, {"uuid": "U"}, {"http": http})
		self.assertEqual(r["status"], "Rejected")
		self.assertIn("bad code", r["error"])

	def test_login_failure_raises(self):
		with self.assertRaises(RuntimeError):
			eg_ad.get_token({"name": "C", "environment": "Test", "auth_user": "a", "auth_secret": "b"}, Fake((400, {"error": "invalid_client"})))


def _cert_pair():
	key_pem, _csr, _b64 = zatca.make_csr("300000000000003", "Seller Co", "Riyadh", "EGS1", "serial-1", "Riyadh", "Supply")
	k = serialization.load_pem_private_key(key_pem.encode(), None)
	name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PREZATCA-Test"), x509.NameAttribute(NameOID.DOMAIN_COMPONENT, "local")])
	cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key()).serial_number(777).not_valid_before(datetime.datetime(2026, 1, 1)).not_valid_after(datetime.datetime(2030, 1, 1)).sign(k, hashes.SHA256())
	der = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
	return key_pem, cert, base64.b64encode(der.encode()).decode()


class Saudi(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.key, cls.cert, cls.token = _cert_pair()

	def inv(self, buyer_tax=""):
		i = sample("SAR", 1.0, 15, buyer_tax=buyer_tax)
		i["seller"]["address"] = {"country": "SA", "city": "Riyadh", "street": "King Fahd", "building": "1234", "postal": "12345"}
		i["buyer"]["address"] = {"country": "SA"}
		i["seller"]["tax_id"] = "300000000000003"
		return i

	def test_csr_is_a_valid_request_with_the_template_extension(self):
		key, csr, b64 = zatca.make_csr("300000000000003", "Co", "Unit", "EGS1", "s1", "Riyadh", "Supply", environment="Production")
		req = x509.load_pem_x509_csr(csr.encode())
		self.assertTrue(req.is_signature_valid)
		self.assertEqual(req.subject.get_attributes_for_oid(NameOID.COUNTRY_NAME)[0].value, "SA")
		self.assertEqual(base64.b64decode(b64).decode(), csr)
		self.assertIn(b"ZATCA-Code-Signing", req.extensions.get_extension_for_oid(x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2")).value.value)

	def test_xml_hash_signature_and_qr(self):
		root = zatca.build_xml(self.inv(), {"invoice_kind": "simplified"}, zatca.new_uuid(), 1, zatca.FIRST_PIH)
		xml, h, qr = zatca.sign_invoice(root, self.key, self.token)
		r2 = etree.fromstring(xml.encode())
		digest, h2 = zatca.invoice_hash(r2)
		self.assertEqual(h, h2)  # the embedded signature and QR do not change the hash
		sig = base64.b64decode(r2.find(".//{http://www.w3.org/2000/09/xmldsig#}SignatureValue").text)
		self.cert.public_key().verify(sig, digest, ec.ECDSA(hashes.SHA256()))
		tlv = base64.b64decode(qr)
		tags, i = {}, 0
		while i < len(tlv):
			tags[tlv[i]] = tlv[i + 2:i + 2 + tlv[i + 1]]
			i += 2 + tlv[i + 1]
		self.assertEqual(tags[1], b"Seller Co")
		self.assertEqual(tags[2], b"300000000000003")
		self.assertEqual(tags[4], b"127.08")
		self.assertEqual(tags[6].decode(), h)
		self.assertIn(9, tags)

	def test_standard_invoice_has_no_cert_signature_tag(self):
		root = zatca.build_xml(self.inv("399999999900003"), {"invoice_kind": "standard"}, zatca.new_uuid(), 2, zatca.FIRST_PIH)
		_, _, qr = zatca.sign_invoice(root, self.key, self.token, simplified=False)
		tlv = base64.b64decode(qr)
		tags, i = [], 0
		while i < len(tlv):
			tags.append(tlv[i])
			i += 2 + tlv[i + 1]
		self.assertNotIn(9, tags)

	def test_credit_note_needs_reference(self):
		i = self.inv()
		i["kind"], i["reference"], i["notes"] = "credit", "SINV-0", "Returned"
		root = zatca.build_xml(i, {"invoice_kind": "simplified"}, zatca.new_uuid(), 3, zatca.FIRST_PIH)
		ns = {"cbc": zatca.NS["cbc"], "cac": zatca.NS["cac"]}
		self.assertEqual(root.find("cbc:InvoiceTypeCode", ns).text, "381")
		self.assertEqual(root.find(".//cac:InvoiceDocumentReference/cbc:ID", ns).text, "SINV-0")

	def cfg(self):
		return {"environment": "Simulation", "private_key": self.key, "production_token": self.token, "production_secret": "sec", "tax_id": "300000000000003", "invoice_kind": "Auto"}

	def test_send_reporting_for_simplified(self):
		http = Fake((200, {"reportingStatus": "REPORTED", "validationResults": {"status": "PASS", "errorMessages": [], "warningMessages": []}}))
		out = sa_ad.send(self.cfg(), self.inv(), {"http": http, "icv": 4, "pih": zatca.FIRST_PIH})
		self.assertEqual(out["status"], "Accepted")
		self.assertTrue(out["advance_chain"])
		self.assertEqual(out["icv"], 5)
		self.assertTrue(http.calls[0][1].endswith("/simulation/invoices/reporting/single"))
		self.assertEqual(http.calls[0][2]["Clearance-Status"], "0")
		body = http.calls[0][3]
		self.assertEqual(set(body), {"invoiceHash", "uuid", "invoice"})

	def test_send_clearance_for_standard(self):
		http = Fake((200, {"clearanceStatus": "CLEARED", "validationResults": {"status": "PASS", "errorMessages": []}, "clearedInvoice": base64.b64encode(b"<cleared/>").decode()}))
		out = sa_ad.send(self.cfg(), self.inv("399999999900003"), {"http": http})
		self.assertTrue(http.calls[0][1].endswith("/invoices/clearance/single"))
		self.assertEqual(http.calls[0][2]["Clearance-Status"], "1")
		self.assertEqual(out["status"], "Accepted")
		self.assertEqual(out["payload"], "<cleared/>")

	def test_rejection_does_not_advance_chain(self):
		http = Fake((400, {"validationResults": {"status": "ERROR", "errorMessages": [{"code": "X1", "message": "bad"}]}}))
		out = sa_ad.send(self.cfg(), self.inv(), {"http": http})
		self.assertEqual(out["status"], "Rejected")
		self.assertNotIn("advance_chain", out)

	def test_needs_onboarding(self):
		with self.assertRaises(RuntimeError):
			sa_ad.send({"tax_id": "1"}, self.inv(), {"http": Fake()})

	def test_onboarding_calls(self):
		http = Fake((200, {"binarySecurityToken": "TOK", "secret": "SEC", "requestID": 123}))
		t, s, rid = sa_ad.compliance_csid({"environment": "Simulation"}, "CSR", "123456", http)
		self.assertEqual((t, s, rid), ("TOK", "SEC", "123"))
		self.assertEqual(http.calls[0][2]["OTP"], "123456")
		self.assertTrue(http.calls[0][1].endswith("/simulation/compliance"))

	def test_compliance_run_posts_six_samples(self):
		cfg = {"environment": "Simulation", "private_key": self.key, "compliance_token": self.token, "compliance_secret": "x"}
		http = Fake(*[(200, {"reportingStatus": "REPORTED", "validationResults": {"status": "PASS", "errorMessages": []}})] * 6)
		res = sa_ad.run_compliance(cfg, self.inv(), http)
		self.assertEqual(len(res), 6)
		self.assertTrue(all(r[1] == "Accepted" for r in res))


class Uae(unittest.TestCase):
	def inv(self):
		i = sample("AED", 1.0, 5)
		i["seller"].update({"tax_id": "100000000000003"})
		i["buyer"].update({"tax_id": "100000000000011"})
		i["seller"]["address"]["country"] = i["buyer"]["address"]["country"] = "AE"
		return i

	def test_xml(self):
		i = self.inv()
		i["seller"]["endpoint"] = i["seller"]["tax_id"]
		i["buyer"]["endpoint"] = i["buyer"]["tax_id"]
		root = uae.build_xml(i, {})
		ns = {"cbc": zatca.NS["cbc"], "cac": zatca.NS["cac"]}
		self.assertEqual(root.find("cbc:CustomizationID", ns).text, "urn:peppol:pint:billing-1@ae-1")
		self.assertEqual(root.find(".//cac:AccountingSupplierParty//cbc:EndpointID", ns).get("schemeID"), "0235")
		self.assertEqual(len(root.findall("cac:InvoiceLine", ns)), 2)
		self.assertEqual(root.find("cac:LegalMonetaryTotal/cbc:PayableAmount", ns).text, "116.03")

	def test_send_xml_and_template(self):
		cfg = {"api_url": "https://asp.example/inv", "auth_type": "Bearer Token", "auth_secret": "T", "ok_path": "status", "ok_value": "ok", "uuid_path": "id"}
		http = Fake((200, {"status": "ok", "id": "A1"}))
		out = uae_ad.send(cfg, self.inv(), {"http": http})
		self.assertEqual(out["status"], "Submitted")
		self.assertEqual(out["uuid"], "A1")
		self.assertEqual(http.calls[0][2]["Authorization"], "Bearer T")
		self.assertIn(b"urn:peppol:pint:billing-1@ae-1", http.calls[0][4])
		cfg2 = dict(cfg, body_template='{"ref": "{{ inv.id }}", "doc": "{{ cfg.xml_b64 }}"}')
		http = Fake((200, {"status": "ok", "id": "A2"}))
		uae_ad.send(cfg2, self.inv(), {"http": http})
		sent = json.loads(http.calls[0][4])
		self.assertEqual(sent["ref"], "SINV-1")
		self.assertIn(b"CustomizationID", base64.b64decode(sent["doc"]))

	def test_provider_rejection(self):
		http = Fake((200, {"status": "fail", "msg": "TIN unknown"}))
		out = uae_ad.send({"api_url": "u", "ok_path": "status", "ok_value": "ok", "error_path": "msg"}, self.inv(), {"http": http})
		self.assertEqual(out["status"], "Rejected")
		self.assertEqual(out["error"], "TIN unknown")


class Custom(unittest.TestCase):
	def test_dig_and_template(self):
		self.assertEqual(generic.dig({"a": {"b": [1, {"c": 5}]}}, "a.b.1.c"), 5)
		self.assertEqual(generic.render('{{ inv.id }}-{{ inv.lines | length }}', {"id": "X", "lines": [1, 2]}), "X-2")
		with self.assertRaises(Exception):
			generic.render("{{ inv.missing.deep }}", {"id": "X"})

	def test_send_and_failures(self):
		cfg = {"api_url": "https://x/api", "body_template": '{"n": "{{ inv.id }}"}', "auth_type": "Custom Header", "auth_header": "X-Key", "auth_secret": "k", "ok_path": "ok", "ok_value": "true"}
		inv = {"id": "A", "lines": []}
		http = Fake((200, {"ok": True}))
		self.assertEqual(custom.send(cfg, inv, {"http": http})["status"], "Accepted")
		self.assertEqual(http.calls[0][2]["X-Key"], "k")
		self.assertEqual(custom.send(cfg, inv, {"http": Fake((500, "boom"))})["status"], "Failed")
		self.assertEqual(custom.send(cfg, inv, {"http": Fake((422, {"e": 1}))})["status"], "Rejected")

	def test_registry(self):
		for s in ("Egypt ETA", "Saudi ZATCA", "UAE PINT-AE", "Custom API"):
			self.assertTrue(hasattr(get(s), "send"))


if __name__ == "__main__":
	unittest.main()
