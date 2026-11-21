"""UAE: PINT-AE document sent to an Accredited Service Provider."""
import base64

from ledgerx_tax.engine import generic
from ledgerx_tax.engine import uae as eng

from .custom import _headers
from .http import call, dump


def send(cfg, inv, ctx):
	http = ctx.get("http", call)
	if not cfg.get("api_url"):
		raise RuntimeError("Set the API address of your accredited service provider on the connection.")
	inv = dict(inv, seller=dict(inv["seller"], endpoint=inv["seller"].get("tax_id")), buyer=dict(inv["buyer"], endpoint=inv["buyer"].get("tax_id")))
	xml = eng.to_string(eng.build_xml(inv, {"endpoint_scheme": cfg.get("endpoint_scheme"), "type_flags": cfg.get("type_flags")}))
	headers = _headers(cfg, http, ctx)
	data = None
	body = None
	if cfg.get("body_template"):
		rendered = _render_with_xml(cfg, inv, xml)
		data = rendered.encode()
		headers.setdefault("Content-Type", cfg.get("content_type") or "application/json")
	elif cfg.get("payload_format") == "JSON with XML inside":
		body = {"id": inv["id"], "type": inv["kind"], "invoice": base64.b64encode(xml.encode()).decode()}
		headers.setdefault("Content-Type", "application/json")
	else:
		data = xml.encode()
		headers.setdefault("Content-Type", "application/xml")
	st, resp, text = http(cfg.get("http_method") or "POST", cfg["api_url"], headers=headers, json=body, data=data)
	out = {"payload": xml, "response": dump(resp if resp is not None else text), "http_status": st}
	if 200 <= st < 300:
		status, uuid, err = generic.interpret(resp or {}, cfg.get("ok_path"), cfg.get("ok_value"), cfg.get("uuid_path"), cfg.get("error_path"))
		out.update({"status": "Submitted" if status == "Accepted" else status, "uuid": uuid, "error": err})
		return out
	out.update({"status": "Rejected" if st in (400, 401, 403, 422) else "Failed", "error": f"{st}: {text[:500]}"})
	return out


def _render_with_xml(cfg, inv, xml):
	return generic.render(cfg["body_template"], inv, dict(cfg, xml=xml, xml_b64=base64.b64encode(xml.encode()).decode()))


def check(cfg, sub, ctx):
	return {"status": sub.get("status"), "error": sub.get("error") or ""}


def cancel(cfg, sub, reason, ctx):
	raise RuntimeError("A UAE tax invoice cannot be cancelled. Issue a credit note instead.")


def test(cfg, ctx):
	return "Address set." if cfg.get("api_url") else "Set the service provider address first."
