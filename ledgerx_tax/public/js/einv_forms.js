(function () {
	const call = (method, args, done) => frappe.call({ method: "ledgerx_tax.api." + method, args, freeze: true, callback: (r) => done && done(r.message) });
	const show = (title, text) => frappe.msgprint({ title: __(title), message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(text || "")}</pre>`, wide: true });

	frappe.ui.form.on("Sales Invoice", {
		refresh(frm) {
			if (frm.doc.docstatus !== 1) return;
			const st = frm.doc.einv_status;
			if (st) frm.dashboard.add_indicator(__("E-Invoice: {0}", [__(st)]), { Accepted: "green", Submitted: "blue", Pending: "orange", Rejected: "red", Failed: "red", Cancelled: "gray" }[st] || "gray");
			if (!["Accepted", "Submitted", "Cancelled"].includes(st)) {
				frm.add_custom_button(__("Send to the Tax Authority"), () => call("send_now", { invoice: frm.doc.name }, () => { frappe.show_alert({ message: __("Queued"), indicator: "green" }); frm.reload_doc(); }), __("E-Invoicing"));
			}
			frm.add_custom_button(__("Preview E-Invoice"), () => call("preview", { invoice: frm.doc.name }, (t) => show("E-Invoice", t)), __("E-Invoicing"));
		},
	});

	frappe.ui.form.on("E-Invoice Submission", {
		refresh(frm) {
			if (frm.is_new()) return;
			if (["Failed", "Rejected", "Pending"].includes(frm.doc.status)) frm.add_custom_button(__("Send Again"), () => call("retry", { submission: frm.doc.name }, () => frm.reload_doc()));
			if (["Submitted"].includes(frm.doc.status)) frm.add_custom_button(__("Check Status"), () => call("refresh", { submission: frm.doc.name }, () => frm.reload_doc()));
		},
	});

	frappe.ui.form.on("E-Invoice Connection", {
		refresh(frm) {
			if (frm.is_new()) return;
			frm.add_custom_button(__("Test Connection"), () => call("test_connection", { connection: frm.doc.name }, (t) => show("Test", t)), __("Actions"));
			if (frm.doc.system === "Saudi ZATCA") {
				const step = (m, label) => frm.add_custom_button(__(label), () => frm.save().then(() => call(m, { connection: frm.doc.name }, (t) => { show(label, t); frm.reload_doc(); })), __("Saudi Onboarding"));
				step("zatca_generate_csr", "1. Generate Certificate Request");
				step("zatca_compliance_csid", "2. Get Compliance Certificate");
				step("zatca_run_compliance", "3. Run Compliance Checks");
				step("zatca_production_csid", "4. Get Production Certificate");
			}
		},
	});
})();
