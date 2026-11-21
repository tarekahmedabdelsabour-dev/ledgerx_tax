"""One place for outgoing requests so the adapters can be tested with a fake."""
import json as _json


def call(method, url, headers=None, json=None, data=None, timeout=60):
	"""-> (status_code, parsed json or None, text). Network errors raise requests exceptions (the caller marks Failed and retries)."""
	import requests

	resp = requests.request(method, url, headers=headers or {}, json=json, data=data, timeout=timeout)
	try:
		parsed = resp.json()
	except ValueError:
		parsed = None
	return resp.status_code, parsed, resp.text


def dump(obj, limit=200000):
	s = obj if isinstance(obj, str) else _json.dumps(obj, ensure_ascii=False, indent=1, default=str)
	return s[:limit]
