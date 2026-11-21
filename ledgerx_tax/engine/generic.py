"""Any other system: a connection describes URL, headers and a Jinja body template.
The template receives {inv, cfg}; the response mapping reads dotted paths from the JSON answer."""
import json
from jinja2 import Environment, StrictUndefined

_env = Environment(autoescape=False, undefined=StrictUndefined)


def render(template, inv, cfg=None):
	return _env.from_string(template).render(inv=inv, cfg=cfg or {}, tojson=json.dumps)


def dig(obj, path):
	cur = obj
	for part in (path or "").split("."):
		if not part:
			continue
		if isinstance(cur, list):
			try:
				cur = cur[int(part)]
			except (ValueError, IndexError):
				return None
		elif isinstance(cur, dict):
			cur = cur.get(part)
		else:
			return None
	return cur


def interpret(resp, ok_path, ok_value, uuid_path="", error_path=""):
	ok = dig(resp, ok_path) if ok_path else True
	good = (str(ok).lower() == str(ok_value).lower()) if ok_path else True
	return ("Accepted" if good else "Rejected"), (dig(resp, uuid_path) if uuid_path else None), (str(dig(resp, error_path) or "") if not good else "")
