# AI Munimji on Telegram

Telegram is an optional way to answer requests. It is **off until a Munimji Manager switches it on**. With it on, each request that needs an answer also arrives in the Telegram chat of every person who connected one, with buttons, and the answer is given there. Nothing about the Desk changes: a request can still be answered in the Desk, the first answer wins, and the other place is tidied up.

## What a person sees

- A message for each request, with the same text as in the Desk and buttons: **Start reorder**, **Create order**, **Reject**, **Details**, **Change quantity**, **Change vendor**, **Got it**, **Remind in 3d** (the buttons of the request in front of you).
- Pressing a button is **your own answer, with your own rights**: the app acts as the Frappe user your chat is connected to. A Purchase Order is made in your name, and what ERPNext would refuse you in the Desk it refuses here.
- After an answer the buttons disappear from the request message (in every chat it was sent to), the message under it says what was recorded and by whom, and one plain sentence says what happens next, the same sentence the Desk shows ("Approved. The vendors are being compared; the purchase request will appear in Munimji Approval Request in about a minute."). The purchase request that follows an approved reorder arrives in the chat too.
- **Change quantity** and **Change vendor** ask a question in the chat; type the answer (a number, or the number or name of a vendor) within ten minutes. You can also **reply to an order request with a number** to change its quantity. The request is then replaced by a revised one, which arrives last in the chat, below the sentence that says it is on its way.
- A request nobody answers is **reminded** in the chat after the time set under "Remind after (hours)", up to "Most reminders for one request" times (AI Munimji Settings, “Requests waiting for an answer”). Only the people who were sent the request are reminded.
- Anything else you type gets one sentence that says where to go. The bot **does not answer questions about your stock** (no AI model is involved) and **cannot order anything by itself**: ordering always needs the Create order button.
- `/start`, `/id` and `/help` show you your own chat number. Anyone who writes to the bot gets that, at most once every half minute, and nothing else: a chat that is not connected cannot answer a request.

## Setting it up (a Munimji Manager)

1. **Make a bot.** In Telegram open `@BotFather`, send `/newbot`, give it a name, and copy the token it gives you (`123456789:AA...`). The token is a password.
2. **Decide how answers reach the site.**
   * **Webhook** (the default): Telegram calls your site the moment someone presses a button. The site needs a public **HTTPS** address (a site on Frappe Cloud has one). Telegram only accepts HTTPS.
   * **Polling**: a background job asks Telegram for the answers. It works for a site Telegram cannot reach (a laptop, a server behind a router), and needs a **worker for the long queue** running all the time (`bench worker --queue long`, which a normal production setup has). Answers take a few seconds instead of being instant.
3. Open **AI Munimji Settings**, section **Telegram**: tick **Send requests on Telegram**, paste the token under **Bot token**, choose the mode, and **save**.
4. Press **Connect the bot**. The site asks Telegram who the token belongs to, keeps the bot's name, and registers the webhook (or starts the polling loop). The page says what happened and shows what Telegram says about the webhook. If the site is not HTTPS it tells you so and suggests Polling.
5. **Connect yourself** (below), then press **Send me a test message**.
6. Tell the people who answer requests to connect their Telegram.

Switching Telegram off stops every message at once; it does not delete the links people made.

## Connecting your chat (everyone who answers requests)

1. Open **AI Munimji** → **Telegram** (the tile on the home page) and press **Connect Telegram**.
2. A dialog shows a link to the bot. **Open it where you use Telegram and press Start.** (On the same computer, the **Open Telegram** button does it.) The link works once, for ten minutes.
3. The bot answers "Connected." and the dialog closes. From then on the requests made after that moment arrive in your chat. The ones already waiting stay in the Desk.

To stop: open your link in the list and press **Disconnect** (or delete it), or untick **Send me requests on Telegram** to pause. A Munimji Manager can disconnect anyone. A person who is deleted, disabled or no longer holds the Munimji Approver role is no longer sent requests and cannot answer through their chat. Messages already in Telegram stay there; only the person can delete them.

A chat belongs to one person and a person has one chat. Group chats and channels are not supported.

## What is sent to Telegram

See `docs/PRIVACY.md`. In short: the text of each request (items, quantities, warehouses, vendor names with their prices, delivery times and totals, the reasons, tax figures where the request shows them), the outcome of each answer (who answered, the number of a draft order), reminders, and what a person types in the chat. Telegram keeps those messages under its own policy, and an ordinary bot chat is not end-to-end encrypted. The bot token is kept encrypted on your site, appears only in the address of each call to Telegram, and is never shown, logged or put in a message.

## If something does not work

- **The test message does not arrive / the bot does not answer:** press Connect the bot again and read the message. A wrong token is refused by Telegram. In webhook mode, "Telegram’s last delivery error" on the Settings page tells you why Telegram could not reach the site (certificate, firewall, a proxy that drops the header `X-Telegram-Bot-Api-Secret-Token`).
- **Requests do not arrive in the chat but are in the Desk:** requests are sent by a background job, so a **worker** must be running; the stock check and the vendor comparison need one too. Look at Scheduled Job Log for "AI Munimji" jobs and at the Error Log.
- **Buttons show a spinner for a while:** in polling mode answers are fetched every few seconds. In webhook mode the site did not answer in time; look at the Error Log.
- **"You are not registered to answer these requests":** this chat is not connected, or the connected user was disabled or lost the Munimji Approver role. Connect again.
- **"That link has expired or was already used":** make a new one with Connect Telegram.
- **"Telegram could not be reached a moment ago":** after three failed calls the site leaves Telegram alone for a minute so that a Desk answer is never held up. It tries again by itself.
- **Switching from webhook to polling (or back):** press Connect the bot again. Telegram does not hand out updates while a webhook is registered, so the polling loop removes it first.

## Limits of this version

See "Telegram" in `docs/KNOWN_LIMITATIONS.md`.
