"""Any other system: URL + headers + Jinja body template."""
import base64
import json

from ledgerx_tax.engine import generic

from .http import call, dump


def _headers(cfg, http, ctx):
	h = {}
	if cfg.get("headers_json"):
		h.update(json.loads(cfg["headers_json"]))
	t = cfg.get("auth_type") or "None"
	if t == "Bearer Token":
		h["Authorization"] = f"Bearer {cfg.get('auth_secret')}"
	elif t == "Basic":
		h["Authorization"] = "Basic " + base64.b64encode(f"{cfg.get('auth_user')}:{cfg.get('auth_secret')}".encode()).decode()
	elif t == "Custom Header":
		h[cfg.get("auth_header") or "X-Api-Key"] = cfg.get("auth_secret") or ""
	elif t == "Client Credentials" and cfg.get("identity_url"):
		st, body, text = http("POST", cfg["identity_url"], headers={"Content-Type": "application/x-www-form-urlencoded"}, data=f"grant_type=client_credentials&client_id={cfg.get('auth_user')}&client_secret={cfg.get('auth_secret')}")
		if st != 200 or not (body or {}).get("access_token"):
			raise RuntimeError(f"Sign-in failed ({st}): {text[:300]}")
		h["Authorization"] = "Bearer " + body["access_token"]
	return h


def send(cfg, inv, ctx):
	http = ctx.get("http", call)
	if not cfg.get("api_url") or not cfg.get("body_template"):
		raise RuntimeError("Set the API address and the body template on the connection.")
	headers = _headers(cfg, http, ctx)
	headers.setdefault("Content-Type", cfg.get("content_type") or "application/json")
	body = generic.render(cfg["body_template"], inv, cfg)
	st, resp, text = http(cfg.get("http_method") or "POST", cfg["api_url"], headers=headers, data=body.encode())
	out = {"payload": body, "response": dump(resp if resp is not None else text), "http_status": st}
	if 200 <= st < 300:
		status, uuid, err = generic.interpret(resp or {}, cfg.get("ok_path"), cfg.get("ok_value"), cfg.get("uuid_path"), cfg.get("error_path"))
		out.update({"status": status, "uuid": uuid, "error": err})
		return out
	out.update({"status": "Rejected" if st in (400, 401, 403, 422) else "Failed", "error": f"{st}: {text[:500]}"})
	return out


def check(cfg, sub, ctx):
	return {"status": sub.get("status"), "error": sub.get("error") or ""}


def cancel(cfg, sub, reason, ctx):
	return {"status": "Cancelled", "error": "", "response": "Cancelled locally: this connection has no cancel call."}


def test(cfg, ctx):
	return "Address and template set." if cfg.get("api_url") and cfg.get("body_template") else "Set the API address and the body template."
