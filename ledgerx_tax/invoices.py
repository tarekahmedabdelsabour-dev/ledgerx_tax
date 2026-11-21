"""Sales Invoice events."""
import frappe
from frappe import _

from ledgerx_tax import adapters, data, jobs


def on_submit(doc, method=None):
	if doc.get("einv_skip"):
		return
	conn = data.connection_for(doc.company)
	if conn and conn.auto_submit:
		try:
			jobs.queue_invoice(doc.name)
		except Exception:
			frappe.log_error(title=f"E-invoice queue {doc.name}")


def before_cancel(doc, method=None):
	sub = frappe.db.get_value("E-Invoice Submission", {"sales_invoice": doc.name, "status": ["in", ["Accepted", "Submitted"]]}, ["name", "connection", "uuid", "system"], as_dict=True)
	if not sub:
		return
	if sub.system == "Egypt ETA":
		conn = frappe.get_doc("E-Invoice Connection", sub.connection)
		try:
			adapters.get(sub.system).cancel(data.cfg_of(conn), {"uuid": sub.uuid}, doc.get("cancel_reason") or "Cancelled in the books", jobs.ctx())
		except Exception as e:
			frappe.throw(_("The tax authority did not accept the cancellation, so the invoice was not cancelled: {0}").format(e))
		frappe.db.set_value("E-Invoice Submission", sub.name, "status", "Cancelled")
		frappe.db.set_value("Sales Invoice", doc.name, "einv_status", "Cancelled", update_modified=False)
	elif sub.system in ("Saudi ZATCA", "UAE PINT-AE"):
		frappe.throw(_("This invoice was sent to the tax authority and cannot be cancelled. Issue a credit note instead."))
