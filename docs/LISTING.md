# AI Munimji: listing (draft v3, 13 Nov 2026)

**Nothing here has been released.** Rewritten after Claude Code compared the first draft with the code, and after I read Frappe's new registry (`github.com/frappe/marketplace`, README and docs, 9 Nov 2026). Draft v3 adds the optional Telegram connection to the description, the claims, the screenshots and the video. Re-check every claim against the app at the release commit. Items in [square brackets] are for you to fill in.

## 1. How the listing is submitted: the registry

Frappe's new Marketplace is a GitHub repository, [frappe/marketplace](https://github.com/frappe/marketplace). You add your app with a pull request. An automated check installs it on a real bench; a new app that passes **merges on its own**, with no manual approval (see its `docs/auto-merge/rules.md`). The older route (the Frappe Cloud dashboard, "Become a Publisher", a review of up to 10 days) is described in the older docs. **Which route Frappe Cloud shows to users today is not fully clear to me, so check the dashboard too** and ask on the forum if both exist.

Two files go into the registry pull request:

**`apps.json`: add this entry** (every field is required)

```json
{
  "name": "ai_munimji",
  "title": "AI Munimji",
  "description": "Watches stock and prepares draft purchase orders for approval",
  "repo": "https://github.com/vivek-vpc/AI-Munimji",
  "logo_url": "https://raw.githubusercontent.com/vivek-vpc/AI-Munimji/main/docs/img/ai-munimji-logo.png",
  "website": "https://github.com/vivek-vpc/AI-Munimji",
  "documentation": "https://github.com/vivek-vpc/AI-Munimji/blob/main/docs/USER_GUIDE.md",
  "categories": ["Inventory", "Purchasing"],
  "category": "Applications",
  "stars": 0,
  "releases": "apps/ai_munimji.json"
}
```

- `description` is one line (61 characters here).
- `logo_url` must be a **direct URL to a square PNG or SVG**. Put `ai-munimji-logo-1024.png` in the repository at `docs/img/ai-munimji-logo.png`. The link works only after the repository is public.
- `category` must be one of Applications, Compliance, Developer Tools, Extensions, Integrations, Utilities.

**`apps/ai_munimji.json`: the release**

```json
{
  "name": "ai_munimji",
  "releases": [
    {
      "version": "0.1.1",
      "branch": "main",
      "commit": "[the full 40-character SHA of the release commit]",
      "frappe_core": "[copied exactly from pyproject.toml: [tool.bench.frappe-dependencies].frappe]",
      "dependencies": {},
      "channel": "stable"
    }
  ]
}
```

- The commit must be on `main` of your public repository, and `version` and `frappe_core` must match what that commit's `pyproject.toml` declares.
- `dependencies` lists **other Marketplace apps** only. Python packages such as `ai-munimji-engine` come from `pyproject.toml`; the check installs the app as Pilot's `get-app` does, so the engine must already be **on PyPI** when the check runs.

The old dashboard route (if it is still offered) also asks for a support link, a Terms of Service link and a Privacy Policy link. Keep those pages: they are good practice either way.

## 2. Long description (README, website, or the dashboard form)

AI Munimji watches the stock in your ERPNext site and, when an item is running low, prepares a purchase request for a person to approve.

**What it does**
- Checks stock on a schedule you set, using the usage history and the demand calendar on your site.
- Starts with a **reorder request**. When an approver agrees, the app compares your suppliers on price, delivery time and terms within about a minute, and picks one by fixed rules.
- Shows the purchase request in plain words: the stock you have, how long it will last, how long a new order takes to arrive, and the cost, with taxes where they can be read.
- Explains **why this supplier was chosen and why each of the others was not**.
- Lets an approver approve, change the quantity or the vendor, or dismiss it. The first answer wins; a later one is told who answered first.
- On approval, creates a **draft** Purchase Order under the approver's own login, with the request's reference and the approver recorded on it.
- Keeps a record of every request and decision, with a tamper-evident seal over the history.
- **Optional: answer in Telegram.** A manager can switch on a Telegram connection. Each request then also arrives, with buttons, in the Telegram chat of every person who connected one (a person connects with one tap on a link). A press is that person's own answer, with their own rights: the Draft Purchase Order is made in their name, ERPNext refuses what it would refuse them in the Desk, and the first answer wins. Reminders go to the same chat. It works with a public HTTPS site (webhook) or on a site Telegram cannot reach (polling).

