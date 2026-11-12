// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

const CHECK_POLL_MS = 5000; // how often the page asks how far a check has got, while one is queued or running
const MANAGERS = ["Munimji Manager", "System Manager"];

frappe.ui.form.on("AI Munimji Settings", {
	refresh(frm) {
		show_the_notes(frm);
		show_the_flow_help(frm);
		show_the_check(frm);
		show_telegram(frm);
	},
	enabled(frm) {
		show_the_notes(frm);
	},
	run_check_now(frm) {
		run_the_check(frm);
	},
	telegram_enabled(frm) {
		show_telegram(frm);
	},
	telegram_connect_bot(frm) {
		connect_the_bot(frm);
	},
	telegram_send_test(frm) {
		send_the_test(frm);
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

// "How a request flows": the three steps, the timing and who sees what. The same words are in docs/USER_GUIDE.md and docs/LISTING.md (tests/test_flow_docs.py keeps the three in step).
function show_the_flow_help(frm) {
	const field = frm.fields_dict && frm.fields_dict.flow_help;
	if (!field) {
		return;
	}
	const esc = frappe.utils.escape_html;
	const step = (title, text) => `<li><b>${esc(title)}</b> ${esc(text)}</li>`;
	field.$wrapper.html(
		`<ol style="padding-left: var(--padding-lg)">${[
			step(
				__("Reorder request."),
				__(
					"The stock check looks at every item. For each one that is running low it makes a Reorder request and tells the people who may approve."
				)
			),
			step(
				__("Purchase request."),
				__(
					"When an approver approves a reorder, the vendors are compared in the background (price, delivery time, how often each delivered on time). About a minute later a Purchase request appears in Munimji Approval Request, with the vendor it recommends and why it did not choose the others. For an item with no purchase history no comparison is possible: the request says so, and you order it in ERPNext by hand and press “Got it”."
				)
			),
			step(
				__("Draft Purchase Order."),
				__(
					"When an approver approves the purchase request, ERPNext gets a Draft Purchase Order in the approver’s name. It is only a draft: open it in ERPNext, check it and submit it. Nothing is sent to the vendor."
				)
			),
		].join("")}</ol>` +
			`<p class="text-muted">${esc(
				__(
					"Timing: the stock check runs at the time set under “Check stock at”, or when a manager presses “Run the check now”. The vendor comparison starts right after a reorder is approved and takes about a minute; if a stock check is running at that moment, the next scheduled check makes it."
				)
			)}</p>` +
			`<p class="text-muted">${esc(
				__(
					"Who sees what: Viewers see the requests. Approvers also answer them and make the draft order. Managers also change the settings and run the check."
				)
			)}</p>`
	);
}

function can_run_the_check() {
	return frappe.user.has_role(MANAGERS);
}

function check_html(status) {
	const rows = (status.rows || [])
		.map(
			([label, value]) =>
				`<tr><td class="text-muted" style="padding-right: var(--padding-lg)">${frappe.utils.escape_html(
					label
				)}</td><td><b>${frappe.utils.escape_html(value)}</b></td></tr>`
		)
		.join("");
	return rows ? `<table>${rows}</table>` : "";
}

function paint_the_check(frm, status) {
	frm.fields_dict.check_status.$wrapper.html(check_html(status));
	frm.toggle_enable("run_check_now", !status.busy);
}

// Shows the last check on the page and, while one is queued or running, asks again every few seconds until it has finished (or the page is no longer on screen).
function show_the_check(frm) {
	if (!frm.fields_dict || !frm.fields_dict.check_status) {
		return;
	}
	frm.toggle_display("run_check_now", can_run_the_check());
	return frappe
		.call({ method: "ai_munimji.api.check_status", type: "GET" })
		.then((r) => {
			const status = r.message || {};
			paint_the_check(frm, status);
			watch_the_check(frm, status);
		})
		.catch(() => {
			frm.fields_dict.check_status.$wrapper.html("");
		});
}

function watch_the_check(frm, status) {
	clearTimeout(frm.__check_timer);
	if (status.busy && frm.fields_dict.check_status.$wrapper.is(":visible")) {
		frm.__check_timer = setTimeout(() => show_the_check(frm), CHECK_POLL_MS);
	}
}

function run_the_check(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save the settings first"),
			message: frappe.utils.escape_html(
				__(
					"The check uses the settings as last saved. Save the page, then press the button."
				)
			),
			indicator: "orange",
		});
		return;
	}
	return frappe
		.call({
			method: "ai_munimji.api.run_check_now",
			freeze: true,
			freeze_message: __("Queueing the check..."),
		})
		.then((r) => {
			const result = r.message || {};
			frappe.show_alert(
				{
					message: frappe.utils.escape_html(result.message || ""),
					indicator: result.ok ? "green" : "orange",
				},
				10
			);
			paint_the_check(frm, result);
			watch_the_check(frm, result);
		});
}

// Telegram: what the site knows about it (no call to Telegram), and the two buttons that do call it. Everything that came from the server is escaped; the bot token is never on the page.
function rows_html(rows) {
	const body = (rows || [])
		.map(
			([label, value]) =>
				`<tr><td class="text-muted" style="padding-right: var(--padding-lg)">${frappe.utils.escape_html(
					label
				)}</td><td><b>${frappe.utils.escape_html(value)}</b></td></tr>`
		)
		.join("");
	return body ? `<table>${body}</table>` : "";
}

function show_telegram(frm) {
	const field = frm.fields_dict && frm.fields_dict.telegram_status;
	if (!field) {
		return;
	}
	if (!frm.doc.telegram_enabled) {
		field.$wrapper.html("");
		return;
	}
	return frappe
		.call({ method: "ai_munimji.telegram.api.status", type: "GET" })
		.then((r) => field.$wrapper.html(rows_html((r.message || {}).rows)))
		.catch(() => field.$wrapper.html(""));
}

function say_what_telegram_answered(result) {
	frappe.show_alert(
		{
			message: frappe.utils.escape_html(result.message || ""),
			indicator: result.ok ? "green" : "orange",
		},
		10
	);
}

function connect_the_bot(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint({
			title: __("Save the settings first"),
			message: frappe.utils.escape_html(
				__(
					"The bot is connected with the token as last saved. Save the page, then press the button."
				)
			),
			indicator: "orange",
		});
		return;
	}
	return frappe
		.call({
			method: "ai_munimji.telegram.api.connect_bot",
			freeze: true,
			freeze_message: __("Asking Telegram..."),
		})
		.then((r) => {
			const result = r.message || {};
			say_what_telegram_answered(result);
			if (result.rows) {
				frm.fields_dict.telegram_status.$wrapper.html(rows_html(result.rows));
			}
			frm.reload_doc();
		});
}

function send_the_test(frm) {
	return frappe
		.call({
			method: "ai_munimji.telegram.api.send_test",
			freeze: true,
			freeze_message: __("Sending..."),
		})
		.then((r) => say_what_telegram_answered(r.message || {}));
}
