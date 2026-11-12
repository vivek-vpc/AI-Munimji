# AI Munimji: Privacy Policy

Version 0.1 · Draft of 12 Nov 2026 (Telegram added) · This is a plain-language policy written for an open-source app. It is not legal advice; have it reviewed before you rely on it for a public listing.

## In short

AI Munimji runs inside your own ERPNext site. By default it **sends no data out of your site**, makes **no calls to any outside service**, and uses **no AI model**. It does not collect usage statistics, and it sets no cookies of its own. There is one optional exception, **Telegram**: a Munimji Manager can switch it on, it is off until then, and what it sends is listed under “What leaves your site”.

## Who is who

- **You** (the site owner) decide what the app is used for and are responsible for the data on your site.
- **The publisher** of the app is [your name], contact vivek.vpc1985@gmail.com. The publisher does not receive any data from your site.
- **Frappe Cloud** (if you use it) hosts your site and is covered by its own policy. AI Munimji does not change that.

## What the app reads

When the stock monitor is switched on, a scheduled job reads data that is already in your ERPNext site:
- items, warehouses and stock levels;
- stock movement history, to work out how fast items are used;
- open sales orders that are due;
- suppliers, their prices, delivery times, payment terms and existing orders;
- tax setup (Tax Rules and default purchase taxes), where ERPNext allows it.

The scheduled job reads as the site's Administrator. When a person uses the app, it reads only what that person is allowed to see in ERPNext.

## What the app stores

In your site's own database, as DocTypes (the full table is in `docs/STORES.md`):
- purchase requests and proposals: the item, quantity, chosen supplier, the reasons for the choice, costs and the tax figures used;
- the decisions: who answered, when, and what they decided;
- a tamper-evident seal over that history (added by the next run of the scheduled job);
- a log of what the app did (kept for 90 days by default; the setting is "Keep logs for (days)");
- its own settings;
- if Telegram is switched on: the bot token and a secret for Telegram’s calls (both in Password fields, encrypted), and for each person who connected a chat a Munimji Telegram Link (the user, the chat number and the date). The ids of the Telegram messages already handled are kept for seven days so that none is handled twice.

Seven read-only custom fields are added to Purchase Order, Material Request and Stock Entry. They hold the request's reference and who approved it; Material Request also has a note field.

## What the app writes to ERPNext

Draft documents, created under the approver's own login. The app **never submits** a document. An approver can later change the quantity of, or cancel, an order that was made from a request, and that acts on the order as ERPNext allows, including one that has been submitted by a person.

## What leaves your site

**By default, nothing.** Specifically, with Telegram switched off (it is off after install):
- no data is sent to the publisher, to any AI provider or to any other third party;
- no e-mail or message is sent. The only notification is shown inside your site, in the Desk bell, to people with the role Munimji Approver;
- there is no analytics, tracking or telemetry.

**With Telegram switched on** (AI Munimji Settings, “Send requests on Telegram”, by a Munimji Manager, with a bot token the manager made with @BotFather), the site talks to Telegram (`api.telegram.org`) and nobody else:
- each request that needs an answer is sent as a message to the Telegram chat of every person who connected one and may answer requests. The message carries the request’s text: the item, the quantity, the warehouse, the vendors that were compared with their prices, delivery times and totals, the reasons, and the tax figures where the request shows them, with its buttons;
- reminders, the outcome of an answer (who answered, for example “by anna@example.com via telegram”, and the number of the draft Purchase Order made) and what a person types in the chat (a quantity, a vendor, yes or no) pass through Telegram too;
- Telegram keeps those messages under its own policy, and an ordinary bot chat is not end-to-end encrypted. Anyone who can read that chat on a person’s devices, or who holds the bot token, can read them;
- Telegram tells the site each button press and message, with the sender’s chat number. The site keeps the chat number of people who connected one. A stranger who writes to the bot is answered, at most once every half minute, with their own number and nothing else;
- the bot token is sent to Telegram in the address of each call, as Telegram requires. It is never shown on a page, written in a log, put in a message or put in an error;
- a person can disconnect at any time (the Disconnect button, or deleting their Munimji Telegram Link), and switching Telegram off stops every message. Messages already in Telegram stay there; only the person can delete them.

In both cases **no data is sent to the publisher**.

If a later version adds anything else that sends data out (for example e-mail or a hosted AI model), it will be off by default, and this policy will be updated before such a change is made available.

## Who can see the data

Only people on your site with the app's roles (Munimji Viewer, Approver, Manager) or System Manager, and, for stock and order details, only if ERPNext also lets them see that data. The app adds no permissions to any ERPNext DocType. With Telegram on, anyone in a connected chat also sees the requests sent there.

## Keeping and deleting data

- Logs older than the setting "Keep logs for (days)" (90 by default) are removed by a clean-up that runs once a day on your site's scheduler. It runs while that setting is a positive number; with 0 it does not run and every log is kept. You can also run it by hand: `bench --site <site> execute ai_munimji.retention.clean_up`. Requests, proposals, alerts and the audit seal are never removed by it.
- If you uninstall the app, its DocTypes and the data in them are removed with it. Database columns that Frappe cannot drop stay in the database, and any Purchase Orders already made stay. See the uninstall notes.
- Deleting a user deletes their Telegram link. Disconnecting stops the messages; it cannot remove messages already in Telegram.
- Export anything you need to keep before you uninstall.

## Your rights

The data belongs to your site. You can view, export or delete it with ERPNext's normal tools. If the people whose data you hold (for example supplier contacts) have rights under a law that applies to you, you are the one who answers them. The publisher holds none of that data.

## Changes

Changes to this policy are published in the repository with a new date. The change history is public.

## Contact

[Your name] · vivek.vpc1985@gmail.com · [link to the repository's issue page]
