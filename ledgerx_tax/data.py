"""Reads the database and turns a Sales Invoice into the neutral invoice the engines understand."""
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import flt, get_datetime, get_system_timezone

from ledgerx_tax.engine import common

SECRETS = ("auth_secret", "signer_token", "private_key", "compliance_token", "compliance_secret", "production_token", "production_secret")


def connection_for(company):
	name = frappe.db.get_value("E-Invoice Connection", {"company": company, "enabled": 1}, "name")
	return frappe.get_doc("E-Invoice Connection", name) if name else None


def cfg_of(conn):
	"""Plain dict of a connection with its passwords resolved (never log or return this to the browser)."""
	cfg = {k: conn.get(k) for k in [df.fieldname for df in conn.meta.fields if df.fieldtype not in ("Section Break", "Column Break", "Password")]}
	for k in SECRETS:
		cfg[k] = conn.get_password(k, raise_exception=False) if conn.get(k) is not None else None
	cfg["name"] = conn.name
	cfg["company"] = conn.company
	cfg["company_name"] = frappe.db.get_value("Company", conn.company, "company_name") or conn.company
	return cfg


def _country_code(country):
	if not country:
		return ""
	code = frappe.db.get_value("Country", country, "code")
	return (code or country[:2]).upper()


def _address(name):
	if not name:
		return {}
	a = frappe.db.get_value("Address", name, ["address_line1", "address_line2", "city", "state", "country", "pincode"], as_dict=True)
	if not a:
		return {}
	return {"street": " ".join(x for x in (a.address_line1, a.address_line2) if x), "city": a.city or "", "governate": a.state or a.city or "", "country": _country_code(a.country), "postal": a.pincode or "", "building": "0"}


def _tax_rate(si, item):
	rates = []
	try:
		import json

		rates = list(json.loads(item.item_tax_rate or "{}").values())
	except Exception:
		pass
	if rates:
		return flt(rates[0])
	for t in si.get("taxes") or []:
		if flt(t.rate) and t.charge_type in ("On Net Total", "On Previous Row Total", "On Previous Row Amount"):
			return flt(t.rate)
	return 0.0


def _utc(si):
	dt = get_datetime(f"{si.posting_date} {si.posting_time or '00:00:00'}")
	return dt.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def build_invoice(si, cfg):
	"""Neutral invoice from a Sales Invoice document and a connection dict."""
	cust = frappe.db.get_value("Customer", si.customer, ["customer_name", "tax_id", "einv_buyer_type", "einv_reg_no"], as_dict=True) or {}
	tax_id = cust.get("tax_id") or si.get("tax_id") or ""
	btype = {"Business": "B", "Person": "P", "Foreigner": "F"}.get(cust.get("einv_buyer_type")) or ("B" if tax_id else "P")
	buyer = {"name": cust.get("customer_name") or si.customer_name, "tax_id": tax_id, "type": btype, "reg_no": cust.get("einv_reg_no") or "", "address": _address(si.customer_address)}
	seller = {"name": cfg["company_name"], "tax_id": cfg["tax_id"], "reg_no": cfg.get("reg_no") or "", "branch": cfg.get("branch_id") or "0",
		"address": {"country": cfg.get("country") or "", "governate": cfg.get("governate") or "", "city": cfg.get("city") or "", "street": cfg.get("street") or "", "building": cfg.get("building") or "", "postal": cfg.get("postal") or "", "district": cfg.get("district") or ""}}
	items = []
	for it in si.items:
		qty = flt(it.qty)
		price = flt(it.net_rate) + flt(it.discount_amount) if qty else flt(it.net_rate)
		gross = qty * price
		code_meta = frappe.db.get_value("Item", it.item_code, ["einv_code", "einv_code_type"], as_dict=True) or {}
		unit = frappe.db.get_value("UOM", it.uom, "einv_unit_code") or it.uom
		items.append({"description": it.item_name or it.description or it.item_code, "code": code_meta.get("einv_code") or it.item_code, "code_type": code_meta.get("einv_code_type") or "EGS",
			"unit": unit, "qty": qty, "rate": price, "discount_amount": max(0.0, gross - flt(it.net_amount)), "tax_rate": _tax_rate(si, it)})
	lines, totals = common.build_lines(items)
	kind = "credit" if si.is_return else ("debit" if si.get("is_debit_note") else "invoice")
	sign = -1.0 if si.is_return else 1.0  # authorities want positive amounts on a credit note
	if sign < 0:
		for ln in lines:
			ln["qty"] = abs(ln["qty"])
			for k in ("net", "tax", "total", "gross", "discount"):
				ln[k] = abs(ln[k])
		totals = {k: abs(v) for k, v in totals.items()}
	return {"id": si.name, "issue_dt": _utc(si), "kind": kind, "currency": si.currency, "rate": flt(si.conversion_rate) or 1.0, "reference": si.return_against or "",
		"notes": (si.get("remarks") or "")[:200] if kind != "invoice" else "", "seller": seller, "buyer": buyer, "lines": lines, "totals": totals, "payment": {}, "due_date": str(si.due_date or "")}


def sample_invoice(cfg):
	"""A made-up invoice for the Saudi compliance check."""
	import datetime

	lines, totals = common.build_lines([{"description": "Test item", "code": "TEST", "unit": "PCE", "qty": 2, "rate": 100, "discount_amount": 0, "tax_rate": 15}])
	seller = {"name": cfg["company_name"], "tax_id": cfg["tax_id"], "reg_no": cfg.get("reg_no") or "1010010000", "branch": "0",
		"address": {"country": "SA", "governate": cfg.get("governate") or "Riyadh", "city": cfg.get("city") or "Riyadh", "street": cfg.get("street") or "Street", "building": cfg.get("building") or "1234", "postal": cfg.get("postal") or "12345", "district": cfg.get("district") or "Center"}}
	buyer = {"name": "Test Customer", "tax_id": "399999999900003", "type": "B", "address": {"country": "SA", "city": "Riyadh", "street": "Street", "building": "1234", "postal": "12345", "district": "Center"}}
	return {"id": "TEST", "issue_dt": datetime.datetime.utcnow(), "kind": "invoice", "currency": "SAR", "rate": 1.0, "reference": "", "notes": "", "seller": seller, "buyer": buyer, "lines": lines, "totals": totals, "payment": {}}
