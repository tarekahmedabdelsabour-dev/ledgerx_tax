"""Queue: one E-Invoice Submission per invoice, processed in the background and retried by the scheduler."""
import frappe
from frappe.utils import now_datetime

from ledgerx_tax import adapters, data

MAX_ATTEMPTS = 5


class _Cache:
	def get(self, k):
		return frappe.cache.get_value(k)

	def set(self, k, v, ttl):
		frappe.cache.set_value(k, v, expires_in_sec=ttl)


def ctx():
	return {"cache": _Cache()}


def queue_invoice(si_name):
	"""Create (or reuse) the submission of an invoice and send it in the background."""
	si = frappe.db.get_value("Sales Invoice", si_name, ["company", "docstatus"], as_dict=True)
	if not si or si.docstatus != 1:
		return None
	conn = data.connection_for(si.company)
	if not conn:
		return None
	existing = frappe.db.get_value("E-Invoice Submission", {"sales_invoice": si_name, "status": ["not in", ["Cancelled"]]}, "name")
	if existing:
		return existing
	sub = frappe.get_doc({"doctype": "E-Invoice Submission", "sales_invoice": si_name, "connection": conn.name, "system": conn.system, "company": si.company, "status": "Pending"}).insert(ignore_permissions=True)
	frappe.db.set_value("Sales Invoice", si_name, "einv_status", "Pending", update_modified=False)
	frappe.enqueue("ledgerx_tax.jobs.process", sub=sub.name, queue="short", enqueue_after_commit=True, job_id=f"einv::{sub.name}", deduplicate=True)
	return sub.name


def process(sub):
	"""Send one submission. Never raises: the outcome is written on the submission and on the invoice."""
	doc = frappe.get_doc("E-Invoice Submission", sub)
	if doc.status in ("Accepted", "Cancelled", "Submitted"):
		return
	conn = frappe.get_doc("E-Invoice Connection", doc.connection)
	out = {}
	try:
		cfg = data.cfg_of(conn)
		si = frappe.get_doc("Sales Invoice", doc.sales_invoice)
		inv = data.build_invoice(si, cfg)
		adapter = adapters.get(conn.system)
		context = ctx()
		if conn.system == "Saudi ZATCA":
			row = frappe.db.sql("select icv, last_hash from `tabE-Invoice Connection` where name=%s for update", conn.name, as_dict=True)[0]
			context.update({"icv": row.icv or 0, "pih": row.last_hash})
		out = adapter.send(cfg, inv, context)
		if out.get("advance_chain"):
			frappe.db.set_value("E-Invoice Connection", conn.name, {"icv": out["icv"], "last_hash": out["hash"]}, update_modified=False)
	except Exception as e:
		frappe.db.rollback()
		out = {"status": "Failed", "error": str(e)[:900]}
		frappe.log_error(title=f"E-invoice {sub} failed")
	_save(doc.name, out)


def _save(sub, out):
	doc = frappe.get_doc("E-Invoice Submission", sub)
	doc.attempts = (doc.attempts or 0) + 1
	doc.status = out.get("status") or "Failed"
	doc.submitted_on = now_datetime()
	for k, f in (("uuid", "uuid"), ("reference", "long_id"), ("hash", "document_hash"), ("qr", "qr_code"), ("payload", "payload"), ("response", "response")):
		if out.get(k):
			doc.set(f, out[k])
	doc.error = (out.get("error") or "")[:900]
	doc.save(ignore_permissions=True)
	frappe.db.set_value("Sales Invoice", doc.sales_invoice, {"einv_status": doc.status, "einv_uuid": doc.uuid or "", "einv_qr": doc.qr_code or ""}, update_modified=False)
	frappe.db.commit()


def refresh(sub):
	"""Ask the system for the final state of a submitted document."""
	doc = frappe.get_doc("E-Invoice Submission", sub)
	conn = frappe.get_doc("E-Invoice Connection", doc.connection)
	res = adapters.get(conn.system).check(data.cfg_of(conn), {"uuid": doc.uuid, "status": doc.status, "error": doc.error}, ctx())
	doc.status = res.get("status") or doc.status
	doc.error = (res.get("error") or "")[:900]
	if res.get("response"):
		doc.response = res["response"]
	doc.save(ignore_permissions=True)
	frappe.db.set_value("Sales Invoice", doc.sales_invoice, "einv_status", doc.status, update_modified=False)
	return doc.status


def retry_pending():
	"""Scheduler, every 10 minutes: resend Failed and Pending, re-check Submitted."""
	for r in frappe.get_all("E-Invoice Submission", filters={"status": ["in", ["Failed", "Pending"]], "attempts": ["<", MAX_ATTEMPTS]}, pluck="name", limit=50):
		try:
			doc = frappe.get_doc("E-Invoice Submission", r)
			doc.status = "Pending"
			doc.save(ignore_permissions=True)
			process(r)
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"E-invoice retry {r}")
	for r in frappe.get_all("E-Invoice Submission", filters={"status": "Submitted"}, pluck="name", limit=100):
		try:
			refresh(r)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"E-invoice check {r}")
