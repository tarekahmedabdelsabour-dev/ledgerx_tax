"""Install and migrate steps: idempotent, and a failing step never aborts a migrate."""
import os

import frappe

MODULE, FOLDER = "E-Invoicing", "e_invoicing"
ROLES = ["E-Invoice Manager"]
FIELDS = [
	("Sales Invoice", "einv_section", {"label": "E-Invoicing", "fieldtype": "Section Break", "insert_after": "more_info", "collapsible": 1}),
	("Sales Invoice", "einv_status", {"label": "E-Invoice Status", "fieldtype": "Data", "insert_after": "einv_section", "read_only": 1, "in_standard_filter": 1, "no_copy": 1}),
	("Sales Invoice", "einv_uuid", {"label": "E-Invoice ID", "fieldtype": "Data", "insert_after": "einv_status", "read_only": 1, "no_copy": 1}),
	("Sales Invoice", "einv_col", {"fieldtype": "Column Break", "insert_after": "einv_uuid"}),
	("Sales Invoice", "einv_skip", {"label": "Do Not Send to the Tax Authority", "fieldtype": "Check", "insert_after": "einv_col", "no_copy": 1}),
	("Sales Invoice", "einv_qr", {"label": "E-Invoice QR Data", "fieldtype": "Long Text", "insert_after": "einv_skip", "read_only": 1, "hidden": 1, "no_copy": 1}),
	("Customer", "einv_buyer_type", {"label": "E-Invoice Buyer Type", "fieldtype": "Select", "options": "\nBusiness\nPerson\nForeigner", "insert_after": "tax_id", "description": "Blank: Business when a tax number exists, otherwise Person."}),
	("Customer", "einv_reg_no", {"label": "Commercial Register / National ID", "fieldtype": "Data", "insert_after": "einv_buyer_type"}),
	("Item", "einv_code_type", {"label": "E-Invoice Code Type", "fieldtype": "Select", "options": "EGS\nGS1", "default": "EGS", "insert_after": "item_name", "description": "Egypt: EGS (registered with the tax authority) or GS1."}),
	("Item", "einv_code", {"label": "E-Invoice Item Code", "fieldtype": "Data", "insert_after": "einv_code_type", "description": "Blank: the item code is used."}),
	("UOM", "einv_unit_code", {"label": "E-Invoice Unit Code", "fieldtype": "Data", "insert_after": "uom_name", "description": "Egypt: unit code of the authority (e.g. EA). Saudi / UAE: UN/ECE code (e.g. PCE, C62, KGM)."}),
]


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True
	return bool(set(frappe.get_roles()) & set(ROLES + ["System Manager", "Accounts Manager"]))


def after_install():
	_all()


def after_migrate():
	_all()


def _all():
	for fn in (ensure_module, ensure_roles, ensure_custom_fields, refresh_workspace):
		try:
			fn()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"ledgerx_tax install step failed: {fn.__name__}")
	frappe.clear_cache()


def ensure_module():
	if not frappe.db.exists("Module Def", MODULE):
		frappe.get_doc({"doctype": "Module Def", "module_name": MODULE, "app_name": "ledgerx_tax"}).insert(ignore_permissions=True)


def ensure_roles():
	for r in ROLES:
		if not frappe.db.exists("Role", r):
			frappe.get_doc({"doctype": "Role", "role_name": r, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_custom_fields():
	for dt, name, spec in FIELDS:
		if frappe.db.exists("DocType", dt) and not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": name}):
			frappe.get_doc({"doctype": "Custom Field", "dt": dt, "fieldname": name, **spec}).insert(ignore_permissions=True)


def refresh_workspace():
	base = os.path.join(frappe.get_app_path("ledgerx_tax"), FOLDER)
	for dt in ("number_card", "dashboard_chart"):
		folder = os.path.join(base, dt)
		for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
			if os.path.isdir(os.path.join(folder, name)):
				frappe.reload_doc(FOLDER, dt, name, force=True)
	frappe.reload_doc(FOLDER, "workspace", "e_invoicing", force=True)
