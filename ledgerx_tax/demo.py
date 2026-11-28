"""Demo data for the Tax app: an e-invoice connection per country (Egypt ETA, Saudi ZATCA, UAE PINT-AE) and a few submitted Sales Invoices
(business and consumer buyers, with VAT) for the three companies.

    bench --site mysite.localhost execute ledgerx_tax.demo.run

Run ledgerx.demo.foundation first. Take a backup first. Idempotent: every record is looked up by its natural key before it is created.
Every step commits on its own and reports its result; failures are logged in Error Log under titles starting 'Demo tax'.

SAFE BY DESIGN: nothing here can reach a tax authority.
- Connections are created DISABLED (enabled = 0), in the Test environment, with NO passwords, tokens, keys, OTP, API or signer URLs.
  The tax numbers and addresses are sample values for the demo only. Enter the real ones, then onboard, before enabling.
- The app sends on Sales Invoice submit only through an enabled connection (data.connection_for), so nothing is queued; the demo invoices are
  also flagged 'Do Not Send to the Tax Authority' as a second lock, and no E-Invoice Submission is created (the scheduler retries Pending ones).
- The last step checks all of this and fails loudly if any demo connection is enabled or any submission exists for a demo invoice.
Existing connections and customers are never changed.
"""
import frappe
from frappe.utils import add_days, nowdate

from ledgerx.shared import run_each

PREFIX = "Demo tax invoice"

# key: company, connection name, system, VAT %, currency rate vs EGP list prices, customers [(name, type, tax id)], connection fields
COUNTRIES = {
	"eg": dict(company="LedgerX Egypt", territory="Egypt", vat=14, scale=1.0,
		customers=[("Al Ahram Office Supplies", "Business", "EG-212345678"), ("Karim Samir Fouad", "Person", None)],
		conn=dict(connection_name="ETA Egypt (demo, disabled)", system="Egypt ETA", environment="Test", tax_id="212345678", reg_no="45872", branch_id="0", country="EG",
			governate="Cairo", city="Nasr City", street="Makram Ebeid Street", building="14", postal="11765", activity_code="4651", issuer_type="B",
			tax_type="T1", tax_subtype="V009")),
	"sa": dict(company="LedgerX Saudi", territory="Saudi Arabia", vat=15, scale=1 / 13.0,
		customers=[("Al Madar Trading Est", "Business", "300112233400003"), ("Khalid Nasser Al-Anazi", "Person", None)],
		conn=dict(connection_name="ZATCA Saudi (demo, disabled)", system="Saudi ZATCA", environment="Test", tax_id="300455123700003", reg_no="1010456789", branch_id="0",
			country="SA", city="Riyadh", street="Olaya Street", building="7421", postal="12214", district="Al Olaya", invoice_kind="Auto",
			egs_serial="LEDGERX-EGS-0001", org_unit="Riyadh Branch", common_name="LedgerX Saudi EGS 1", industry="Trading", full_address="Olaya Street, Riyadh 12214, Saudi Arabia")),
	"ae": dict(company="LedgerX UAE", territory="United Arab Emirates", vat=5, scale=1 / 13.3,
		customers=[("Gulf Pearl Hospitality LLC", "Business", "100345678900003"), ("Shamma Rashid Al-Ameri", "Person", None)],
		conn=dict(connection_name="PINT-AE UAE (demo, disabled)", system="UAE PINT-AE", environment="Test", tax_id="100345678900003", reg_no="1234567", branch_id="0", country="AE",
			city="Dubai", street="Sheikh Zayed Road", building="Tower 3", postal="00000", endpoint_scheme="0235")),
}
# invoice: days ago, customer index, [(item, qty, discount %)]
INVOICES = [
	(14, 0, [("LX-LAPTOP", 3, 0), ("LX-PRINTER", 1, 0)]),
	(9, 1, [("LX-CHAIR", 2, 0), ("LX-PAPER", 6, 5)]),
	(4, 0, [("LX-DESK", 4, 0), ("LX-CHAIR", 4, 0), ("LX-INK", 5, 0)]),
]
RATES = {"LX-LAPTOP": 18000, "LX-PRINTER": 6500, "LX-DESK": 3200, "LX-CHAIR": 1800, "LX-PAPER": 250, "LX-INK": 420}


def _say(msg):
	print(msg)


def _insert(doc):
	return frappe.get_doc(doc).insert(ignore_permissions=True)


def _company(key):
	c = COUNTRIES[key]["company"]
	if not frappe.db.exists("Company", c):
		frappe.throw(f"Company {c} is missing. Run ledgerx.demo.foundation first.")
	return c


def _group():
	return "Commercial" if frappe.db.exists("Customer Group", "Commercial") else frappe.db.get_value("Customer Group", {"is_group": 0}, "name")


def _territory(name):
	return name if frappe.db.exists("Territory", name) else frappe.db.get_value("Territory", {"is_group": 0}, "name")


# ------------------------------------------------------------------ masters
def _customers(key):
	c = COUNTRIES[key]
	for name, kind, tax in c["customers"]:
		if frappe.db.exists("Customer", name):
			continue
		doc = {"doctype": "Customer", "customer_name": name, "customer_type": "Company" if kind == "Business" else "Individual", "customer_group": _group(),
			"territory": _territory(c["territory"]), "einv_buyer_type": kind}
		if tax:
			doc["tax_id"] = tax
			doc["einv_reg_no"] = "CR-" + tax[-6:]
		_insert(doc)


