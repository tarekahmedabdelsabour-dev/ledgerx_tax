"""Whitelisted calls used by the buttons."""
import frappe
from frappe import _

from ledgerx_tax import adapters, data, jobs

ROLES = ("E-Invoice Manager", "Accounts Manager", "System Manager")


def _check():
	if not set(frappe.get_roles()) & set(ROLES):
		frappe.throw(_("You are not allowed to do this."), frappe.PermissionError)


def _conn(name):
	_check()
	return frappe.get_doc("E-Invoice Connection", name)


@frappe.whitelist(methods=["POST"])
def send_now(invoice):
	_check()
	frappe.has_permission("Sales Invoice", "read", invoice, throw=True)
	name = jobs.queue_invoice(invoice)
	if not name:
		frappe.throw(_("No enabled e-invoice connection for the company of this invoice."))
	return name


@frappe.whitelist(methods=["POST"])
def retry(submission):
	_check()
	status = frappe.db.get_value("E-Invoice Submission", submission, "status", for_update=True)
	if status not in ("Failed", "Pending"):
		frappe.throw(_("Only a failed or pending submission can be sent again. This one is {0}.").format(status))
	frappe.db.set_value("E-Invoice Submission", submission, {"status": "Pending", "attempts": 0})
	frappe.enqueue("ledgerx_tax.jobs.process", sub=submission, queue="short", enqueue_after_commit=True)
	return submission


@frappe.whitelist(methods=["POST"])
def refresh(submission):
	_check()
	return jobs.refresh(submission)


@frappe.whitelist()
def preview(invoice):
	"""What would be sent, without sending it."""
	_check()
	frappe.has_permission("Sales Invoice", "read", invoice, throw=True)
	si = frappe.get_doc("Sales Invoice", invoice)
	conn = data.connection_for(si.company)
	if not conn:
		frappe.throw(_("No enabled e-invoice connection for this company."))
	cfg = data.cfg_of(conn)
	inv = data.build_invoice(si, cfg)
	from lxml import etree

	from ledgerx_tax.engine import egypt, generic, uae, zatca

	if conn.system == "Egypt ETA":
		import json

		doc = egypt.build_document(inv, {"taxpayer_activity_code": cfg.get("activity_code"), "issuer_type": cfg.get("issuer_type"), "tax_type": cfg.get("tax_type"), "tax_subtype": cfg.get("tax_subtype")})
		return json.dumps(doc, indent=1, ensure_ascii=False)
	if conn.system == "Saudi ZATCA":
		kind = "standard" if (cfg.get("invoice_kind") == "Standard" or (cfg.get("invoice_kind") in (None, "Auto") and inv["buyer"].get("tax_id"))) else "simplified"
		root = zatca.build_xml(dict(inv, rate_sar=inv["rate"]), {"invoice_kind": kind}, "00000000-0000-0000-0000-000000000000", (conn.icv or 0) + 1, conn.last_hash or zatca.FIRST_PIH)
		return etree.tostring(root, pretty_print=True, encoding="unicode")
	if conn.system == "UAE PINT-AE":
		inv = dict(inv, seller=dict(inv["seller"], endpoint=inv["seller"]["tax_id"]), buyer=dict(inv["buyer"], endpoint=inv["buyer"].get("tax_id")))
		return etree.tostring(uae.build_xml(inv, {"endpoint_scheme": cfg.get("endpoint_scheme"), "type_flags": cfg.get("type_flags")}), pretty_print=True, encoding="unicode")
	if not cfg.get("body_template"):
		frappe.throw(_("Set the body template on the connection."))
	return generic.render(cfg["body_template"], inv, cfg)


@frappe.whitelist(methods=["POST"])
def test_connection(connection):
	conn = _conn(connection)
	cfg = data.cfg_of(conn)
	try:
		return adapters.get(conn.system).test(cfg, {"http": __import__("ledgerx_tax.adapters.http", fromlist=["call"]).call})
	except Exception as e:
		frappe.throw(str(e))


# ---------------------------------------------------------------- Saudi onboarding
def _log(conn, text):
	frappe.db.set_value("E-Invoice Connection", conn.name, "onboarding_status", ((conn.onboarding_status or "") + "\n" + text).strip()[-2000:])


@frappe.whitelist(methods=["POST"])
def zatca_generate_csr(connection):
	conn = _conn(connection)
	cfg = data.cfg_of(conn)
	key, csr_pem, csr_b64 = adapters.get("Saudi ZATCA").generate_csr(cfg)
	conn.private_key = key
	conn.csr = csr_b64
	conn.save(ignore_permissions=True)
	_log(conn, "Certificate request created.")
	return "Created. Get the one-time code from the ZATCA portal, enter it on the connection, then press Get Compliance Certificate."


@frappe.whitelist(methods=["POST"])
def zatca_compliance_csid(connection):
	conn = _conn(connection)
	if not conn.csr or not conn.zatca_otp:
		frappe.throw(_("Generate the certificate request and enter the one-time code first."))
	cfg = data.cfg_of(conn)
	token, secret, rid = adapters.get("Saudi ZATCA").compliance_csid(cfg, conn.csr, conn.zatca_otp)
	conn.compliance_token, conn.compliance_secret, conn.compliance_request_id, conn.zatca_otp = token, secret, rid, ""
	conn.save(ignore_permissions=True)
	_log(conn, "Compliance certificate received.")
	return "Compliance certificate received. Now press Run Compliance Checks."


@frappe.whitelist(methods=["POST"])
def zatca_run_compliance(connection):
	conn = _conn(connection)
	cfg = data.cfg_of(conn)
	res = adapters.get("Saudi ZATCA").run_compliance(cfg, data.sample_invoice(cfg))
	lines = [f"{n}: {s}" + (f" ({m})" if m else "") for n, s, m in res]
	_log(conn, "Compliance checks:\n" + "\n".join(lines))
	ok = all(s == "Accepted" for _n, s, _m in res)
	return ("All sample invoices passed.\n" if ok else "Some sample invoices failed:\n") + "\n".join(lines)


@frappe.whitelist(methods=["POST"])
def zatca_production_csid(connection):
	conn = _conn(connection)
	cfg = data.cfg_of(conn)
	token, secret = adapters.get("Saudi ZATCA").production_csid(cfg)
	conn.production_token, conn.production_secret = token, secret
	conn.save(ignore_permissions=True)
	_log(conn, "Production certificate received.")
	return "Production certificate received. The connection is ready for real invoices."
