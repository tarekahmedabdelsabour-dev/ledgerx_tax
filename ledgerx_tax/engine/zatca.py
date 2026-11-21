"""Saudi ZATCA (Fatoora) phase 2: UBL 2.1 invoice, invoice hash, ECDSA signature (XAdES), QR (TLV), CSR.

Written from ZATCA's published technical documents and the behaviour of the open reference implementations.
It has NOT been run against ZATCA's compliance checks: every EGS unit must pass the official compliance
invoices (simulation portal) before production. Treat the first run as a test."""
import base64
import hashlib
import uuid as _uuid
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier
from lxml import etree

from .common import money

NS = {
	"inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
	"cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
	"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
	"ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}
DS = "http://www.w3.org/2000/09/xmldsig#"
XADES = "http://uri.etsi.org/01903/v1.3.2#"
TYPE_CODE = {"invoice": "388", "credit": "381", "debit": "383"}
TEMPLATE_NAME = {"Test": "TSTZATCA-Code-Signing", "Simulation": "PREZATCA-Code-Signing", "Production": "ZATCA-Code-Signing"}
URLS = {
	"Test": "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
	"Simulation": "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation",
	"Production": "https://gw-fatoora.zatca.gov.sa/e-invoicing/core",
}


def q(tag):
	p, t = tag.split(":")
	return "{%s}%s" % (NS[p], t)


# ---------------------------------------------------------------- onboarding
def make_csr(vat, org, org_unit, common_name, serial, address, industry, environment="Simulation", solution="LedgerX", model="1", version="1"):
	"""-> (private_key_pem, csr_pem, csr_b64). The EGS serial is '1-<solution>|2-<model>|3-<serial>'."""
	key = ec.generate_private_key(ec.SECP256K1())
	subject = x509.Name([
		x509.NameAttribute(NameOID.COUNTRY_NAME, "SA"), x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, org_unit),
		x509.NameAttribute(NameOID.ORGANIZATION_NAME, org), x509.NameAttribute(NameOID.COMMON_NAME, common_name),
	])
	tpl = TEMPLATE_NAME.get(environment, "ZATCA-Code-Signing").encode()
	template_ext = x509.UnrecognizedExtension(ObjectIdentifier("1.3.6.1.4.1.311.20.2"), bytes([0x13, len(tpl)]) + tpl)
	san_name = x509.Name([
		x509.NameAttribute(ObjectIdentifier("2.5.4.4"), f"1-{solution}|2-{model}|3-{serial}"),
		x509.NameAttribute(ObjectIdentifier("0.9.2342.19200300.100.1.1"), vat),
		x509.NameAttribute(ObjectIdentifier("2.5.4.12"), "1100"),
		x509.NameAttribute(ObjectIdentifier("2.5.4.26"), address),
		x509.NameAttribute(ObjectIdentifier("2.5.4.15"), industry),
	])
	csr = (x509.CertificateSigningRequestBuilder().subject_name(subject)
		.add_extension(template_ext, critical=False)
		.add_extension(x509.SubjectAlternativeName([x509.DirectoryName(san_name)]), critical=False)
		.sign(key, hashes.SHA256()))
	csr_pem = csr.public_bytes(serialization.Encoding.PEM)
	key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())
	return key_pem.decode(), csr_pem.decode(), base64.b64encode(csr_pem).decode()


def cert_from_token(token_b64):
	"""ZATCA returns binarySecurityToken = base64( base64(DER) ). -> (cert object, base64 DER text)"""
	inner = base64.b64decode(token_b64).decode().strip()
	pem = "-----BEGIN CERTIFICATE-----\n" + "\n".join(inner[i:i + 64] for i in range(0, len(inner), 64)) + "\n-----END CERTIFICATE-----\n"
	return x509.load_pem_x509_certificate(pem.encode()), inner


# ---------------------------------------------------------------- invoice XML
def _t(parent, tag, text=None, **attrs):
	el = etree.SubElement(parent, q(tag))
	if text is not None:
		el.text = str(text)
	for k, v in attrs.items():
		el.set(k, str(v))
	return el


