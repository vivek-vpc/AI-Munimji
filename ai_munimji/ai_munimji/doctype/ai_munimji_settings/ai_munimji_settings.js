// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Munimji Settings", {
	refresh(frm) {
		show_whether_it_is_on(frm);
	},
	enabled(frm) {
		show_whether_it_is_on(frm);
	},
});

// The stock monitor is off until someone has looked at the thresholds. While it is off, say so at the top of the page.
function show_whether_it_is_on(frm) {
	if (frm.doc.enabled) {
		frm.set_intro("");
	} else {
		frm.set_intro(
			__(
				"Stock monitoring is off. Review the thresholds below, then switch on Watch stock."
			),
			"yellow"
		);
	}
}
