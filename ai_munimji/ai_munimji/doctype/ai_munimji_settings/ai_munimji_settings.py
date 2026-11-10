# Copyright (c) 2026, AI Munimji project and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIMunimjiSettings(Document):
	def validate(self):
		# imported here: the DocType must still load (migrate, uninstall) in a bench from which the engine has been removed
		from ai_munimji import settings_map

		settings_map.validate(self)

	def onload(self):
		"""The page warns at the top while the database has innodb_snapshot_isolation ON (dbcheck.py); nothing is sent when it is OFF or cannot be read. It also says how many items the last
		stock check could not analyse (last_run.py); nothing is sent when there were none."""
		from ai_munimji import dbcheck, last_run

		if dbcheck.snapshot_isolation_is_on():
			self.set_onload("snapshot_isolation_warning", dbcheck.warning())
		skipped = last_run.unanalysed_in_last_check()
		if skipped:
			self.set_onload("unanalysed_items", skipped)

	def on_update(self):
		"""Watch stock and Check stock at are the scheduler's own switch and time: the stock check's job follows what is saved here (schedule.py). So does the daily clean-up of the logs: it
		runs while Keep logs for (days) is a positive number."""
		from ai_munimji import schedule

		schedule.sync(bool(self.enabled), self.check_cron)
		schedule.sync_clean_up(self.keep_logs_days)