def _party(parent, wrapper, p, scheme_id, scheme_val):
	w = _t(parent, wrapper)
	party = _t(w, "cac:Party")
	if scheme_val:
		pid = _t(party, "cac:PartyIdentification")
		_t(pid, "cbc:ID", scheme_val, schemeID=scheme_id)
	a = p.get("address") or {}
	addr = _t(party, "cac:PostalAddress")
	_t(addr, "cbc:StreetName", a.get("street") or "-")
	_t(addr, "cbc:BuildingNumber", a.get("building") or "0000")
	_t(addr, "cbc:CitySubdivisionName", a.get("district") or a.get("governate") or "-")
	_t(addr, "cbc:CityName", a.get("city") or "-")
	_t(addr, "cbc:PostalZone", a.get("postal") or "00000")
	c = _t(addr, "cac:Country")
	_t(c, "cbc:IdentificationCode", a.get("country") or "SA")
	if p.get("tax_id"):
		ts = _t(party, "cac:PartyTaxScheme")
		_t(ts, "cbc:CompanyID", p["tax_id"])
		_t(_t(ts, "cac:TaxScheme"), "cbc:ID", "VAT")
	le = _t(party, "cac:PartyLegalEntity")
	_t(le, "cbc:RegistrationName", p.get("name") or "-")


