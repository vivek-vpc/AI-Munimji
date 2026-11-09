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
// - until someone has looked at the thresholds and switched Watch stock on, that stock monitoring is off;
// - after a stock check that could not analyse some items (the server sends the count only then: last_run.py).
function show_the_notes(frm) {
	const onload = frm.doc.__onload || {};
	const warning = onload.snapshot_isolation_warning;
	const skipped = onload.unanalysed_items;
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
	if (skipped) {
		notes.push(
			frappe.utils.escape_html(
				(skipped === 1
					? __("1 item could not be analysed in the last stock check and was skipped.")
					: __(
							"{0} items could not be analysed in the last stock check and were skipped.",
							[skipped]
					  )) +
					" " +
					__("Open the latest Munimji Agent Run to see which.")
			)
		);
	}
	frm.set_intro(notes.join("<br><br>"), warning ? "red" : "yellow");
}
