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
- **Database setting.** For two people pressing the same button at the same moment to wait their turn, your MariaDB needs `innodb_snapshot_isolation` set to OFF. Frappe's own Docker files do this. If it is ON, AI Munimji warns you after install and on its Settings page; nothing is ordered twice, but the second press gets a short message that another press is being handled. [Confirm for Frappe Cloud before publishing.]

## First setup

1. Open **AI Munimji Settings** (search for it in the awesomebar).
2. Review the thresholds, the **Check stock at** time and the demand calendar.
3. Check who holds the role **Munimji Approver**. They are told in the Desk bell when a request is made.
4. Tick **Watch stock** and save. The monitor is off until you do. Saving starts the scheduled job at the time you set (ERPNext's scheduler runs jobs at least 4 minutes apart).

## A request, step by step

There are two answers on the way from low stock to an order.

1. **A reorder request appears** when an item is below what the rules allow. Approvers see a notification in the Desk bell, once per request. Open it from the list **Munimji Approval Request**. Approve it to start the reorder (or dismiss it).
2. **At the next run of the scheduled job**, the app compares your suppliers and makes a **purchase request**. This one shows the current stock, how long it will last, how long a new order takes, the chosen supplier and the cost.
3. **Read why.** The purchase request explains why this supplier was chosen and why each of the others was not.
4. **Answer it:**
   - **Approve** creates a **draft** Purchase Order under your own login, with the request's reference and your name on it.
   - **Change quantity** or **Change vendor** makes a new request with the new figures, and the approvers are told again.
   - **Dismiss** closes it without an order.
   - **Got it** closes a request that you started by hand.
5. **The first answer wins.** If two approvers answer at once, the second is told who answered first and nothing is ordered twice.
6. **Review and submit the draft** in ERPNext as you normally would. The app never submits it. An approver can later change the quantity of, or cancel, an order made from a request.
7. **The audit seal** over the history is added at the next run of the scheduled job, and the job runs only while Watch stock is ticked.

## Taxes in a request

The scheduled check reads your tax setup as Administrator and keeps the figures with the request. If a request shows "Taxes are not included in these totals", the app could not read tax data, and every total is before tax. If ERPNext applies no tax for that supplier, the request says so in different words.

## What is not in version 0.1

A dry run, a stock monitor report, reminders and expiry, e-mail notifications, supplier follow-up messages and the AI features. See `docs/KNOWN_LIMITATIONS.md`. Requests wait until someone answers them.

## If something does not work

- **No requests appear:** check that Watch stock is ticked, that an item is really below its limit, and that the Settings page shows no warning. The scheduler needs to be enabled on your site.
- **"Not permitted" on Approve:** the person needs both the Munimji Approver role and permission to create a Purchase Order in ERPNext (Purchase User).
- **A person sees no stock in a request:** they need Stock User.
- **A second press says another press is being handled:** see the database setting above.

## Taking it out

Uninstall it with the normal app uninstall. It removes the app's roles, DocTypes, custom fields and scheduled job. Database columns that Frappe cannot drop stay, and Purchase Orders already made stay. Export anything you want to keep first. Details: `docs/UNINSTALL.md`.

## Getting help

See the [Support page](SUPPORT.md).
