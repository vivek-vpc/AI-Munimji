# AI Munimji

A Frappe app for ERPNext v16, planned to help with stock monitoring and purchase requests. **This repository is at its very beginning.** It is not released, not listed on the Frappe Marketplace, and not installable from it.

What is here, branch by branch:

- `main`: this file and nothing else.
- `frappe/1-spike`: a throw-away spike that checks, on a real bench, how the pieces fit (one DocType, one scheduled job, one approval that creates a draft Purchase Order, and an uninstall). It is a measurement, not a feature, and it has been run only on Frappe v16 and ERPNext v16 in a development container.

The rules the app is being built to: rules decide and a language model, if one is ever used, only explains; nothing is approved by the app itself; ERPNext receives draft documents only, with the approver recorded; version 0.1 sends nothing out of the site and calls no model.

Licence: GPL-3.0-or-later.
