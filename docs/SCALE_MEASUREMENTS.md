# Measured at scale

What the stock check, the audit sweep, the clean-up and the ERP client cost on a large site, before and after the fixes of the production-readiness review (11 Nov 2026), and what a crowd of approvers does
to the app. Nothing here is a promise about your site: the numbers are what these scripts measured on one laptop's Docker (8 vCPUs, 11.8 GB, MariaDB 11.8 with a 2 GB buffer pool,
`innodb_snapshot_isolation` OFF, `innodb_lock_wait_timeout` 50 s), and the tools to measure your own are in `dev/README.md` ("Measuring at scale").

**The site:** 30,000 stock items, one Bin each, a stock ledger of 5,310,003 entries (167 movements per item, three hot items with 100,000 more each), Frappe 16.55.2, ERPNext 16.54.0. About one item in 20 is nearly
out of stock and one in 20 is low, so each run has far more candidates than the 20 requests a run may raise (`max_alerts_per_run`). "Before" is the app as committed at `3da6963` and the engine 0.1.1; "after" is this branch.

## The stock check (finding A1)

Measured by `dev/scripts/measure_stock_check.py`: one full run; the longest time one transaction of the run held row locks (read from the database's transaction list every 0.1 s); and what 20 people see who answer
the 20 requests the run is replacing, one every 0.1 s, as soon as the run has begun to replace them.

| | items | run time | peak memory | longest lock held | the 20 answers |
|---|---|---|---|---|---|
| before | 5,000 | 112 s | 321 MB | 111.8 s (the whole run) | 12 waited 45.7 to 47.4 s and were told "busy"; 3 failed with a deadlock; 5 went through |
| before | 30,000 | 561 s | 1,324 MB | 560.6 s (the whole run) | 12 waited the database's whole lock wait (50 s) and failed; 3 failed with a deadlock; 5 went through |
| batches of 200 items only | 5,000 | 139 s | 165 MB | 5.2 s | median 3.9 s, slowest 4.9 s, 18 of 20 over 2 s |
| batches of 200 items only | 30,000 | 570 s | 334 MB | 3.3 s | median 1.6 s, slowest 3.0 s, 7 of 20 over 2 s |
| **batches of 200 items or half a second, requests first** | 5,000 | 84 s | 162 MB | **0.7 s** | **median 0.04 s, slowest 0.34 s, none over 2 s**: 7 answered, 10 were told the request had been replaced, 3 "busy", no deadlock |
| the same | 30,000 | 508 s | 334 MB | **0.6 s** | **median 0.14 s, slowest 1.17 s, none over 2 s**: 10 answered, 8 were told the request had been replaced, 2 "busy", no deadlock |
| the same, and the people **approve** (re-reading the item and making a work order) | 5,000 | 100 s | 169 MB | 1.7 s | **median 0.6 s, slowest 1.4 s, none over 2 s**: 16 approved, 4 "busy" |

What the three changes did, in the order they were made. **Batches of 200 items**, each committed, took the lock from the length of the run to 3 to 5 seconds and the memory down to a quarter, but a batch that raises
20 requests takes about 5 seconds, and a person answering one of them still waited for it. **Ending a batch after a second** (only the stages that write; reading and analysing hold no lock and are cut by
the count) took the wait to a second or two, and **half a second** brought the slowest answer at 30,000 items from 2.3 s to 1.2 s. **Taking a request's row before its alert's**, in the order a person's answer takes them, removed the deadlocks that the first two left (3 of 20 became 1 of 20, and then none: the
database can still pick one of two transactions that meet on an index, and the answer then says "busy" and changes nothing). A "busy" here means the person pressed within the second in which the run replaced
the very request they were answering; reloading shows the replacement. What a run costs in time has not changed much: at 5,000 items 40 of the 114 seconds are the engine working out each item's settings (three reads
each) and 39 are the engine looking, for each item, for an alert or a stock alert that is open (two reads each); they are the next thing to speed up, and nothing here does.

## The stock ledger (finding A2)

