app_name = "ledgerx_tax"
app_title = "E-Invoicing"
app_publisher = "LedgerX"
app_description = "Electronic invoicing and tax authority connections: Egypt ETA, Saudi ZATCA, UAE Peppol, and any other system through a configurable connector"
app_email = "hello@ledgerx.local"
app_license = "mit"

required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": "ledgerx_tax",
		"logo": "/assets/ledgerx_tax/images/einvoicing.svg",
		"title": "E-Invoicing",
		"route": "/desk/e-invoicing",
		"has_permission": "ledgerx_tax.install.check_app_permission",
	}
]

doc_events = {
	"Sales Invoice": {"on_submit": "ledgerx_tax.invoices.on_submit", "before_cancel": "ledgerx_tax.invoices.before_cancel"},
}

scheduler_events = {
	"cron": {
		"*/10 * * * *": ["ledgerx_tax.tasks.retry"],
	},
}

from ledgerx_tax import __version__ as _v  # noqa: E402

app_include_js = [f"/assets/ledgerx_tax/js/einv_forms.js?v={_v}"]

after_install = "ledgerx_tax.install.after_install"
after_migrate = "ledgerx_tax.install.after_migrate"
