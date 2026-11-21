"""Egypt Tax Authority (ETA) e-invoice v1.0 document, serialization and signature input.
Spec: sdk.invoicing.eta.gov.eg (Invoice v1.0, Document Serialization Approach, Signature creation)."""
import hashlib
import json
from .common import r

DOC_TYPES = {"invoice": "i", "credit": "c", "debit": "d"}


def _addr(a, branch=None):
	a = a or {}
	out = {
		"country": a.get("country") or "EG", "governate": a.get("governate") or "", "regionCity": a.get("city") or "",
		"street": a.get("street") or "", "buildingNumber": a.get("building") or "",
	}
	if branch is not None:
		out = {"branchId": branch or "0", **out}
	if a.get("postal"):
		out["postalCode"] = a["postal"]
	return out


def build_document(inv, cfg):
	"""cfg: taxpayer_activity_code, issuer_type (B/P/F), tax_type (default T1), version."""
	seller, buyer = inv["seller"], inv["buyer"]
	cur, rate = inv["currency"], inv.get("rate") or 1.0
	lines = []
	for ln in inv["lines"]:
		egp = lambda v: r(v * rate, 5)  # noqa: E731
		unit_value = {"currencySold": cur, "amountEGP": egp(ln["price"])}
		if cur != "EGP":
			unit_value.update({"amountSold": r(ln["price"], 5), "currencyExchangeRate": r(rate, 5)})
		sales_total = egp(ln["gross"])
		item = {
			"description": ln["description"], "itemType": ln.get("code_type") or "EGS", "itemCode": ln["code"],
			"unitType": ln["unit"], "quantity": r(ln["qty"], 5), "internalCode": ln["code"], "salesTotal": sales_total,
			"total": egp(ln["total"]), "valueDifference": 0.0, "totalTaxableFees": 0.0, "netTotal": egp(ln["net"]),
			"itemsDiscount": egp(ln["discount"]), "unitValue": unit_value,
			"taxableItems": [{"taxType": cfg.get("tax_type") or "T1", "amount": egp(ln["tax"]), "subType": cfg.get("tax_subtype") or "V009", "rate": r(ln["tax_rate"], 2)}],
		}
		if ln["discount"]:
			item["discount"] = {"rate": 0, "amount": egp(ln["discount"])}
		lines.append(item)
	t = inv["totals"]
	doc = {
		"issuer": {"type": cfg.get("issuer_type") or "B", "id": seller["tax_id"], "name": seller["name"], "address": _addr(seller.get("address"), seller.get("branch") or "0")},
		"receiver": {"type": buyer.get("type") or "P", "id": buyer.get("tax_id") or "", "name": buyer.get("name") or "", "address": _addr(buyer.get("address"))},
		"documentType": DOC_TYPES.get(inv["kind"], "i"), "documentTypeVersion": cfg.get("version") or "1.0",
		"dateTimeIssued": inv["issue_dt"].strftime("%Y-%m-%dT%H:%M:%SZ"), "taxpayerActivityCode": cfg["taxpayer_activity_code"],
		"internalId": inv["id"], "invoiceLines": lines,
		"totalDiscountAmount": r(t["discount"] * rate, 5), "totalSalesAmount": r(t["gross"] * rate, 5), "netAmount": r(t["net"] * rate, 5),
		"taxTotals": [{"taxType": cfg.get("tax_type") or "T1", "amount": r(t["tax"] * rate, 5)}],
		"totalAmount": r(t["grand"] * rate, 5), "extraDiscountAmount": 0.0,
		"totalItemsDiscountAmount": r(t["discount"] * rate, 5),
	}
	if inv.get("reference"):
		doc["references"] = [inv["reference"]]
	return doc


def serialize(node):
	"""ETA canonical string: property names upper-cased and quoted, simple values quoted unchanged,
	arrays: name once, then the name before every element. Signature is excluded by the caller."""
	out = []
	if isinstance(node, dict):
		for k, v in node.items():
			name = f'"{str(k).upper()}"'
			if isinstance(v, list):
				out.append(name)
				for el in v:
					out.append(name)
					out.append(serialize(el))
			else:
				out.append(name)
				out.append(serialize(v))
		return "".join(out)
	return f'"{_plain(node)}"'


def _plain(v):
	if isinstance(v, bool):
		return "true" if v else "false"
	if isinstance(v, float):
		s = repr(v)
		return s
	return str(v)


def canonical_hash(doc):
	"""SHA-256 over the UTF-8 bytes of the canonical form; this is what the CAdES-BES signature covers."""
	src = {k: v for k, v in doc.items() if k != "signatures"}
	canon = serialize(src)
	return canon, hashlib.sha256(canon.encode("utf-8")).digest()


def with_signature(doc, cades_b64):
	out = dict(doc)
	out["signatures"] = [{"signatureType": "I", "value": cades_b64}]
	return out


def parse_response(resp):
	"""-> (status, uuid, long_id, error). resp is the decoded JSON of POST /documentsubmissions."""
	acc = (resp or {}).get("acceptedDocuments") or []
	rej = (resp or {}).get("rejectedDocuments") or []
	if acc:
		a = acc[0]
		return "Accepted", a.get("uuid"), a.get("longId"), ""
	if rej:
		e = rej[0].get("error") or {}
		det = "; ".join(x.get("message", "") for x in e.get("details") or [])
		return "Rejected", None, None, (e.get("message", "") + (" - " + det if det else "")).strip()
	return "Failed", None, None, json.dumps(resp or {}, ensure_ascii=False)[:500]