def _tax_account(company):
	acct = frappe.db.get_value("Account", {"company": company, "account_type": "Tax", "is_group": 0, "root_type": "Liability"}, "name")
	if acct:
		return acct
	abbr = frappe.db.get_value("Company", company, "abbr")
	parent = f"Duties and Taxes - {abbr}"
	if not frappe.db.exists("Account", parent):
		return None
	if not frappe.db.exists("Account", f"Output VAT - {abbr}"):
		_insert({"doctype": "Account", "account_name": "Output VAT", "parent_account": parent, "company": company, "account_type": "Tax", "root_type": "Liability", "is_group": 0})
	return f"Output VAT - {abbr}"


def _template(key):
	"""A VAT template for the company, only when a tax account exists or can be made. Without it the invoices are made without tax."""
	c = COUNTRIES[key]
	company = _company(key)
	title = f"Demo VAT {c['vat']}%"
	if frappe.db.exists("Sales Taxes and Charges Template", {"company": company, "title": title}):
		return
	acct = _tax_account(company)
	if not acct:
		frappe.throw(f"No tax account for {company}; invoices will be made without VAT")
	_insert({"doctype": "Sales Taxes and Charges Template", "title": title, "company": company, "taxes": [{"charge_type": "On Net Total", "account_head": acct,
		"description": f"VAT {c['vat']}%", "rate": c["vat"]}]})


def _connection(key):
	"""Disabled, Test environment, no secrets. An existing connection of the company (enabled or not) is left alone."""
	c = COUNTRIES[key]
	company = _company(key)
	conn = dict(c["conn"])
	if frappe.db.exists("E-Invoice Connection", conn["connection_name"]) or frappe.db.exists("E-Invoice Connection", {"company": company}):
		return
	conn.update({"doctype": "E-Invoice Connection", "company": company, "enabled": 0, "auto_submit": 0})
	_insert(conn)


# ------------------------------------------------------------------ transactions
def _invoice(spec):
	key, i = spec.split(":")
	c = COUNTRIES[key]
	company = _company(key)
	days, cust_i, lines = INVOICES[int(i)]
	customer = c["customers"][cust_i][0]
	remark = f"{PREFIX} {key.upper()}-{int(i) + 1}"
	if frappe.db.exists("Sales Invoice", {"remarks": remark, "company": company, "docstatus": 1}):
		return
	for code, _q, _d in lines:
		if not frappe.db.exists("Item", code):
			frappe.throw(f"Item {code} is missing. Run ledgerx.demo.foundation first.")
	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.posting_date = add_days(nowdate(), -days)
	si.set_posting_time = 1
	si.due_date = add_days(nowdate(), 30 - days)
	si.remarks = remark
	si.einv_skip = 1  # second lock: never sent, even if a connection is enabled later
	for code, qty, disc in lines:
		si.append("items", {"item_code": code, "qty": qty, "rate": round(RATES[code] * c["scale"], 2), "discount_percentage": disc})
	tmpl = frappe.db.get_value("Sales Taxes and Charges Template", {"company": company, "title": f"Demo VAT {c['vat']}%"}, "name")
	if tmpl:
		si.taxes_and_charges = tmpl
		si.set_taxes()
	si.insert(ignore_permissions=True)
	si.submit()


def _safety(_x):
	"""Fails loudly when anything could reach a tax authority."""
	names = [c["conn"]["connection_name"] for c in COUNTRIES.values()]
	on = frappe.get_all("E-Invoice Connection", filters={"connection_name": ["in", names], "enabled": 1}, pluck="name")
	if on:
		frappe.throw(f"Demo connection is ENABLED: {on}. Disable it.")
	for n in names:
		if not frappe.db.exists("E-Invoice Connection", n):
			continue
		d = frappe.get_doc("E-Invoice Connection", n)
		for f in ("auth_secret", "signer_token", "private_key", "compliance_token", "compliance_secret", "production_token", "production_secret"):
			if d.get_password(f, raise_exception=False):
				frappe.throw(f"Demo connection {n} holds a secret in {f}. Clear it.")
	demo = frappe.get_all("Sales Invoice", filters={"remarks": ["like", f"{PREFIX}%"], "docstatus": 1}, pluck="name")
	if demo and frappe.db.exists("E-Invoice Submission", {"sales_invoice": ["in", demo]}):
		frappe.throw("A demo invoice has an E-Invoice Submission. Delete it before the scheduler retries it.")


STEPS = [
	("Customers", _customers, list(COUNTRIES)),
	("VAT templates", _template, list(COUNTRIES)),
	("E-invoice connections (disabled)", _connection, list(COUNTRIES)),
	("Sales invoices", _invoice, [f"{k}:{i}" for k in COUNTRIES for i in range(len(INVOICES))]),
	("Safety check", _safety, [1]),
]


def run():
	_say("Tax demo data")
	failed_any = False
	for label, fn, items in STEPS:
		done, failed = run_each(items, fn, f"Demo tax: {label}")
		failed_any = failed_any or bool(failed)
		_say(f"  {label}: {len(done)} ok, {len(failed)} failed")
	if failed_any:
		_say("Some steps failed. Open Error Log (titles start with 'Demo tax') and send me the errors.")
	else:
		_say("Done. The connections are disabled and hold no credentials: enter the real tax data and onboard before enabling any of them.")
