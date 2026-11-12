"""Telegram for AI Munimji: requests arrive in a chat with buttons, and a person answers there.

The behaviour (what is sent, what a button does, who may answer, how a duplicate is recognised, what the bot says to a stranger) is the engine's:
`ai_munimji_engine.core.approvals.channels.telegram`, `.inbound` and `.typed_answers`, the same code the standalone service runs. This package is the edge that a Frappe site adds:

  config.py     what the AI Munimji Settings page says about Telegram (switch, token, mode, secret)
  transport.py  the one place that talks to the network; tests/test_nothing_leaves.py names it as the only exception
  memory.py     what is remembered between two requests, kept in the site's cache so that every process sees it
  links.py      which chat is which person, and the one-time code that connects them
  router.py     the engine's router over those links: who is told, and who is answering
  channel.py    the engine's channel, given the transport, the memory and this app's words
  inbound.py    one update from Telegram, handled as the person it came from
  webhook.py    the address Telegram calls (the only method of the app that a stranger can call)
  outbox.py     requests are sent by a job after they are committed, never inside the stock check
  jobs.py       the queued jobs: sending, the housekeeping (retries, reminders) and the polling loop
  api.py        the buttons of the Settings page and of the Connect Telegram dialog

Telegram is off until a Munimji Manager switches it on and gives it a bot token (docs/PRIVACY.md says what then leaves the site). A person answers as themselves: the button press runs as the Frappe
user the chat is connected to, with that user's rights, so what Frappe would refuse in the Desk it refuses here.
"""