**What it will not do**
- It never approves anything by itself. A person answers every request.
- It never submits a document. It creates drafts. An approver can later change the quantity of, or cancel, an order made from a request.
- By default it sends nothing out of your site and calls no AI model. If a manager switches on the optional Telegram connection, requests are also sent to the Telegram chats of the people who connected one (`docs/TELEGRAM.md`, `docs/PRIVACY.md`). Nothing is ever sent to a vendor, and the bot has no AI model: it does not answer questions about your stock and cannot order anything by itself.
- It does not move stock between warehouses, send e-mail, or remind anyone in the Desk (reminders exist on Telegram only).

**How a request flows**
1. **Reorder request.** The stock check looks at every item. For each one that is running low it makes a Reorder request and tells the people who may approve.
2. **Purchase request.** When an approver approves a reorder, the vendors are compared in the background (price, delivery time, how often each delivered on time). About a minute later a Purchase request appears in Munimji Approval Request, with the vendor it recommends and why it did not choose the others. For an item with no purchase history no comparison is possible: the request says so, and you order it in ERPNext by hand and press Got it.
3. **Draft Purchase Order.** When an approver approves the purchase request, ERPNext gets a Draft Purchase Order in the approver's name. It is only a draft: open it in ERPNext, check it and submit it. Nothing is sent to the vendor.

Timing: the stock check runs at the time set under Check stock at, or when a manager presses Run the check now on the Settings page. The vendor comparison starts right after a reorder is approved and takes about a minute; if a stock check is running at that moment, the next scheduled check makes it.

Who sees what: Viewers see the requests. Approvers also answer them and make the draft order. Managers also change the settings and run the check. People who connect Telegram see the requests sent to their own chat and answer there with their own rights; a Manager switches Telegram on and sees every connection.

**Which roles**
Three roles control the app's own pages: Munimji Viewer, Munimji Approver and Munimji Manager. What a person can see of your stock and orders is still decided by ERPNext's own roles.

**Good to know**
- The stock monitor is **off** after installation. Review the thresholds on the AI Munimji Settings page, then switch it on.
- **Telegram is optional and off after installation.** Switching it on needs a bot made with @BotFather and its token, and either a public HTTPS address (webhook) or two workers for the `long` queue (polling). With it on, the text of each request (items, quantities, vendor names with prices, delivery times and totals, the reasons) goes to Telegram, which keeps it under its own policy; the bot token is kept encrypted and never shown. What leaves the site, and what does not: `docs/PRIVACY.md`.
- The version covers stock monitoring, supplier comparison and approval, in the Desk and, optionally, on Telegram. Expiry of requests, reminders in the Desk, e-mail notifications, moving stock between warehouses, an AI chat, a stock monitor report and the supplier follow-up features are not part of it (`docs/KNOWN_LIMITATIONS.md`).
- Works with Frappe and ERPNext version 16.
- Free and open source under GPL-3.0-or-later.

## 3. Claims to re-check before the release commit

| Claim | Where to check |
|---|---|
| Creates drafts, never submits; an approver can change or cancel an order made from a request | `ai_munimji/erp_client.py`, the order tests |
| Two answers from low stock to an order (reorder request, then purchase request about a minute after the reorder is approved) | the browser round trip |
| Nothing leaves the site unless a manager switches Telegram on; no model | `docs/PRIVACY.md`, `docs/TELEGRAM.md`, the outbound-block tests (tests/test_nothing_leaves.py names the one exception) |
| Optional: requests arrive in Telegram with buttons and are answered there, with the answering person’s own rights | `docs/TELEGRAM.md`, the Telegram tests (`tests/test_telegram_*.py`), `dev/telegram-e2e.ps1` |
| Telegram is off after install, and nothing is sent while it is off | `docs/PRIVACY.md`, `tests/test_telegram_flow.py` ("switched off means nothing leaves") |
| The webhook is the only method open to guests and refuses any call without Telegram's secret | `tests/test_rules.py`, `tests/test_telegram_webhook.py` |
| The bot token is kept encrypted and is never shown, logged or put in a message or an error | `docs/PRIVACY.md`, `tests/test_telegram_links.py`, `tests/world/test_nothing_leaves.py` |
| Reminders exist on Telegram only; nothing is sent to a vendor; the bot has no AI model | `docs/KNOWN_LIMITATIONS.md`, `docs/TELEGRAM.md` |
| Stock monitor off after install | `docs/INSTALL.md`, the settings tests |
| First answer wins | the approval tests |
| The purchase request lists why other suppliers lost | the form on a real request |
| Notification in the Desk bell only | `docs/KNOWN_LIMITATIONS.md` |
| The audit seal is added by the next job run, and only while Watch stock is on | `docs/KNOWN_LIMITATIONS.md` |
| Works with version 16 only | the `frappe_core` range in `pyproject.toml` |
| Needs MariaDB with `innodb_snapshot_isolation` OFF for two simultaneous presses to wait their turn; the app warns when it is ON | `docs/INSTALL.md`, the Settings page |