Measured by `dev/scripts/measure_ledger_reads.py`, each measurement in its own process (so that peak memory is its own), the database cold or warm as the row says.

| what is read | before | after |
|---|---|---|
| `list_items()`, 30,003 items, first run (the first movements not known yet) | 39 s (64 s the first time, with ERPNext's renaming job running) | 89 s, once: 176 queries of 200 items each |
| `list_items()`, every run after | 17.7 to 64 s: a GROUP BY over all 5.3 million entries, every time | **2.3 s**, 2 queries, 30,005 rows |
| one item (what answering a reorder request costs) | 17.7 s, 35,008 rows | **0.6 s**, 3 rows |
| `get_consumption`, 30,000 items, one movement per item and day | 86 s, 4,620,002 rows, 601 queries | 93 s, 4,320,980 rows, 601 queries |
| `get_consumption`, three hot items of 100,000 movements each | 7.5 s, 225 MB, **300,434 rows** | 4.1 s, 80 MB, **1,412 rows** |

What this says. The cost of the first-movement lookup used to be paid on every run and on every answer to a reorder request; it is now paid once per item, and an item created more than 1,100 days ago (longer than any
history the rules read) is not looked up at all. The cost of the usage read no longer grows with the number of movements: the database adds up each item's movements of a day, so a hot item of 100,000 movements
is 470 rows (one per day), not 100,000. **When every movement is on a day of its own, as in the uniform part of this seed, there is nothing to add up, and the read costs what it did.** The first
try at it used 200 items per query and cost twice as much on that data (183 s): the database adds up a chunk in a temporary table, and measured chunks of 200 are two to three times dearer per item than
chunks of 50, so the client asks for 50. The 785 MB peak of the 30,000-item read is the measuring script holding every item's days; a run holds one batch's at a time.

## The audit sweep (finding A3)

Measured by `dev/scripts/seed_audit.py` and `measure_audit_sweep.py`: 200,000 closed requests, every one sealed in a valid chain, then a sweep with nothing new to seal.

| | time | rows fetched into Python | queries | peak memory |
|---|---|---|---|---|
| before | 8.1 to 11.5 s | 400,001 (every sealed id and every closed request) | 5 to 6 | 248 MB |
| after | 0.21 s the first time, **0.01 s** after | **1 to 3** | 4 (17 the first time, which reads the DocType's description) | 84 MB |

The patch that flags the requests a site had already sealed (`ai_munimji.patches.mark_the_sealed_records`) flagged all 200,000 inside a `bench migrate` of 81 seconds in all.

## The clean-up of the logs (finding A4)

Measured by `dev/scripts/measure_retention.py`: tool calls older than the retention period.

| | records | time | |
|---|---|---|---|
| before | 3,000 | 124.8 s, in one transaction: 41.6 ms a record | a backlog of 150,000 is 104 minutes in one transaction, past the 25 minutes a "Daily Long" job is allowed, and rolled back every day |
| after, batches of 500, cap 5,000 | 150,000 | the first run removed 1,000 in 31 s, then **Frappe refused with "Too many queued background jobs (700)"** | every deletion queues a background job (`delete_dynamic_links`) and the bench's one worker takes them more slowly than they are queued; the clean-up now looks at the queue first (below) |
| after, batches of 100, waits for the workers | 150,000 | run 1: 600 removed in 71 s; run 2: 100 in 36 s; each ended cleanly, saying how many tables it had left | the rate is the worker's, not the database's: one worker takes about as many jobs a second as the clean-up deletes records, and the queue holds 500 |

What this says. The cost of a deletion (42 ms) is Frappe's, not the app's: one document read and locked, its `on_trash`, its removal, and one queued job. The old clean-up spent it 150,000 times in one transaction. The new
one spends it at most 5,000 times a run, commits every 100, and does not push more jobs into Frappe's queue than Frappe allows. On this bench, with one worker, that is a few hundred records a run, and a backlog
of 150,000 would take months to clear; on a site whose workers keep up, a run removes its 5,000. The daily volume of a site that has been cleaned from the start is a few hundred records, which any of this handles. If a
site really does start with a backlog of hundreds of thousands, a single `DELETE` per batch would clear it in minutes, and the way to allow it is to give `retention.py` that one exception to the rule that the app writes through the stores
(`tests/test_rules.py`); it is not done, and it is yours to decide.

## What a crowd of approvers does (finding A5)

Measured by `dev/loadtest.py` over HTTP, against the app served by 8 gunicorn workers (`gunicorn -w 8 -t 300 --preload frappe.app:application`, the way `bench` serves a production site; the development server is
a single process and would measure itself), the same 30,000-item site, and 100 users who are Munimji Approvers with the roles that make a draft Purchase Order. Each calls the URLs the Desk calls, with the user's own API key.
Before the test each of 110 requests was a purchase request waiting for an answer.

| | what happened | answered how | p50 | p95 | slowest | duplicates | lost answers |
|---|---|---|---|---|---|---|---|
| **a** 100 approvals of 100 different requests, at the same moment | 97 draft orders made | 97 approved, **3 "busy"** | **25.1 s** | **40.3 s** | 42.1 s | 0 | 0 |
| **b** 20 presses on the same request, at the same moment | 1 draft order | 1 approved, 12 told who answered first, **7 "busy"** | 0.47 s | 0.50 s | 0.51 s | 0 | 0 |
| **c** 100 people open the list and a request form (200 page loads), while a stock check of the 30,000 items runs | all 200 pages | 200 ok, no "busy" | 1.21 s | 1.53 s | 1.94 s | not applicable | not applicable |

**Duplicates and lost answers: none.** Every request that was told "approved" has one draft order and is decided in the database; the 20 presses on one request made one order. **Scenario a does not meet the bar the
brief set (no "busy", p95 under 10 s).** One approval alone takes 0.25 to 0.39 s (five measured one at a time); the 97 took 42 s in all, about 2.3 a second, which is what one at a time looks like. That is the one lock
that is taken for the making of any Purchase Order, from the moment a press reaches it until its request ends (`stores/locks.py`, `take`): it is what makes two presses of one button make one order, and it makes all
approvals take turns. The three "busy" are deadlocks on the primary key of the Approval Request table (the last one the database recorded: one transaction inserting the request that follows a new order, another holding a gap
lock there); the answer says "busy" and changes nothing, and pressing again works. Waiting for the lock did not reach the database's 50 seconds (the slowest took 42).

What would change it, smallest first (nothing here is done; this is waiting for your go):

1. **Retry a deadlock inside the request** (`api.answer`: roll back and decide again, up to three times, a fraction of a second apart). It removes the "busy" of a deadlock and costs a few lines and a test. It does not shorten
   the queue: at 0.4 s an approval, p95 stays under 10 s up to about 25 approvals at the same moment (an estimate from the measured time per approval, not a measurement).
2. **Take the lock per reference instead of per document type** (a fixed number of lock rows, chosen by a hash of the reference: the same reference always meets the same row, so two presses of one request still make one
   order, and different requests mostly do not meet). The reason the lock is per type today is written in `locks.py`: the locking read that looks for an existing order takes a gap lock, and two different references then
   deadlock inserting into the same gap, so that read would have to go (the request's own row, which `decide` locks, may already be enough to make a second press of one request wait and then see it decided: scenario b is consistent with that, and it would have to be proved before the read is removed). It is a change to the
   one piece of code that was written to be safe under concurrency, so it needs the parallel-presses tests (`tests/world/test_parallel_presses.py`) run at 100, and a day.
3. **A unique index on `custom_agent_ref`** of Purchase Order, Material Request and Stock Entry, so that the database refuses a second order for a reference. No lock at all, but it changes ERPNext's tables, has to meet
   a cancelled order that keeps its reference (a new order for the same request after a cancel would be refused), and cannot be added to a site that already has two orders with one reference.

My recommendation is 1 now, and 2 if you expect bursts of more than a few dozen approvals at one moment, which an inventory approval flow does not usually have.
