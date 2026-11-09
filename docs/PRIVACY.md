# AI Munimji: Privacy Policy

Version 0.1 · Draft of 9 Nov 2026 · This is a plain-language policy written for an open-source app. It is not legal advice; have it reviewed before you rely on it for a public listing.

## In short

AI Munimji runs inside your own ERPNext site. In version 0.1 it **sends no data out of your site**, makes **no calls to any outside service**, and uses **no AI model**. It does not collect usage statistics, and it sets no cookies of its own.

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
- its own settings.

Seven read-only custom fields are added to Purchase Order, Material Request and Stock Entry. They hold the request's reference and who approved it; Material Request also has a note field.

## What the app writes to ERPNext

Draft documents, created under the approver's own login. The app **never submits** a document. An approver can later change the quantity of, or cancel, an order that was made from a request, and that acts on the order as ERPNext allows, including one that has been submitted by a person.

## What leaves your site

**Nothing.** Specifically in version 0.1:
- no data is sent to the publisher, to any AI provider or to any other third party;
- no e-mail or message is sent. The only notification is shown inside your site, in the Desk bell, to people with the role Munimji Approver;
- there is no analytics, tracking or telemetry.

If a later version adds anything that sends data out (for example e-mail, chat messages or a hosted AI model), it will be off by default, and this policy will be updated before such a change is made available.

## Who can see the data

Only people on your site with the app's roles (Munimji Viewer, Approver, Manager) or System Manager, and, for stock and order details, only if ERPNext also lets them see that data. The app adds no permissions to any ERPNext DocType.

## Keeping and deleting data

- Logs older than the setting "Keep logs for (days)" (90 by default) are removed by a clean-up that runs once a day on your site's scheduler. It runs while that setting is a positive number; with 0 it does not run and every log is kept. You can also run it by hand: `bench --site <site> execute ai_munimji.retention.clean_up`. Requests, proposals, alerts and the audit seal are never removed by it.
- If you uninstall the app, its DocTypes and the data in them are removed with it. Database columns that Frappe cannot drop stay in the database, and any Purchase Orders already made stay. See the uninstall notes.
- Export anything you need to keep before you uninstall.

## Your rights

The data belongs to your site. You can view, export or delete it with ERPNext's normal tools. If the people whose data you hold (for example supplier contacts) have rights under a law that applies to you, you are the one who answers them. The publisher holds none of that data.

## Changes

Changes to this policy are published in the repository with a new date. The change history is public.

## Contact

[Your name] · vivek.vpc1985@gmail.com · [link to the repository's issue page]