## 4. Screenshots to take (from the demo site, with the seed data)

Use fictional items and suppliers. No real names, addresses or e-mail addresses.

1. AI Munimji Settings, with the stock monitor switched on.
2. The list of requests (pending).
3. The first request (the reorder).
4. The purchase request: the stock, how long it lasts, the chosen supplier.
5. The same request scrolled to **why the other suppliers were not chosen**.
6. The Change quantity dialog.
7. The request after approval, with the draft order's number shown on it.
8. The draft Purchase Order, showing the request reference and the approver.
9. The AI Munimji home page (the shortcuts, with the count of requests waiting) and, if you like, the apps screen with the AI Munimji tile.
10. AI Munimji Settings, the **Telegram** section: the switch, the mode, and the status after "Connect the bot". **The Bot token field stays empty or shows only dots.**
11. The **Connect Telegram** dialog with its link. **Blur the one-time code.**
12. A request in a Telegram chat, with its buttons, and the same request after it was answered (the buttons gone, the outcome under it). Use a bot made for the screenshot, a fictional person and fictional items; no real chat number, name or token.

Each image: at least 1280 px wide, light theme, no browser toolbars, a short caption. Check each one for a bot token, a chat number, an e-mail address or a real company name before it is used.

## 5. Demo video (about 100 seconds, about 115 with the optional Telegram step; optional for the registry, useful on the page)

| Time | On screen | Say |
|---|---|---|
| 0:00 | Stock list, one item low | "Stock for bolts is running low." |
| 0:10 | AI Munimji Settings, monitor on | "I switch on the stock monitor and set the time of the check." |
| 0:20 | The reorder request (bell shows it) | "AI Munimji raises a reorder request and tells the approver." |
| 0:30 | Approve it | "The approver agrees. About a minute later the app has compared the suppliers." |
| 0:45 | The purchase request | "It shows the stock, how long it lasts, and how long a new order takes." |
| 1:00 | Supplier comparison | "It picked this supplier, and explains why each other supplier was not chosen." |
| 1:15 | Change quantity, Approve | "The approver can change the quantity. Approving creates a draft order." |
| 1:30 | The draft Purchase Order | "ERPNext gets a draft with the request and approver recorded. A person still reviews and submits it." |
| 1:40 | (optional) A phone showing the same request in Telegram, a press of Create order | "Optionally, the request also arrives in Telegram. The press is the approver's own answer, with their own rights." |
| 1:55 | Title card | "AI Munimji. Open source, for ERPNext 16." |

## 6. Publishing steps (registry)

For the release that adds Telegram, the extra checks are item 8 of `docs/RELEASE_CHECKLIST.md`, and the engine to publish first is the one that holds the Telegram channel (0.1.3 or later, already on PyPI); the steps below are otherwise the same.

1. Engine first: tag `engine-v0.1.1` in `erpnext-ai-agents`, approve the publish, check the package on PyPI.
2. App release commit (Claude Code, per `docs/RELEASE_CHECKLIST.md`): exact engine pin `ai-munimji-engine==0.1.1`, version 0.1.1, "not released" wording changed, logo added at `docs/img/`. CI green on that commit.
3. Make `AI-Munimji` public. Check that the logo URL, the documentation page and the licence open in a private browser window.
4. Run the registry's check locally against the release commit (clone `frappe/marketplace`, see its `docs/marketplace-check`). Fix what it finds.
5. Fork `frappe/marketplace`, add the two files above, open the pull request. Read the check's comment on it; comment `/rereview` to run it again.
6. If it passes, a new app merges on its own. If it is labelled `held-for-review`, read the reason in the Auto-merge Registry run.
7. In parallel, check whether the Frappe Cloud dashboard still offers "Become a Publisher", and follow it if it does.

## Note: the MariaDB setting

`docs/INSTALL.md` says the parallel-press protection needs MariaDB with `innodb_snapshot_isolation` OFF. Frappe's own Docker files set it that way. On Frappe Cloud it was checked on 11 Nov 2026 on one site (`SHOW VARIABLES LIKE 'innodb_snapshot_isolation'` returned OFF). An app cannot change this setting, and Frappe Cloud may change its configuration later, so the app warns after install and on its Settings page when the setting is ON. Do not claim more than this: say OFF on Frappe Cloud as checked on that date, not "always".
