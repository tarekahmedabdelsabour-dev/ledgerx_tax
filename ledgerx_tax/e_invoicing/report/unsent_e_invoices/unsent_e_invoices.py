import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	cols = [
		{"label": _("Invoice"), "fieldname": "name", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 180},
		{"label": _("Total"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 120},
		{"label": _("E-Invoice Status"), "fieldname": "einv_status", "fieldtype": "Data", "width": 130},
		{"label": _("Last Error"), "fieldname": "error", "fieldtype": "Data", "width": 360},
	]
	conds, vals = ["si.docstatus = 1", "ifnull(si.einv_skip, 0) = 0", "ifnull(si.einv_status, '') not in ('Accepted', 'Submitted', 'Cancelled')",
		"exists (select 1 from `tabE-Invoice Connection` c where c.company = si.company and c.enabled = 1)"], {}
	if filters.company:
		conds.append("si.company = %(company)s")
		vals["company"] = filters.company
	if filters.from_date:
		conds.append("si.posting_date >= %(from_date)s")
		vals["from_date"] = filters.from_date
	if filters.to_date:
		conds.append("si.posting_date <= %(to_date)s")
		vals["to_date"] = filters.to_date
	rows = frappe.db.sql(
		f"""select si.name, si.posting_date, si.customer, si.grand_total, si.einv_status,
		(select s.error from `tabE-Invoice Submission` s where s.sales_invoice = si.name order by s.creation desc limit 1) as error
		from `tabSales Invoice` si where {' and '.join(conds)} order by si.posting_date desc, si.name desc limit 1000""", vals, as_dict=True)
	return cols, rows
