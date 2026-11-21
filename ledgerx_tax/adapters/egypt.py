"""Egypt ETA: login, sign, submit, check, cancel."""
import base64
import time

from ledgerx_tax.engine import egypt as eng

from .http import call, dump

HOSTS = {
	"Test": ("https://api.preprod.invoicing.eta.gov.eg", "https://id.preprod.eta.gov.eg"),
	"Simulation": ("https://api.preprod.invoicing.eta.gov.eg", "https://id.preprod.eta.gov.eg"),
	"Production": ("https://api.invoicing.eta.gov.eg", "https://id.eta.gov.eg"),
}


def hosts(cfg):
	api, ident = HOSTS.get(cfg.get("environment"), HOSTS["Production"])
	return (cfg.get("api_url") or api).rstrip("/"), (cfg.get("identity_url") or ident).rstrip("/")


def get_token(cfg, http=call, cache=None):
	key = f"einv_eg_token::{cfg['name']}"
	if cache is not None:
		tok = cache.get(key)
		if tok:
			return tok
	_, ident = hosts(cfg)
	basic = base64.b64encode(f"{cfg['auth_user']}:{cfg['auth_secret']}".encode()).decode()
	headers = {"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}
	if cfg.get("on_behalf_of"):
		headers["onbehalfof"] = cfg["on_behalf_of"]
	status, body, text = http("POST", ident + "/connect/token", headers=headers, data="grant_type=client_credentials&scope=InvoicingAPI")
	if status != 200 or not (body or {}).get("access_token"):
		raise RuntimeError(f"Login to the tax authority failed ({status}): {text[:300]}")
	if cache is not None:
		cache.set(key, body["access_token"], max(60, int(body.get("expires_in", 3600)) - 120))
	return body["access_token"]


def sign(cfg, doc, http=call):
	canon, digest = eng.canonical_hash(doc)
	if cfg.get("signer") == "None (test only)" or not cfg.get("signer_url"):
		return doc, digest.hex(), "unsigned"
	headers = {"Content-Type": "application/json"}
	if cfg.get("signer_token"):
		headers["Authorization"] = f"Bearer {cfg['signer_token']}"
	status, body, text = http("POST", cfg["signer_url"], headers=headers, json={"canonical": canon, "sha256": digest.hex()})
	sig = (body or {}).get("signature")
	if status != 200 or not sig:
		raise RuntimeError(f"The signing service did not return a signature ({status}): {text[:300]}")
	return eng.with_signature(doc, sig), digest.hex(), "signed"


def send(cfg, inv, ctx):
	http = ctx.get("http", call)
	api, _ = hosts(cfg)
	token = get_token(cfg, http, ctx.get("cache"))
	doc = eng.build_document(inv, {"taxpayer_activity_code": cfg.get("activity_code"), "issuer_type": cfg.get("issuer_type"), "tax_type": cfg.get("tax_type"), "tax_subtype": cfg.get("tax_subtype")})
	signed, hexdigest, mode = sign(cfg, doc, http)
	payload = {"documents": [signed]}
	status, body, text = http("POST", api + "/api/v1.0/documentsubmissions", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
	out = {"payload": dump(payload), "response": dump(body if body is not None else text), "hash": hexdigest, "http_status": status}
	if status in (200, 202) and body:
		st, uuid, long_id, err = eng.parse_response(body)
		out.update({"status": "Submitted" if st == "Accepted" else st, "uuid": uuid, "reference": long_id, "error": err})
		if mode == "unsigned" and st == "Accepted":
			out["error"] = "Sent without a signature (test mode)."
		return out
	if status == 422 or status == 400 or status == 403:
		out.update({"status": "Rejected", "error": f"{status}: {text[:400]}"})
		return out
	out.update({"status": "Failed", "error": f"{status}: {text[:400]}"})
	return out


def check(cfg, sub, ctx):
	"""Validation at the authority is asynchronous: ask for the final state of the document."""
	http = ctx.get("http", call)
	api, _ = hosts(cfg)
	token = get_token(cfg, http, ctx.get("cache"))
	status, body, text = http("GET", f"{api}/api/v1.0/documents/{sub['uuid']}/details", headers={"Authorization": f"Bearer {token}"})
	if status != 200 or not body:
		return {"status": "Submitted", "error": f"Could not read the status ({status})", "response": dump(text)}
	st = (body.get("status") or "").lower()
	if st == "valid":
		return {"status": "Accepted", "error": "", "response": dump(body)}
	if st in ("invalid", "rejected"):
		steps = (body.get("validationResults") or {}).get("validationSteps") or []
		errs = [f"{s.get('name')}: {(s.get('error') or {}).get('error') or (s.get('error') or {}).get('message') or ''}" for s in steps if s.get("status") == "Invalid"]
		return {"status": "Rejected", "error": "; ".join(errs)[:900] or "Invalid", "response": dump(body)}
	if st == "cancelled":
		return {"status": "Cancelled", "error": "", "response": dump(body)}
	return {"status": "Submitted", "error": "", "response": dump(body)}


def cancel(cfg, sub, reason, ctx):
	http = ctx.get("http", call)
	api, _ = hosts(cfg)
	token = get_token(cfg, http, ctx.get("cache"))
	status, body, text = http("PUT", f"{api}/api/v1.0/documents/state/{sub['uuid']}/state", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"status": "cancelled", "reason": reason or "Cancelled"})
	if status == 200:
		return {"status": "Cancelled", "error": "", "response": dump(body or text)}
	raise RuntimeError(f"The tax authority did not accept the cancellation ({status}): {text[:300]}")


def test(cfg, ctx):
	get_token(cfg, ctx.get("http", call), None)
	return "Login to the tax authority works."


_ = time
