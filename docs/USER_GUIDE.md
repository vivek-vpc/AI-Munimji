# AI Munimji: User guide

Version 0.1 · Draft of 9 Nov 2026. For ERPNext version 16. Check each step against the app before you publish this page.

## What it is

AI Munimji watches your stock and prepares purchase requests for a person to approve. It never approves by itself, never submits a document, and in this version sends nothing out of your site.

## Before you start

- ERPNext version 16 on your site.
- **People and roles.** AI Munimji adds three roles. Give each person the right ones:

| A person who... | Munimji role | ERPNext roles they also need |
|---|---|---|
| looks at requests | Munimji Viewer | Stock User |
| answers requests (creates a draft Purchase Order under their own login) | Munimji Approver | Stock User and Purchase User |
| changes the settings | Munimji Manager | as an approver, if they also answer |

- A person with only a Munimji role sees none of your stock or orders. That is intended.
- **Database setting.** For two people pressing the same button at the same moment to wait their turn, your MariaDB needs `innodb_snapshot_isolation` set to OFF. Frappe's own Docker files do this. If it is ON, AI Munimji warns you after install and on its Settings page; nothing is ordered twice, but the second press gets a short message that another press is being handled. innodb_snapshot_isolation is OFF on Frappe Cloud as of 11 Nov 2026 as tested on my own servers. 

## First setup

1. Open **AI Munimji Settings** (search for it in the awesomebar).
2. Review the thresholds, the **Check stock at** time and the demand calendar.
3. Check who holds the role **Munimji Approver**. They are told in the Desk bell when a request is made.
4. Tick **Watch stock** and save. The monitor is off until you do. Saving starts the scheduled job at the time you set. The page refuses a schedule that can start the check less than 15 minutes after the last start, because every check reads all your stock (0 6 * * * is every day at 6 in the morning, 0 * * * * is every hour).
5. To check the stock straight away instead of waiting for the set time, press **Run the check now** (Munimji Managers and System Managers). It refuses while a check is already waiting or running. The page shows when the last check ran, how far it got and how many requests it made.
6. Check **Keep logs for (days)**. It is 90 by default. A clean-up runs once a day and removes the logs of what the app did that are older than this; it never removes a request, a proposal, an alert or the audit seal. Set it to 0 to keep every log; the clean-up then does not run.

## How a request flows

A request goes through three steps. The page of each request has a **Flow** block at the top: every step is a link, and the step you are looking at is marked.

1. **Reorder request.** The stock check looks at every item. For each one that is running low it makes a Reorder request and tells the people who may approve.
2. **Purchase request.** When an approver approves a reorder, the vendors are compared in the background (price, delivery time, how often each delivered on time). About a minute later a Purchase request appears in **Munimji Approval Request**, with the vendor it recommends and why it did not choose the others. For an item with no purchase history no comparison is possible: the request says so, and you order it in ERPNext by hand and press **Got it**.
3. **Draft Purchase Order.** When an approver approves the purchase request, ERPNext gets a Draft Purchase Order in the approver's name. It is only a draft: open it in ERPNext, check it and submit it. Nothing is sent to the vendor.

**Timing.** The stock check runs at the time set under **Check stock at**, or when a manager presses **Run the check now** on the Settings page. The vendor comparison starts right after a reorder is approved and takes about a minute; if a stock check is running at that moment, the next scheduled check makes it. After every answer the page says in one sentence what happens next and where to look.

**Who sees what.** Viewers see the requests. Approvers also answer them and make the draft order. Managers also change the settings and run the check.

## A request, step by step

There are two answers on the way from low stock to an order.

1. **A reorder request appears** when an item is below what the rules allow. Approvers see a notification in the Desk bell, once per request. Open it from the list **Munimji Approval Request**. Approve it to start the reorder (or dismiss it).
2. **About a minute after you approve the reorder**, the app has compared your suppliers and made a **purchase request**. This one shows the current stock, how long it will last, how long a new order takes, the chosen supplier and the cost.
3. **Read why.** The purchase request explains why this supplier was chosen and why each of the others was not.
4. **Answer it:**
   - **Approve** creates a **draft** Purchase Order under your own login, with the request's reference and your name on it.
   - **Change quantity** or **Change vendor** makes a new request with the new figures, and the approvers are told again.
   - **Dismiss** closes it without an order.
   - **Got it** closes a request that you started by hand.
5. **The first answer wins.** If two approvers answer at once, the second is told who answered first and nothing is ordered twice.
6. **Review and submit the draft** in ERPNext as you normally would. The app never submits it. An approver can later change the quantity of, or cancel, an order made from a request.
7. **The audit seal** over the history is added at the next run of the scheduled job, and the job runs only while Watch stock is ticked.

## Telegram (if your manager has switched it on)

You can get the requests in a Telegram chat, with buttons, and answer there. Open **AI Munimji** → **Telegram**, press **Connect Telegram**, open the link it shows where you use Telegram and press **Start**. From then on the requests made after that arrive in your chat. Pressing a button is your own answer, with your own rights, exactly as in the Desk; the other place is tidied up, and the first answer wins. **Change quantity** and **Change vendor** ask a question: type the answer, or reply to the order request with a number. Disconnect from the same list whenever you want. The steps for a manager, what is sent to Telegram and what to do if the bot is silent are in `docs/TELEGRAM.md`.

## Taxes in a request

The scheduled check reads your tax setup as Administrator and keeps the figures with the request. If a request shows "Taxes are not included in these totals", the app could not read tax data, and every total is before tax. If ERPNext applies no tax for that supplier, the request says so in different words.

## What is not in version 0.1

A dry run, a stock monitor report, expiry, e-mail notifications, supplier follow-up messages and the AI features (the AI chat in Telegram too). Reminders exist only on Telegram. See `docs/KNOWN_LIMITATIONS.md`. Requests wait until someone answers them.

## If something does not work

- **No requests appear:** check that Watch stock is ticked, that an item is really below its limit, and that the Settings page shows no warning. The scheduler needs to be enabled on your site.
- **You approved a reorder and no purchase request has appeared:** wait a minute and look at the Flow block at the top of the reorder request; it says what is happening. If a stock check was running when you approved, the next scheduled check makes the request. For an item with no purchase history there is no vendor to compare: the request that appears tells you to order it in ERPNext by hand and press **Got it**.
- **"Not permitted" on Approve:** the person needs both the Munimji Approver role and permission to create a Purchase Order in ERPNext (Purchase User).
- **A person sees no stock in a request:** they need Stock User.
- **A second press says another press is being handled:** see the database setting above.
- **The Settings page says "N items could not be analysed":** the last stock check skipped those items and looked at all the others. Open the latest Munimji Agent Run to see which items and why. The note goes at the next check that analyses every item.

## Taking it out

Uninstall it with the normal app uninstall. It removes the app's roles, DocTypes, custom fields and scheduled job. Database columns that Frappe cannot drop stay, and Purchase Orders already made stay. Export anything you want to keep first. Details: `docs/UNINSTALL.md`.

## Getting help

See the [Support page](SUPPORT.md).
