import frappe

from ledgerx_tax import jobs


def retry():
	try:
		jobs.retry_pending()
	except Exception:
		frappe.log_error(title="E-invoice retry run failed")
