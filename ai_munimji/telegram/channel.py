"""The engine's Telegram channel, given what a Frappe site supplies: the transport, the memory in the cache, and this app's words."""

from ai_munimji_engine.core.approvals.channels.telegram import TelegramChannel

from ai_munimji.telegram import config, memory, transport

PRODUCT = "AI Munimji"
BOT_DESCRIPTION = "the AI Munimji bot for ERPNext stock and purchases"
KNOWN_HELP = (
	"Requests that need your answer arrive here with buttons: tap one to answer. Nothing is ordered until someone approves it; the purchase request that follows an approved reorder arrives here too.\n"
	"On an order request you can tap Change quantity or Change vendor and type your answer here, or reply to the request with a number to change its quantity.\n"
	"To stop getting requests here, disconnect Telegram in AI Munimji."
)
SHORT_CALL_SECONDS = 5  # the calls a Desk answer makes to tidy up the chat (remove the buttons, show the outcome): a person is waiting for the page


def build_channel(for_desk: bool = False) -> TelegramChannel | None:
	"""The channel, or None while Telegram is off or has no token. `for_desk`: made for an answer given in the Desk, whose tidying-up calls must not keep the person waiting."""
	if not config.enabled():
		return None
	return TelegramChannel(
		config.token(),
		webhook_secret=config.webhook_secret() or None,
		mode=config.mode(),
		http=transport.Http(),
		api_base=config.api_base(),
		product=PRODUCT,
		bot_description=BOT_DESCRIPTION,
		known_help=KNOWN_HELP,
		throttle=memory.CacheThrottle(),
		offset=memory.CacheOffset(),
		timeout_for=(lambda method: SHORT_CALL_SECONDS) if for_desk else None,
	)
