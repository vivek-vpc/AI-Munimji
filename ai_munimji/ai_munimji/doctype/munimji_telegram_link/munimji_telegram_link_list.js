// Copyright (c) 2026, AI Munimji project and contributors
// For license information, please see license.txt

const CONNECTION_POLL_MS = 3000; // how often the dialog asks whether the person has pressed Start in Telegram
const TELEGRAM_HOST = "t.me";

// The list of Telegram links holds one row per person who has connected a chat. The way to get a row is the button: nobody types a chat number. The server makes a link to the bot with a
// one-time code in it; the person opens it where they use Telegram and presses Start, and the bot connects that chat to this user. The page has no address of its own in it: the link comes from
// the server, and is only used if it points at Telegram.
frappe.listview_settings["Munimji Telegram Link"] = {
	onload: place_the_button,
	refresh: place_the_button,
};

// Frappe takes the list's main button away from a person who may not create records in it, and nobody may here (the bot makes them). So the button is put back every time the list is drawn.
function place_the_button(listview) {
	listview.page.set_primary_action(
		__("Connect Telegram"),
		() => connect_telegram(listview),
		"link"
	);
}

function points_at_telegram(link) {
	try {
		return new URL(link).hostname === TELEGRAM_HOST;
	} catch (error) {
		return false;
	}
}

function connect_telegram(listview) {
	return frappe
		.call({
			method: "ai_munimji.telegram.api.connect",
			freeze: true,
			freeze_message: __("Making your link..."),
		})
		.then((r) => {
			const out = r.message || {};
			if (!out.ok || !points_at_telegram(out.link)) {
				frappe.msgprint({
					title: __("Connect Telegram"),
					message: frappe.utils.escape_html(
						out.message || __("Telegram could not be connected.")
					),
					indicator: "orange",
				});
				return;
			}
			show_the_link(listview, out);
		});
}

function show_the_link(listview, out) {
	const esc = frappe.utils.escape_html;
	const dialog = new frappe.ui.Dialog({
		title: __("Connect Telegram"),
		fields: [{ fieldtype: "HTML", fieldname: "steps" }],
		primary_action_label: __("Open Telegram"),
		primary_action() {
			window.open(out.link, "_blank", "noopener");
		},
	});
	dialog.fields_dict.steps.$wrapper.html(
		`<p>${esc(out.message)}</p>` +
			`<p><a href="${esc(out.link)}" target="_blank" rel="noopener"><b>${esc(
				out.bot
			)}</b></a></p>` +
			`<p class="text-muted">${esc(__("Waiting for you to press Start in Telegram..."))}</p>`
	);
	let timer = null;
	const stop = () => {
		clearTimeout(timer);
		timer = null;
	};
	const watch = () => {
		timer = setTimeout(() => {
			frappe
				.call({ method: "ai_munimji.telegram.api.connection", type: "GET" })
				.then((r) => {
					if (!dialog.is_visible) {
						return;
					}
					if ((r.message || {}).connected) {
						stop();
						dialog.hide();
						frappe.show_alert(
							{
								message: esc(
									__("Telegram is connected. Requests will arrive in your chat.")
								),
								indicator: "green",
							},
							8
						);
						listview.refresh();
					} else {
						watch();
					}
				});
		}, CONNECTION_POLL_MS);
	};
	dialog.onhide = stop;
	dialog.show();
	watch();
}
