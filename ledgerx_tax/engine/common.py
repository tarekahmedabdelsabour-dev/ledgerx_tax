"""Shared, database-free helpers. The neutral invoice is a plain dict:

{
 "id": "SINV-0001", "issue_dt": datetime (UTC), "kind": "invoice|credit|debit",
 "currency": "EGP", "rate": 1.0, "reference": "SINV-0000" or "",
 "seller": {"name","tax_id","reg_no","branch","address":{"country","governate","city","street","building","postal"}},
 "buyer":  {"name","tax_id","type":"B|P|F","address":{...}},
 "lines": [{"description","code","code_type","unit","qty","price","discount","net","tax_rate","tax","total"}],
 "totals": {"gross","discount","net","tax","grand"},
 "payment": {"means": "10"}, "notes": ""
}
Amounts are in the currency of the invoice unless a key says otherwise."""
from decimal import ROUND_HALF_UP, Decimal


def d(x):
	return Decimal(str(x or 0))


def r(x, places=2):
	q = Decimal(1).scaleb(-places)
	return float(d(x).quantize(q, rounding=ROUND_HALF_UP))


def build_lines(items, tax_rate_default=0.0):
	"""items: [{description, code, unit, qty, rate, discount_amount, tax_rate?}] -> neutral lines + totals.
	price is the unit price before discount; net = qty*price - discount; tax = net*rate/100."""
	lines, gross, disc, net_t, tax_t = [], d(0), d(0), d(0), d(0)
	for i, it in enumerate(items, 1):
		qty, price, dis = d(it.get("qty")), d(it.get("rate")), d(it.get("discount_amount"))
		rate = d(it["tax_rate"] if it.get("tax_rate") is not None else tax_rate_default)
		line_gross = qty * price
		net = d(r(line_gross - dis))
		tax = d(r(net * rate / 100))  # rounded per line so the totals are the sum of what the authority checks
		lines.append({
			"idx": i, "description": it.get("description") or it.get("code") or "", "code": it.get("code") or "",
			"code_type": it.get("code_type") or "EGS", "unit": it.get("unit") or "EA", "qty": float(qty),
			"price": float(price), "discount": float(dis), "net": float(net), "tax_rate": float(rate),
			"tax": float(tax), "total": float(net + tax), "gross": float(line_gross),
		})
		gross += line_gross
		disc += dis
		net_t += net
		tax_t += tax
	totals = {"gross": float(gross), "discount": float(disc), "net": float(net_t), "tax": float(tax_t), "grand": float(net_t + tax_t)}
	return lines, totals


def money(x, places=2):
	return f"{r(x, places):.{places}f}"
