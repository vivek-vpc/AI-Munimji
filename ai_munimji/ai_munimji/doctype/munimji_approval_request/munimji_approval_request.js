// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

frappe.ui.form.on("Munimji Approval Request", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Pending") {
			return;
		}
		// The server decides who may press it (the "approve" permission, which also needs the right to create a Purchase Order).
		frm.add_custom_button(__("Create Purchase Order"), () => {
			frappe.confirm(
				__("Create a draft Purchase Order for {0} x {1}? Nothing is submitted.", [frm.doc.qty, frm.doc.item_code]),
				() => {
					frm.call({
						doc: frm.doc,
						method: "create_draft_purchase_order",
						freeze: true,
						freeze_message: __("Creating the draft..."),
					}).then((r) => {
						frappe.show_alert({ message: __("Draft {0} created", [r.message]), indicator: "green" });
						frm.reload_doc();
					});
				}
			);
		}).addClass("btn-primary");
	},
});