def build_xml(inv, cfg, uuid, icv, pih_b64):
	"""Unsigned invoice (compact, no whitespace between elements). cfg: invoice_kind 'standard'|'simplified',
	zero_reason_code, zero_reason."""
	standard = cfg.get("invoice_kind") == "standard"
	root = etree.Element(q("inv:Invoice"), nsmap={None: NS["inv"], "cac": NS["cac"], "cbc": NS["cbc"], "ext": NS["ext"]})
	_t(root, "cbc:ProfileID", "reporting:1.0")
	_t(root, "cbc:ID", inv["id"])
	_t(root, "cbc:UUID", uuid)
	dt = inv["issue_dt"]
	_t(root, "cbc:IssueDate", dt.strftime("%Y-%m-%d"))
	_t(root, "cbc:IssueTime", dt.strftime("%H:%M:%S") + "Z")
	_t(root, "cbc:InvoiceTypeCode", TYPE_CODE.get(inv["kind"], "388"), name=("01" if standard else "02") + "00000")
	if inv.get("notes"):
		_t(root, "cbc:Note", inv["notes"], languageID="ar")
	cur = inv["currency"]
	_t(root, "cbc:DocumentCurrencyCode", cur)
	_t(root, "cbc:TaxCurrencyCode", "SAR")
	if inv.get("reference"):
		br = _t(root, "cac:BillingReference")
		_t(_t(br, "cac:InvoiceDocumentReference"), "cbc:ID", inv["reference"])
	_t(_t(root, "cac:AdditionalDocumentReference"), "cbc:ID", "ICV")
	root[-1].append(etree.Element(q("cbc:UUID")))
	root[-1][-1].text = str(icv)
	pr = _t(root, "cac:AdditionalDocumentReference")
	_t(pr, "cbc:ID", "PIH")
	_t(_t(pr, "cac:Attachment"), "cbc:EmbeddedDocumentBinaryObject", pih_b64, mimeCode="text/plain")
	qr = _t(root, "cac:AdditionalDocumentReference")
	_t(qr, "cbc:ID", "QR")
	_t(_t(qr, "cac:Attachment"), "cbc:EmbeddedDocumentBinaryObject", "QR-PLACEHOLDER", mimeCode="text/plain")
	sg = _t(root, "cac:Signature")
	_t(sg, "cbc:ID", "urn:oasis:names:specification:ubl:signature:Invoice")
	_t(sg, "cbc:SignatureMethod", "urn:oasis:names:specification:ubl:dsig:enveloped:xades")
	s, b = inv["seller"], inv["buyer"]
	_party(root, "cac:AccountingSupplierParty", s, "CRN", s.get("reg_no"))
	_party(root, "cac:AccountingCustomerParty", b, "NAT" if not b.get("tax_id") else "CRN", b.get("reg_no") or b.get("tax_id"))
	_t(_t(root, "cac:Delivery"), "cbc:ActualDeliveryDate", dt.strftime("%Y-%m-%d"))
	pm = _t(root, "cac:PaymentMeans")
	_t(pm, "cbc:PaymentMeansCode", (inv.get("payment") or {}).get("means") or "10")
	if inv["kind"] in ("credit", "debit"):
		_t(pm, "cbc:InstructionNote", inv.get("notes") or "Correction")
	t = inv["totals"]
	tx = _t(root, "cac:TaxTotal")
	_t(tx, "cbc:TaxAmount", money(t["tax"]), currencyID=cur)
	tx2 = _t(root, "cac:TaxTotal")
	_t(tx2, "cbc:TaxAmount", money(t["tax"] * (inv.get("rate_sar") or 1.0)), currencyID="SAR")
	groups = {}
	for ln in inv["lines"]:
		g = groups.setdefault(ln["tax_rate"], [0.0, 0.0])
		g[0] += ln["net"]
		g[1] += ln["tax"]
	for rate, (net, tax) in groups.items():
		sub = _t(tx2, "cac:TaxSubtotal")
		_t(sub, "cbc:TaxableAmount", money(net), currencyID=cur)
		_t(sub, "cbc:TaxAmount", money(tax), currencyID=cur)
		cat = _t(sub, "cac:TaxCategory")
		_t(cat, "cbc:ID", "S" if rate else "Z", schemeID="UN/ECE 5305", schemeAgencyID="6")
		_t(cat, "cbc:Percent", money(rate))
		if not rate:
			_t(cat, "cbc:TaxExemptionReasonCode", cfg.get("zero_reason_code") or "VATEX-SA-OOS")
			_t(cat, "cbc:TaxExemptionReason", cfg.get("zero_reason") or "Out of scope")
		_t(_t(cat, "cac:TaxScheme"), "cbc:ID", "VAT", schemeID="UN/ECE 5153", schemeAgencyID="6")
	lm = _t(root, "cac:LegalMonetaryTotal")
	_t(lm, "cbc:LineExtensionAmount", money(t["net"]), currencyID=cur)
	_t(lm, "cbc:TaxExclusiveAmount", money(t["net"]), currencyID=cur)
	_t(lm, "cbc:TaxInclusiveAmount", money(t["grand"]), currencyID=cur)
	_t(lm, "cbc:AllowanceTotalAmount", "0.00", currencyID=cur)
	_t(lm, "cbc:PrepaidAmount", "0.00", currencyID=cur)
	_t(lm, "cbc:PayableAmount", money(t["grand"]), currencyID=cur)
	for ln in inv["lines"]:
		il = _t(root, "cac:InvoiceLine")
		_t(il, "cbc:ID", ln["idx"])
		_t(il, "cbc:InvoicedQuantity", f"{ln['qty']:.6f}", unitCode=ln["unit"] or "PCE")
		_t(il, "cbc:LineExtensionAmount", money(ln["net"]), currencyID=cur)
		lt = _t(il, "cac:TaxTotal")
		_t(lt, "cbc:TaxAmount", money(ln["tax"]), currencyID=cur)
		_t(lt, "cbc:RoundingAmount", money(ln["net"] + ln["tax"]), currencyID=cur)
		item = _t(il, "cac:Item")
		_t(item, "cbc:Name", ln["description"] or ln["code"] or "-")
		ct = _t(item, "cac:ClassifiedTaxCategory")
		_t(ct, "cbc:ID", "S" if ln["tax_rate"] else "Z")
		_t(ct, "cbc:Percent", money(ln["tax_rate"]))
		_t(_t(ct, "cac:TaxScheme"), "cbc:ID", "VAT")
		price = _t(il, "cac:Price")
		_t(price, "cbc:PriceAmount", f"{(ln['net'] / ln['qty']) if ln['qty'] else 0:.6f}", currencyID=cur)
	return root


