// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

// A thin Desk client of the engine, until Phase 5 builds the approval form: one button for a purchase request. It carries the answer in as the signed-in person; what the answer does
// (a draft Purchase Order in that person's name, a second press refused) is the engine's, and who may press it is the server's.
frappe.ui.form.on("Munimji Approval Request", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "pending" || frm.doc.kind !== "procurement.po") {
			return;
		}
		frm.add_custom_button(__("Create Purchase Order"), () => {
			frappe.confirm(
				__("Create a draft Purchase Order for {0} x {1}? Nothing is submitted.", [
					frm.doc.qty,
					frm.doc.item_code,
				]),
				() => {
					frappe
						.call({
							method: "ai_munimji.api.answer",
							args: { approval_id: frm.doc.name, action: "approve" },
							freeze: true,
							freeze_message: __("Creating the draft..."),
						})
						.then((r) => {
							const answer = r.message || {};
							frappe.show_alert({
								message: answer.message || __("No answer"),
								indicator: answer.ok ? "green" : "red",
							});
							frm.reload_doc();
						});
				}
			);
		}).addClass("btn-primary");
	},
});
