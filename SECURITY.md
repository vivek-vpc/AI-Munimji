# Security

If you find a security problem in AI Munimji, please report it privately. Write to **vivek.vpc1985@gmail.com** with **"AI Munimji security"** in the subject. Please do not open a public issue for it.

Say which version of the app you have, which Frappe and ERPNext versions, what you did, what you saw, and, if you can, how to make it happen again. Do not send passwords, API keys, Telegram bot tokens or customer data.

You will get an acknowledgement. There is no promised time for a fix: this is a free, open-source project kept on a best-effort basis (see [docs/SUPPORT.md](docs/SUPPORT.md)).

This covers the app itself (`ai_munimji`). A problem in Frappe, ERPNext or the database server belongs with those projects.

**Telegram.** With the optional Telegram connection switched on, the app has one method that works without signing in: the webhook (`/api/method/ai_munimji.telegram.webhook.receive`), which refuses every call that does not carry the secret Telegram was given. Reports about it are in scope and welcome: a way past the secret check, a bot token or secret that is shown, logged or put in a message or an error, a Telegram press that acts as someone other than the person whose chat it is, or a message from a stranger's chat that is acted on. If you found a real token or chat number in a log or a page, say where, and do not include it in the report; the owner of the bot should revoke the token with @BotFather. A problem in Telegram itself belongs with Telegram.
