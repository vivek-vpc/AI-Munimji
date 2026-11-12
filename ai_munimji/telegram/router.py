"""The engine's router over this site's links: who is sent a request, which chat belongs to whom, and who is answering."""

from ai_munimji_engine.core.approvals.models import Recipient
from ai_munimji_engine.core.approvals.router import ApprovalRouter

from ai_munimji.telegram import channel, links


class SiteRouter(ApprovalRouter):
	"""The people come from the Munimji Telegram Links, not from a list: they are read the first time they are needed (a button press needs one person, not all of them)."""

	def __init__(self, telegram_channel) -> None:
		self._people: list[Recipient] | None = None
		super().__init__({"telegram": telegram_channel}, [], "all")

	@property
	def recipients(self) -> list[Recipient]:
		if self._people is None:
			self._people = links.recipients()
		return self._people

	@recipients.setter
	def recipients(self, _value) -> None:
		pass  # the engine's constructor assigns an empty list; the people are the links

	def recipient_for(self, channel_type: str, sender: str) -> Recipient | None:
		return links.recipient_for_chat(sender) if channel_type == "telegram" else None

	@staticmethod
	def actor_for(recipient: Recipient, via: str):
		"""The person as the engine knows them: what Frappe lets them do (look, decide, change the settings), exactly as for an answer in the Desk. A press is the person's own."""
		from ai_munimji import wiring

		return wiring.actor_for(recipient.id, via=via)


def build(for_desk: bool = False) -> SiteRouter | None:
	"""The router with Telegram in it, or None while Telegram is off (the app then has no channels at all, as before)."""
	telegram_channel = channel.build_channel(for_desk)
	return SiteRouter(telegram_channel) if telegram_channel is not None else None