# ---------------------------------------------------------------- hash, signature, QR
def _strip_for_hash(root):
	c = etree.fromstring(etree.tostring(root))
	for el in c.findall(q("ext:UBLExtensions")) + c.findall(q("cac:Signature")):
		c.remove(el)
	for ad in c.findall(q("cac:AdditionalDocumentReference")):
		i = ad.find(q("cbc:ID"))
		if i is not None and i.text == "QR":
			c.remove(ad)
	return c


def invoice_hash(root):
	"""SHA-256 of the C14N form of the invoice without extensions, signature and QR -> (digest bytes, base64 text)."""
	canon = etree.tostring(_strip_for_hash(root), method="c14n")
	dg = hashlib.sha256(canon).digest()
	return dg, base64.b64encode(dg).decode()


def sign_digest(private_key_pem, digest):
	key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
	return key.sign(digest, ec.ECDSA(hashes.SHA256()))


def _issuer_name(cert):
	parts = cert.issuer.rfc4514_string().split(",")
	return ", ".join(p.strip() for p in parts)


def signed_properties(cert, cert_b64, signing_time):
	"""Returns the SignedProperties element and the digest ZATCA expects for it."""
	cert_digest = base64.b64encode(hashlib.sha256(cert_b64.encode()).hexdigest().encode()).decode()
	xml = (
		f'<xades:SignedProperties xmlns:xades="{XADES}" xmlns:ds="{DS}" Id="xadesSignedProperties"><xades:SignedSignatureProperties>'
		f"<xades:SigningTime>{signing_time}</xades:SigningTime><xades:SigningCertificate><xades:Cert><xades:CertDigest>"
		f'<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/><ds:DigestValue>{cert_digest}</ds:DigestValue></xades:CertDigest>'
		f"<xades:IssuerSerial><ds:X509IssuerName>{_issuer_name(cert)}</ds:X509IssuerName><ds:X509SerialNumber>{cert.serial_number}</ds:X509SerialNumber>"
		"</xades:IssuerSerial></xades:Cert></xades:SigningCertificate></xades:SignedSignatureProperties></xades:SignedProperties>"
	)
	el = etree.fromstring(xml)
	canon = etree.tostring(el, method="c14n", exclusive=True)
	prop_digest = base64.b64encode(hashlib.sha256(canon).hexdigest().encode()).decode()
	return xml, prop_digest


def qr_tlv(fields):
	"""fields: {tag(int): bytes|str}. TLV with one-byte length, base64 of the whole."""
	out = b""
	for tag in sorted(fields):
		v = fields[tag]
		v = v.encode() if isinstance(v, str) else v
		if len(v) > 255:
			raise ValueError(f"QR tag {tag} is longer than 255 bytes")
		out += bytes([tag, len(v)]) + v
	return base64.b64encode(out).decode()


