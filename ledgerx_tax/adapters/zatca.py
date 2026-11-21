"""Saudi ZATCA: onboarding (CSR, compliance, production certificates) and reporting / clearance."""
import base64
from datetime import datetime

from ledgerx_tax.engine import common
from ledgerx_tax.engine import zatca as eng

from .http import call, dump


def base(cfg):
	return (cfg.get("api_url") or eng.URLS.get(cfg.get("environment"), eng.URLS["Production"])).rstrip("/")


def _basic(token, secret):
	return "Basic " + base64.b64encode(f"{token}:{secret}".encode()).decode()


def kind_of(cfg, inv):
	k = cfg.get("invoice_kind") or "Auto"
	if k == "Auto":
		return "standard" if (inv["buyer"].get("tax_id")) else "simplified"
	return k.lower()


def generate_csr(cfg):
	"""-> (private key pem, csr pem). Stored by the caller; the key never leaves the site."""
	key, csr_pem, csr_b64 = eng.make_csr(
		cfg["tax_id"], cfg.get("company_name") or cfg["company"], cfg.get("org_unit") or cfg.get("company_name") or cfg["company"],
		cfg.get("common_name") or "EGS1", cfg.get("egs_serial") or "1", cfg.get("full_address") or cfg.get("city") or "Riyadh",
		cfg.get("industry") or "Supply", cfg.get("environment") or "Simulation")
	return key, csr_pem, csr_b64


def compliance_csid(cfg, csr_b64, otp, http=call):
	st, body, text = http("POST", base(cfg) + "/compliance", headers={"Content-Type": "application/json", "OTP": otp, "Accept-Version": "V2", "Accept-Language": "en"}, json={"csr": csr_b64})
	if st != 200 or not (body or {}).get("binarySecurityToken"):
		raise RuntimeError(f"ZATCA did not issue the compliance certificate ({st}): {text[:400]}")
	return body["binarySecurityToken"], body["secret"], str(body.get("requestID"))


def production_csid(cfg, http=call):
	st, body, text = http("POST", base(cfg) + "/production/csids", headers={"Content-Type": "application/json", "Authorization": _basic(cfg["compliance_token"], cfg["compliance_secret"]), "Accept-Version": "V2"}, json={"compliance_request_id": cfg["compliance_request_id"]})
	if st != 200 or not (body or {}).get("binarySecurityToken"):
		raise RuntimeError(f"ZATCA did not issue the production certificate ({st}): {text[:400]}")
	return body["binarySecurityToken"], body["secret"]


def _prepare(cfg, inv, icv, pih, token):
	kind = kind_of(cfg, inv)
	uuid = eng.new_uuid()
	root = eng.build_xml(inv, {"invoice_kind": kind, "zero_reason_code": cfg.get("zero_reason_code"), "zero_reason": cfg.get("zero_reason")}, uuid, icv, pih)
	xml, hash_b64, qr = eng.sign_invoice(root, cfg["private_key"], token, simplified=(kind == "simplified"))
	return kind, uuid, xml, hash_b64, qr


def send(cfg, inv, ctx):
	http = ctx.get("http", call)
	if not (cfg.get("production_token") and cfg.get("production_secret") and cfg.get("private_key")):
		raise RuntimeError("Finish the Saudi onboarding first: this connection has no production certificate.")
	icv = int(ctx.get("icv") or 0) + 1
	pih = ctx.get("pih") or eng.FIRST_PIH
	inv = dict(inv, rate_sar=inv.get("rate") or 1.0)
	kind, uuid, xml, hash_b64, qr = _prepare(cfg, inv, icv, pih, cfg["production_token"])
	body = eng.submission_body(xml, hash_b64, uuid)
	path = "/invoices/clearance/single" if kind == "standard" else "/invoices/reporting/single"
	headers = {"Content-Type": "application/json", "Authorization": _basic(cfg["production_token"], cfg["production_secret"]), "Accept-Version": "V2", "Accept-Language": "en", "Clearance-Status": "1" if kind == "standard" else "0"}
	st, resp, text = http("POST", base(cfg) + path, headers=headers, json=body)
	out = {"payload": xml, "response": dump(resp if resp is not None else text), "hash": hash_b64, "qr": qr, "uuid": uuid, "reference": f"ICV {icv}", "http_status": st, "icv": icv}
	if st in (200, 202) and resp is not None:
		status, err, cleared = eng.parse_response(resp, kind)
		out.update({"status": status, "error": err})
		if cleared:
			out["payload"] = cleared
		out["advance_chain"] = status == "Accepted"
		return out
	if st in (400, 401, 403, 409, 422):
		out.update({"status": "Rejected", "error": f"{st}: {text[:500]}"})
		return out
	out.update({"status": "Failed", "error": f"{st}: {text[:500]}"})
	return out


def sample_invoices(cfg, inv_template):
	"""The compliance check wants a standard and a simplified invoice plus their credit and debit notes."""
	out = []
	for kind in ("standard", "simplified"):
		for doc_kind in ("invoice", "credit", "debit"):
			inv = dict(inv_template, kind=doc_kind, id=f"TEST-{kind[:3].upper()}-{doc_kind[:3].upper()}", issue_dt=datetime.utcnow(), reference=("TEST-" + kind[:3].upper() + "-INV") if doc_kind != "invoice" else "", notes="Test" if doc_kind != "invoice" else "")
			inv["buyer"] = dict(inv_template["buyer"], tax_id=inv_template["buyer"].get("tax_id") or "399999999900003") if kind == "standard" else dict(inv_template["buyer"], tax_id="")
			out.append((kind, inv))
	return out


def run_compliance(cfg, inv_template, http=call):
	"""Signs sample invoices with the compliance certificate and posts them. -> list of (name, status, message)."""
	results, icv, pih = [], 0, eng.FIRST_PIH
	for kind, inv in sample_invoices(cfg, inv_template):
		icv += 1
		inv = dict(inv, rate_sar=1.0)
		uuid = eng.new_uuid()
		root = eng.build_xml(inv, {"invoice_kind": kind, "zero_reason_code": cfg.get("zero_reason_code"), "zero_reason": cfg.get("zero_reason")}, uuid, icv, pih)
		xml, h, _qr = eng.sign_invoice(root, cfg["private_key"], cfg["compliance_token"], simplified=(kind == "simplified"))
		st, resp, text = http("POST", base(cfg) + "/compliance/invoices", headers={"Content-Type": "application/json", "Authorization": _basic(cfg["compliance_token"], cfg["compliance_secret"]), "Accept-Version": "V2", "Accept-Language": "en"}, json=eng.submission_body(xml, h, uuid))
		status, err, _ = eng.parse_response(resp or {}, kind)
		results.append((inv["id"], status if st in (200, 202) else f"HTTP {st}", err or text[:300]))
		if status == "Accepted":
			pih = h
	return results


def check(cfg, sub, ctx):
	return {"status": sub.get("status"), "error": sub.get("error") or ""}


def cancel(cfg, sub, reason, ctx):
	raise RuntimeError("A Saudi tax invoice cannot be cancelled. Issue a credit note instead.")


def test(cfg, ctx):
	need = [k for k in ("tax_id", "private_key", "production_token", "production_secret") if not cfg.get(k)]
	if need:
		return "Not ready: missing " + ", ".join(need)
	return "Certificates are in place. Send a test invoice to confirm."
