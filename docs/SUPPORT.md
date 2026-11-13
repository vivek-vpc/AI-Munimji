# AI Munimji: Support

Support is best-effort and free. There is no service level.

## Ask a question or report a problem

Open an issue: https://github.com/vivek-vpc/AI-Munimji/issues for the app, or https://github.com/vivek-vpc/erpnext-ai-agents/issues/ for the rules package it uses (`ai-munimji-engine`).

Please include:
- your Frappe and ERPNext versions, and whether the site is on Frappe Cloud or your own bench;
- what you did, what you expected, and what happened;
- the exact text of any error message (remove customer names and other private data first);
- for a problem with Telegram: whether it is switched on, whether it is in webhook or polling mode, and what AI Munimji Settings shows under Telegram (for example "Telegram's last delivery error").

Please do not post passwords, API keys, a Telegram bot token, the webhook secret or customer data in an issue. If a bot token was posted by mistake, revoke it with @BotFather (`/revoke`) at once: anyone who has it can read and send in the bot's chats.

## Security problems

Do not open a public issue for a security problem. Write to vivek.vpc1985@gmail.com with "AI Munimji security" in the subject. You will get an acknowledgement; there is no promised fix time. (GitHub's private vulnerability reporting is not available for this repository at the moment.)

## Before you ask

- Read the [User guide](USER_GUIDE.md), in particular "If something does not work", and, for Telegram, [Telegram](TELEGRAM.md), "If something does not work".
- Check the known limits in `docs/KNOWN_LIMITATIONS.md`: some things are not part of version 0.1.

## What is covered

Problems with the app itself on ERPNext version 16, including setting up and using its Telegram connection. Not covered: custom changes to your site, other apps, hosting, and your own ERPNext data; and for Telegram, Telegram's own service and apps, an outage there, and a network or country that blocks Telegram.

