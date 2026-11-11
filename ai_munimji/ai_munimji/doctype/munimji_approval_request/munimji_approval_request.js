// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

// The approval form. The request is shown in words, drawn from the JSON the engine stored with it (request_json): its sections, its figures and the effect of each answer are the engine's own
// and nothing is worked out again here. The buttons carry the person's answer to ai_munimji.api.answer; what an answer does, and who may give it, is decided on the server, and the first
// answer wins (the second is told who answered first).

const HEADINGS = {
	// the engine's section names, said in the words of this screen (any other heading is shown as the engine wrote it)
	Recommendation: __("What is proposed, and what it costs"),
	"Stock position": __("The stock, and how long it lasts"),
	"Why this vendor": __("Why this vendor"),
	"Other vendors": __("The other vendors, and why they were not chosen"),
	"How vendors were scored": __("How the vendors were scored"),
	"Note to vendor": __("Note to the vendor"),
	Notes: __("Notes"),
	"What is needed": __("What is needed"),
	"Vendors checked": __("The vendors that were checked"),
	"Every vendor": __("Every vendor's figures"),
	"Duties and taxes by vendor": __("Duties and taxes, by vendor"),
	"How the score works": __("How the score works"),
};

function stored(value) {
	if (value && typeof value === "object") {
		return value;
	}
	try {
		return value ? JSON.parse(value) : {};
	} catch (e) {
		return {};
	}
}

function esc(text) {
	return frappe.utils.escape_html(text === null || text === undefined ? "" : String(text));
}

function section_html(section, level) {
	const heading = HEADINGS[section.heading] || section.heading;
	const lines = (section.lines || []).map((line) => `<li>${esc(line)}</li>`).join("");
	return `<div style="margin-bottom: var(--margin-lg)"><h${level} style="margin-bottom: var(--margin-sm)">${esc(
		heading
	)}</h${level}><ul style="padding-left: var(--padding-lg)">${lines}</ul></div>`;
}

function glance_html(frm, request) {
	const facts = request.facts || {};
	const rows = [];
	const add = (label, value) => {
		if (value !== undefined && value !== null && value !== "") {
			rows.push(
				`<tr><td class="text-muted" style="padding-right: var(--padding-lg)">${esc(
					label
				)}</td><td><b>${esc(value)}</b></td></tr>`
			);
		}
	};
	add(__("Item"), facts.item_code || frm.doc.item_code);
	add(__("Quantity"), facts.qty);
	add(__("Vendor"), facts.supplier);
	add(__("Price each"), facts.unit_price);
	add(__("Total"), facts.total);
	return rows.length
		? `<table style="margin-bottom: var(--margin-lg)">${rows.join("")}</table>`
		: "";
}

function outcome_html(frm) {
	if (frm.doc.status === "pending") {
		return `<p><span class="indicator-pill orange">${esc(
			__("Waiting for your answer")
		)}</span></p>`;
	}
	const who = frm.doc.approver ? __("by {0}", [frm.doc.approver]) : "";
	const when = frm.doc.decided_at ? frappe.datetime.str_to_user(frm.doc.decided_at) : "";
	const what =
		frm.doc.status === "decided"
			? __("Answered: {0}", [frm.doc.answer || ""])
			: __("This request is {0}.", [frm.doc.status]);
	return `<p><span class="indicator-pill gray">${esc(what)} ${esc(who)} ${esc(when)}</span></p>${
		frm.doc.status_note ? `<p class="text-muted">${esc(frm.doc.status_note)}</p>` : ""
	}`;
}

function reasoning_html(frm, request) {
	const parts = [outcome_html(frm)];
	if (request.headline) {
		parts.push(`<p style="font-size: var(--text-lg)"><b>${esc(request.headline)}</b></p>`);
	}
	parts.push(glance_html(frm, request));
	(request.sections || []).forEach((section) => parts.push(section_html(section, 5)));
	const details = request.details || [];
	const taxed = details.some((section) => section.heading === "Duties and taxes by vendor");
	// the engine says in its own notes why there are no tax figures ("Taxes are not included in these totals: ... could not be read", or "Duties and taxes are not in this comparison: no Tax
	// Rule applies"); this plain line is only for a request that says nothing about taxes, so that the two are never both shown
	const says_nothing_about_taxes = ![...(request.sections || []), ...details].some((section) =>
		(section.lines || []).some((line) =>
			/Taxes are not included in these totals|Duties and taxes are not in this comparison/.test(
				line
			)
		)
	);
	if (!taxed && says_nothing_about_taxes && (request.facts || {}).total !== undefined) {
		parts.push(
			`<p class="text-muted">${esc(__("Taxes are not included in these totals."))}</p>`
		);
	}
	if (details.length) {
		parts.push(
			`<details style="margin-bottom: var(--margin-lg)"><summary>${esc(
				__("Every vendor's figures, the duties and taxes, and how the score works")
			)}</summary>${details.map((section) => section_html(section, 6)).join("")}</details>`
		);
	}
	const options = answers(request);
	if (frm.doc.status === "pending" && options.length) {
		const items = options
			.map(
				(o) =>
					`<li><b>${esc(BUTTONS[o.action].label)}</b>: ${esc(o.description || "")}</li>`
			)
			.join("");
		parts.push(
			`<div><h5>${esc(
				__("What each button does")
			)}</h5><ul style="padding-left: var(--padding-lg)">${items}</ul></div>`
		);
	}
	return parts.join("");
}