def sign_invoice(root, private_key_pem, cert_token_b64, signing_dt=None, simplified=True):
	"""Embeds the XAdES signature and the QR. Returns (signed xml string, invoice hash b64, qr b64)."""
	cert, cert_b64 = cert_from_token(cert_token_b64)
	digest, hash_b64 = invoice_hash(root)
	sig_b64 = base64.b64encode(sign_digest(private_key_pem, digest)).decode()
	stime = (signing_dt or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
	sp_xml, sp_digest = signed_properties(cert, cert_b64, stime)
	ubl = (
		f'<ext:UBLExtensions xmlns:ext="{NS["ext"]}"><ext:UBLExtension><ext:ExtensionURI>urn:oasis:names:specification:ubl:dsig:enveloped:xades</ext:ExtensionURI>'
		'<ext:ExtensionContent><sig:UBLDocumentSignatures xmlns:sig="urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2" '
		'xmlns:sac="urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2" '
		'xmlns:sbc="urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2"><sac:SignatureInformation>'
		"<cbc:ID xmlns:cbc=\"%s\">urn:oasis:names:specification:ubl:signature:1</cbc:ID><sbc:ReferencedSignatureID>urn:oasis:names:specification:ubl:signature:Invoice</sbc:ReferencedSignatureID>"
		f'<ds:Signature xmlns:ds="{DS}" Id="signature"><ds:SignedInfo><ds:CanonicalizationMethod Algorithm="http://www.w3.org/2006/12/xml-c14n11"/>'
		'<ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"/>'
		'<ds:Reference Id="invoiceSignedData" URI=""><ds:Transforms>'
		'<ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116"><ds:XPath>not(//ancestor-or-self::ext:UBLExtensions)</ds:XPath></ds:Transform>'
		'<ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116"><ds:XPath>not(//ancestor-or-self::cac:Signature)</ds:XPath></ds:Transform>'
		"<ds:Transform Algorithm=\"http://www.w3.org/TR/1999/REC-xpath-19991116\"><ds:XPath>not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])</ds:XPath></ds:Transform>"
		'<ds:Transform Algorithm="http://www.w3.org/2006/12/xml-c14n11"/></ds:Transforms>'
		f'<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/><ds:DigestValue>{hash_b64}</ds:DigestValue></ds:Reference>'
		'<ds:Reference Type="http://www.w3.org/2000/09/xmldsig#SignatureProperties" URI="#xadesSignedProperties">'
		f'<ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/><ds:DigestValue>{sp_digest}</ds:DigestValue></ds:Reference></ds:SignedInfo>'
		f"<ds:SignatureValue>{sig_b64}</ds:SignatureValue><ds:KeyInfo><ds:X509Data><ds:X509Certificate>{cert_b64}</ds:X509Certificate></ds:X509Data></ds:KeyInfo>"
		f'<ds:Object><xades:QualifyingProperties xmlns:xades="{XADES}" Target="signature">{sp_xml}</xades:QualifyingProperties></ds:Object>'
		"</ds:Signature></sac:SignatureInformation></sig:UBLDocumentSignatures></ext:ExtensionContent></ext:UBLExtension></ext:UBLExtensions>"
	) % NS["cbc"]
	ext_el = etree.fromstring(ubl)
	root.insert(0, ext_el)
	pk = cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
	seller = root.find(q("cac:AccountingSupplierParty")).find(".//" + q("cbc:RegistrationName")).text
	vat = root.find(q("cac:AccountingSupplierParty")).find(".//" + q("cbc:CompanyID")).text
	issue = root.find(q("cbc:IssueDate")).text + "T" + root.find(q("cbc:IssueTime")).text
	total = root.find(q("cac:LegalMonetaryTotal")).find(q("cbc:TaxInclusiveAmount")).text
	vat_amt = root.findall(q("cac:TaxTotal"))[0].find(q("cbc:TaxAmount")).text
	fields = {1: seller, 2: vat, 3: issue, 4: total, 5: vat_amt, 6: hash_b64, 7: sig_b64, 8: pk}
	if simplified:
		fields[9] = cert.signature
	qr = qr_tlv(fields)
	for ad in root.findall(q("cac:AdditionalDocumentReference")):
		i = ad.find(q("cbc:ID"))
		if i is not None and i.text == "QR":
			ad.find(".//" + q("cbc:EmbeddedDocumentBinaryObject")).text = qr
	xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode()
	return xml, hash_b64, qr


def new_uuid():
	return str(_uuid.uuid4())


FIRST_PIH = base64.b64encode(hashlib.sha256(b"0").hexdigest().encode()).decode()


def submission_body(signed_xml, hash_b64, uuid):
	return {"invoiceHash": hash_b64, "uuid": uuid, "invoice": base64.b64encode(signed_xml.encode()).decode()}


def parse_response(resp, mode):
	"""reporting/clearance JSON -> (status, error text, cleared xml or None)."""
	resp = resp or {}
	v = resp.get("validationResults") or {}
	errs = [f"{e.get('code')}: {e.get('message')}" for e in v.get("errorMessages") or []]
	warns = [f"{e.get('code')}: {e.get('message')}" for e in v.get("warningMessages") or []]
	st = (resp.get("reportingStatus") or resp.get("clearanceStatus") or v.get("status") or "").upper()
	ok = st in ("REPORTED", "CLEARED", "PASS") and not errs
	cleared = None
	if resp.get("clearedInvoice"):
		cleared = base64.b64decode(resp["clearedInvoice"]).decode("utf-8", "replace")
	return ("Accepted" if ok else "Rejected"), "; ".join(errs or warns), cleared
