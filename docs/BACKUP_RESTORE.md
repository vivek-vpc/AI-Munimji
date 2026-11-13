# Backing up and restoring a site that runs AI Munimji

Rehearsed on the development bench on 9 Nov 2026 (Frappe 16.55.2, ERPNext 16.54.0): demo data, one request answered and sealed, one waiting, Watch stock off.

    bench --site SOURCE backup --with-files          # into sites/SOURCE/private/backups/
    bench new-site NEW --db-root-password ROOT --admin-password ADMIN
    bench --site NEW --force restore STAMP-SOURCE-database.sql.gz --db-root-password ROOT --with-public-files STAMP-SOURCE-files.tar --with-private-files STAMP-SOURCE-private-files.tar
    bench --site NEW migrate                         # code and database in step; the job, lock rows and notification are checked again
    SITE=NEW bash dev/run-script.sh dev/scripts/check_restore.py     # development bench only: PASS or FAIL per check, then ALL OK

On the restored site: the same numbers as the source; the audit seal verifies; a waiting request can be answered and a second press is refused; the job is still stopped and Watch stock still off until a person switches it on; one job, one Scheduler Event, one notification.
Not exercised: a restore on another server, and the site's `encryption_key` (site_config.json, used for stored passwords). With Telegram off the app stores no password. With Telegram on it stores two, the bot token and a secret for Telegram's calls, in Password fields; a restore on another server needs the same `encryption_key`, or the token cannot be read and has to be entered again (and "Connect the bot" pressed again). The restore of a site with Telegram on has not been rehearsed.

If you restore a copy that you do not mean to use for real (a test site, a staging site), **switch Telegram off on it** before anything else runs: the copy holds the same bot token as the original. Two sites asking Telegram for the same bot's answers in polling mode keep interrupting each other (Telegram answers "Conflict: terminated by other getUpdates request"), a copy in polling mode removes the webhook that the original registered, and in webhook mode the site that pressed "Connect the bot" last receives the answers. Messages the copy sends appear in the real people's chats.