const BUTTONS = {
	approve: { label: __("Approve"), primary: true },
	change_qty: { label: __("Change quantity") },
	change_vendor: { label: __("Change vendor") },
	dismiss: { label: __("Dismiss") },
	ack: { label: __("Got it"), primary: true }, // the only answer to a request that asks for no order: "I will handle this in the ERP"
};

// the answers the request offers that this screen has a button for, in the order of BUTTONS (the engine lists them in its own order)
function answers(request) {
	const order = Object.keys(BUTTONS);
	return (request.options || [])
		.filter((o) => BUTTONS[o.action])
		.sort((a, b) => order.indexOf(a.action) - order.indexOf(b.action));
}

const FLOW_POLL_LIMIT = 40; // a purchase request takes about a minute; the form stops asking after this many tries

// The Flow block: reorder request -> purchase request -> Draft Purchase Order, written (and escaped) on the server. While the purchase request is still being made the server says when to
// ask again, and the block is asked for again then, only while the form is on screen.
function show_flow(frm, tries) {
	const field = frm.fields_dict.flow;
	if (!field || frm.is_new()) {
		return;
	}
	clearTimeout(frm.__flow_timer);
	frappe
		.call({ method: "ai_munimji.api.flow", args: { approval_id: frm.doc.name }, type: "GET" })
		.then((r) => {
			const flow = r.message || {};
			field.$wrapper.html(flow.html || "");
			if (
				flow.refresh_in &&
				(tries || 0) < FLOW_POLL_LIMIT &&
				field.$wrapper.is(":visible")
			) {
				frm.__flow_timer = setTimeout(
					() => show_flow(frm, (tries || 0) + 1),
					flow.refresh_in * 1000
				);
			}
		})
		.catch(() => field.$wrapper.html(""));
}

function send(frm, action, params) {
	return frappe
		.call({
			method: "ai_munimji.api.answer",
			args: {
				approval_id: frm.doc.name,
				action: action,
				params: params ? JSON.stringify(params) : null,
			},
			freeze: true,
			freeze_message: __("Sending your answer..."),
		})
		.then((r) => r.message || { ok: false, message: __("No answer") });
}

function finish(frm, result) {
	if (!result.ok) {
		// refused: the engine says why, and who answered first when someone did
		frappe.msgprint({ title: __("Not done"), message: esc(result.message), indicator: "red" });
		return frm.reload_doc();
	}
	// the server says what happens next in one sentence, and sends it again with the draft order's number as a link (already escaped there); the engine's own words stand where it has none
	frappe.show_alert(
		{ message: result.message_html || esc(result.message), indicator: "green" },
		15
	);
	if (result.approval && result.approval !== frm.doc.name) {
		// a change replaces the request with a revised one and closes this one: open the revised one
		return frappe.set_route("Form", "Munimji Approval Request", result.approval);
	}
	return frm.reload_doc();
}

function ask(frm, option) {
	const facts = stored(frm.doc.request_json).facts || {};
	if (option.action === "change_qty") {
		frappe.prompt(
			[
				{
					fieldname: "qty",
					fieldtype: "Float",
					label: __("New quantity"),
					reqd: 1,
					default: facts.qty,
				},
			],
			(values) =>
				send(frm, "change_qty", { qty: values.qty }).then((result) => finish(frm, result)),
			__("Change quantity"),
			__("Check the vendors again")
		);
	} else if (option.action === "change_vendor") {
		send(frm, "change_vendor", null).then((result) => {
			if (!result.ok || result.status !== "need_input") {
				return finish(frm, result);
			}
			frappe.prompt(
				[
					{
						fieldname: "supplier",
						fieldtype: "Select",
						label: __("Vendor"),
						reqd: 1,
						options: (result.choices || []).map((c) => ({
							value: c.id,
							label: c.label,
						})),
					},
				],
				(values) =>
					send(frm, "change_vendor", { supplier: values.supplier }).then((answer) =>
						finish(frm, answer)
					),
				__("Change vendor"),
				__("Use this vendor")
			);
		});
	} else {
		const message =
			{
				approve: __("Approve this request? {0}", [esc(option.description || "")]),
				ack: __("Mark this request as handled? {0}", [esc(option.description || "")]),
			}[option.action] || __("Dismiss this request? Nothing will be ordered.");
		frappe.confirm(message, () =>
			send(frm, option.action, null).then((result) => finish(frm, result))
		);
	}
}

frappe.ui.form.on("Munimji Approval Request", {
	refresh(frm) {
		frm.disable_save();
		if (frm.is_new()) {
			return;
		}
		const request = stored(frm.doc.request_json);
		show_flow(frm, 0);
		frm.fields_dict.reasoning.$wrapper.html(reasoning_html(frm, request));
		if (
			frm.doc.status !== "pending" ||
			!frappe.user.has_role(["Munimji Approver", "Munimji Manager"])
		) {
			return;
		}
		answers(request).forEach((option) => {
			const button = frm.add_custom_button(BUTTONS[option.action].label, () =>
				ask(frm, option)
			);
			if (BUTTONS[option.action].primary) {
				button.addClass("btn-primary");
			}
		});
	},
});
