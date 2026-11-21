"""Builds the DocType JSON files of ledgerx_tax. Run from the repo root: python3 tools/gen_doctypes.py (controller .py files are never overwritten)."""
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "ledgerx_tax", "e_invoicing", "doctype")
TS = "2026-11-22 08:00:00.000000"
MODULE = "E-Invoicing"


def f(name, ftype, label=None, **kw):
	d = {"fieldname": name, "fieldtype": ftype}
	if ftype not in ("Section Break", "Column Break", "Tab Break"):
		d["label"] = label or name.replace("_", " ").title()
	elif label:
		d["label"] = label
	d.update(kw)
	return d


def sec(name, label=None, **kw):
	return f(name, "Section Break", label, **kw)


def col(name):
	return f(name, "Column Break")


MGR = "E-Invoice Manager"


def perms(*rows):
	out = []
	for role, mode in rows:
		p = {"role": role, "read": 1, "report": 1, "print": 1, "export": 1}
		if mode in ("rw", "all"):
			p["write"] = 1
		if mode == "all":
			p.update({"create": 1, "delete": 1})
		out.append(p)
	out.append({"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "print": 1, "export": 1})
	return out


EG, SA, AE, CU = "Egypt ETA", "Saudi ZATCA", "UAE PINT-AE", "Custom API"
SYSTEMS = "\n".join([EG, SA, AE, CU])
DT = {}


def dep(system_list):
	return "eval:" + " || ".join(f"doc.system=='{s}'" for s in system_list)


DT["E-Invoice Connection"] = {"fields": [
	f("connection_name", "Data", "Connection Name", reqd=1, unique=1, in_list_view=1),
	f("enabled", "Check", "Enabled", default=1, in_list_view=1),
	f("company", "Link", "Company", options="Company", reqd=1, in_list_view=1, in_standard_filter=1),
	col("cb0"),
	f("system", "Select", "System", options=SYSTEMS, reqd=1, in_list_view=1, in_standard_filter=1),
	f("environment", "Select", "Environment", options="Test\nSimulation\nProduction", default="Test", reqd=1, in_list_view=1, description="Test: the authority's pre-production or developer sandbox. Simulation: Saudi simulation portal. Production: real invoices."),
	f("auto_submit", "Check", "Send Automatically When the Invoice Is Submitted", default=1),
	sec("sb_seller", "Seller (this company on the tax system)"),
	f("tax_id", "Data", "Tax Registration / VAT / TIN", reqd=1),
	f("reg_no", "Data", "Commercial Register / Trade License No."),
	f("branch_id", "Data", "Branch Code", default="0"),
	col("cb1"),
	f("country", "Data", "Country Code", default="EG", description="Two letters, e.g. EG, SA, AE."),
	f("governate", "Data", "Governorate / Region"),
	f("city", "Data", "City / District"),
	f("street", "Data", "Street"),
	col("cb2"),
	f("building", "Data", "Building No."),
	f("postal", "Data", "Postal Code"),
	f("district", "Data", "Neighbourhood"),
	sec("sb_api", "Connection"),
	f("api_url", "Data", "API Address", description="Leave empty to use the authority's standard address for the environment."),
	f("identity_url", "Data", "Login (Identity) Address", depends_on=dep([EG, CU])),
	col("cb3"),
	f("auth_type", "Select", "Sign-in Method", options="None\nBearer Token\nBasic\nCustom Header\nClient Credentials", default="None", depends_on=dep([AE, CU])),
	f("auth_user", "Data", "Client ID / User", depends_on=dep([EG, AE, CU])),
	f("auth_secret", "Password", "Client Secret / Token / Password", depends_on=dep([EG, AE, CU])),
	f("auth_header", "Data", "Header Name", depends_on=dep([AE, CU]), description="For Custom Header, e.g. X-Api-Key."),
	# ---------------- Egypt
	sec("sb_eg", "Egypt: Tax Authority", depends_on=dep([EG])),
	f("activity_code", "Data", "Taxpayer Activity Code"),
	f("issuer_type", "Select", "Issuer Type", options="B\nP\nF", default="B", description="B business, P person, F foreigner."),
	f("on_behalf_of", "Data", "Registration No. of the Taxpayer (only when an intermediary)", description="Sent as the onbehalfof header."),
	col("cb4"),
	f("tax_type", "Data", "Tax Type Code", default="T1", description="T1 = VAT."),
	f("tax_subtype", "Data", "Tax Subtype Code", default="V009"),
	f("signer", "Select", "Document Signing", options="External Signing Service\nNone (test only)", default="External Signing Service", description="The authority requires a digital seal (CAdES-BES) on every invoice."),
	f("signer_url", "Data", "Signing Service Address", description="Receives {canonical, sha256} and returns {signature: base64}. See the install guide."),
	f("signer_token", "Password", "Signing Service Key"),
	# ---------------- Saudi
	sec("sb_sa", "Saudi Arabia: ZATCA", depends_on=dep([SA])),
	f("invoice_kind", "Select", "Invoice Kind", options="Auto\nStandard\nSimplified", default="Auto", description="Auto: standard (cleared) when the customer has a tax number, otherwise simplified (reported)."),
	f("egs_serial", "Data", "Device Serial (EGS)"),
	f("org_unit", "Data", "Organization Unit / Branch Name"),
	f("common_name", "Data", "Device Name (Common Name)"),
	col("cb5"),
	f("industry", "Data", "Business Category"),
	f("full_address", "Data", "Registered Address (one line)"),
	f("zero_reason_code", "Data", "Zero-rate Reason Code", default="VATEX-SA-OOS"),
	f("zero_reason", "Data", "Zero-rate Reason", default="Out of scope"),
	sec("sb_sa2", "Saudi Arabia: Certificates", depends_on=dep([SA])),
	f("zatca_otp", "Data", "One-time Code from the Portal (OTP)", description="Valid for a short time. Press Get Compliance Certificate right after entering it."),
	f("csr", "Long Text", "Certificate Request (CSR)", read_only=1),
	f("private_key", "Password", "Private Key", read_only=1),
	col("cb6"),
	f("compliance_token", "Password", "Compliance Certificate", read_only=1),
	f("compliance_secret", "Password", "Compliance Secret", read_only=1),
	f("compliance_request_id", "Data", "Compliance Request ID", read_only=1),
	f("production_token", "Password", "Production Certificate", read_only=1),
	f("production_secret", "Password", "Production Secret", read_only=1),
	sec("sb_sa3", "Saudi Arabia: Invoice Chain", depends_on=dep([SA])),
	f("icv", "Int", "Invoice Counter", read_only=1, default=0),
	f("last_hash", "Data", "Hash of the Last Invoice", read_only=1),
	f("onboarding_status", "Small Text", "Onboarding Log", read_only=1),
	# ---------------- UAE + custom
	sec("sb_ae", "UAE: Service Provider", depends_on=dep([AE])),
	f("endpoint_scheme", "Data", "Peppol Scheme ID", default="0235", description="0235 = UAE tax number."),
	f("type_flags", "Data", "Invoice Type Flags", default="00000000"),
	f("payload_format", "Select", "Body Sent to the Provider", options="XML\nJSON with XML inside", default="XML"),
	sec("sb_cu", "Request Template (Custom API, and optional for UAE)", depends_on=dep([AE, CU])),
	f("http_method", "Select", "Method", options="POST\nPUT", default="POST"),
	f("content_type", "Data", "Content-Type", default="application/json"),
	f("headers_json", "Code", "Extra Headers (JSON)", options="JSON"),
	f("body_template", "Code", "Body Template (Jinja)", options="Jinja", description="Variables: inv (the invoice), cfg. For UAE also xml and xml_b64. Use {{ inv | tojson }} to send the whole invoice."),
	col("cb7"),
	f("ok_path", "Data", "Success Field in the Answer", description="Dotted path, e.g. status or data.accepted. Empty = any 2xx is success."),
	f("ok_value", "Data", "Success Value", default="true"),
	f("uuid_path", "Data", "Reference Field in the Answer"),
	f("error_path", "Data", "Error Field in the Answer"),
], "autoname": "field:connection_name", "icon": "fa fa-plug", "title_field": "connection_name", "perms": perms((MGR, "all"), ("Accounts Manager", "r"))}

DT["E-Invoice Submission"] = {"fields": [
	f("sales_invoice", "Link", "Sales Invoice", options="Sales Invoice", reqd=1, in_list_view=1, in_standard_filter=1, search_index=1),
	f("connection", "Link", "Connection", options="E-Invoice Connection", reqd=1, in_standard_filter=1),
	f("system", "Data", "System", read_only=1, in_list_view=1, in_standard_filter=1),
	col("cb1"),
	f("status", "Select", "Status", options="Pending\nSubmitted\nAccepted\nRejected\nFailed\nCancelled", default="Pending", in_list_view=1, in_standard_filter=1, read_only=1),
	f("company", "Link", "Company", options="Company", read_only=1),
	f("attempts", "Int", "Attempts", read_only=1, default=0),
	f("submitted_on", "Datetime", "Last Attempt", read_only=1),
	sec("sb_ref", "Tax Authority Reference"),
	f("uuid", "Data", "Document ID (UUID)", read_only=1, in_list_view=1),
	f("long_id", "Data", "Long ID / Reference", read_only=1),
	f("document_hash", "Data", "Document Hash", read_only=1),
	col("cb2"),
	f("qr_code", "Long Text", "QR Code Data", read_only=1),
	f("error", "Small Text", "Error", read_only=1),
	sec("sb_data", "What Was Sent", collapsible=1),
	f("payload", "Code", "Request", read_only=1),
	f("response", "Code", "Answer", read_only=1),
], "autoname": "format:EINV-.YYYY.-.#####", "icon": "fa fa-paper-plane", "title_field": "sales_invoice", "perms": perms((MGR, "rw"), ("Accounts Manager", "r"), ("Accounts User", "r"))}


def build():
	os.makedirs(ROOT, exist_ok=True)
	for name, d in DT.items():
		fields = d["fields"]
		out = {
			"actions": [], "creation": TS, "doctype": "DocType", "engine": "InnoDB", "field_order": [x["fieldname"] for x in fields],
			"fields": fields, "links": [], "modified": TS, "modified_by": "Administrator", "module": MODULE, "name": name, "owner": "Administrator",
			"sort_field": "creation", "sort_order": "DESC", "states": [], "permissions": d["perms"], "autoname": d["autoname"],
			"icon": d["icon"], "title_field": d["title_field"], "track_changes": 1, "allow_rename": 0,
		}
		slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
		folder = os.path.join(ROOT, slug)
		os.makedirs(folder, exist_ok=True)
		open(os.path.join(folder, "__init__.py"), "a").close()
		with open(os.path.join(folder, slug + ".json"), "w", encoding="utf-8") as fh:
			json.dump(out, fh, indent=1, ensure_ascii=False)
			fh.write("\n")
		py = os.path.join(folder, slug + ".py")
		if not os.path.exists(py):
			cls = "".join(w.capitalize() for w in re.split(r"[^A-Za-z0-9]+", name))
			open(py, "w").write(f"from frappe.model.document import Document\n\n\nclass {cls}(Document):\n\tpass\n")


if __name__ == "__main__":
	build()
	print(len(DT), "doctypes")
