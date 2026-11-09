// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Munimji Settings", {
	refresh(frm) {
		show_the_notes(frm);
	},
	enabled(frm) {
		show_the_notes(frm);
	},
});

// The notes at the top of the page. They share one place (Frappe's form intro is the dashboard headline), so they are written together and neither can wipe the other:
// - in red, while the database has innodb_snapshot_isolation ON (the server sends the sentence only then: dbcheck.py);
// - until someone has looked at the thresholds and switched Watch stock on, that stock monitoring is off.
function show_the_notes(frm) {
	const warning = (frm.doc.__onload || {}).snapshot_isolation_warning;
	const notes = [];
	if (warning) {
		notes.push(frappe.utils.escape_html(warning));
	}
	if (!frm.doc.enabled) {
		notes.push(
			frappe.utils.escape_html(
				__(
					"Stock monitoring is off. Review the thresholds below, then switch on Watch stock."
				)
			)
		);
	}
	frm.set_intro(notes.join("<br><br>"), warning ? "red" : "yellow");
}
