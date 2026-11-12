// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

// A person's Telegram link has nothing to type (the bot makes it). What they can do here is stop being sent requests, or disconnect. Disconnecting does not touch the chat itself.
frappe.ui.form.on("Munimji Telegram Link", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Disconnect"), () => {
			frappe.confirm(
				frappe.utils.escape_html(
					__(
						"Requests will no longer be sent to this Telegram chat. Connect again whenever you want."
					)
				),
				() =>
					frappe
						.call({
							method: "ai_munimji.telegram.api.disconnect",
							args: { user: frm.doc.user },
							freeze: true,
						})
						.then((r) => {
							frappe.show_alert(
								{
									message: frappe.utils.escape_html(
										(r.message || {}).message || ""
									),
									indicator: "green",
								},
								8
							);
							frappe.set_route("List", "Munimji Telegram Link");
						})
			);
		});
	},
});
