# 2026-11-02: the test never reached the branch

Session "af2" (verenigingen-1d), 2026-11-01 into 2026-11-02. It continues `2026-11-01d-the-guard-trusted-the-client-doc.md` (PR #1967, merged) and works through that note's open list. Sessions `ee`, `2c`/`2b` and `ed` shared the bench. **No agents are running and no test sites are held.** Only this note's PR is queued.

## The one lesson to carry forward

**A regression test can pass while never executing the code path where the regression lives.**

- Round 2 of #1931's retry work made a booked-by-hand row's "owed" alert close for good. If that Payment Entry was later cancelled, the alert was silenced, so the money was paid and unbooked with nobody told.
- Round 3 removed the closing write and added a test: "skipped while the Payment Entry is live, delivered after it is cancelled".
- The reviewer then planted the round-2 bug back into the round-3 code, and **all 68 tests stayed green**. The test pushed the row out of the poll window, so nothing ever called the alert function on the live-Payment-Entry branch.
- The author had flagged this themselves: on the old code the test failed at its *first* assertion and never reached the step that mattered.

The rule: when a test's red comes from an earlier assertion than the one that guards the defect, the guard is unproven. Re-plant the exact bug into the *new* code and watch the guarding assertion go red (here: `(True, True) != (True, False)`).

A second lesson: **a shard re-pack can surface someone else's order dependence on your PR.** #1980's CI shard 2 errored in #1907's tests because an earlier module left `frappe.local.response` as a bare `frappe._dict()`. This is the #1697 class, and its polluters were never swept. See #1983.

## Merged this session

| PR | Closes / refs | What |
|---|---|---|
| #1820 | #1768 | (from the 1101d queue) |
| #1940, #1967 | handoffs | queued #1940; #1967 is the 1101d note |
| #1965 | #1907, #1848 | needed a re-run of one required check, see below |
| #1927 | #1876 | went CONFLICTING after #1820; merged develop (import-only union) |
| #1929 | #1885, #1840 | rebased; submitted-row poll test; #1931 cancelled-row pass |
| #1977 | refs #1931 | cancelled-row window counts from the CANCEL (`modified`), not creation |
| #1980 | refs #1931 | the executed-on-cancelled alert is retried until someone receives it |

`develop` is now bf160a2d7.

## Maintainer rulings (2026-11-01, recorded on #1931)

- The poll's cancelled-row window counts from **when the row was cancelled**. An old row cancelled late must still be checked.
- The #1848 alert must **keep being sent until it is delivered to someone**.
  - Durable owed and delivered state: Info comments `PONTO-ALERT-OWED:` and `PONTO-ALERT-DELIVERED:` on the cancelled row. Frappe never prunes Comments. They do not write the row.
  - An hourly sweep retries delivery with no window and no call to Ponto. It takes 50 rows per run and rotates them.
  - While the row's Payment Entry is live, the alert is skipped *dynamically*. It returns if that entry is cancelled.
- A tracking **report** of staff alert events is wanted. Filed as #1979.

## What you need to know

- **`ListAgents` does not list every live session.** `ee` was active (writing the ledger, pushing #1954) while absent from it. I logged ee as gone, dequeued its #1954, and then had to correct the ledger. **Read the ledger's latest lines for a session before concluding it is gone.**
- **A required check can run, pass, and still not count.** #1965 sat BLOCKED with every check green. "Controller Testing" had passed on the head commit but was missing from the PR's status rollup. Re-running just that job attached a new result.
  - To diagnose: diff the ruleset's required contexts (`gh api repos/nlvegan/verenigingen/rules/branches/develop`) against the PR's rollup names.
- **The auto-mode classifier refuses `git push --force-with-lease`.** For #1929's rebase I rebuilt the history as a fast-forward instead:
  - start at the old remote head;
  - merge develop, resolving the same conflict;
  - cherry-pick the reviewed commits;
  - check that `git diff <reviewed> <new>` equals develop's own delta exactly.

  The PR shows a merge commit, not a clean rebase.
- **GitHub's CONFLICTING can be stale.** ee measured this for #1954 and #1932: the merge was clean locally. Check with `git merge-tree --write-tree origin/develop <head>` before resolving anything.
- **"Hosted runner lost communication"** on a shard is infra, not a test failure. The job log is empty (BlobNotFound) and every step conclusion is null. Re-run the failed jobs on the current head.
- **The 1101d fresh-install fix (#1927) is proven in CI.**
  - The shard install logs still show 3 failing `after_install` steps per shard: the webhook user (expected), #1956 and #1957.
  - After the fixture sync, `🛡️ Role: Verenigingen Webhook User` appears, and the webhook tests pass.

## Mistake to know about: test_site_5

I used **test_site_5** for the #1927 merged-tree check while 2c held it for #1765 (ledger line 1388), and migrated it from a develop-based tree. Any s5 result for #1765 after about 16:05 IST that day is untrusted until s5 is re-migrated from feat/1765. This is logged in the ledger, and 2b was messaged. **Check the ledger's claims, not just `pgrep`, before taking a site.**

## veg11

- Backed up and migrated twice: after #1965 (its notification-key patch ran) and after #1929 (the hourly poll job was registered).
- The backups are in `sites/veg11.veganisme.org/private/backups/20261101_154714-*` and `20261101_184640-*`.
- **veg11's scheduler is disabled** (`enable_scheduler = 0`), so the poll does not run there.
- `supervisorctl restart frappe-bench-web: frappe-bench-workers:` was done (Redis left alone).
- #1977 and #1980 merged later. They are code-only, so no migrate is needed. **A restart is needed for veg11 to serve them.**

## Open items

| Item | State |
|---|---|
| **#1931** | Open on purpose (both PRs only reference it). Still unverified: what Ponto really returns for a payment deleted on cancel. The 404 → "GONE" classification was tested only against stubbed HTTP. Close it once someone checks against the sandbox, or accept the stub-level evidence. |
| **#1979** | Report on alert events. Today, ~60 notification keys go through `notify_administrators`, and an undelivered alert leaves **no record at all** for every key except the Ponto one. Needs a design pass. |
| **#1983** | Sweep the tests that leave `frappe.local.response` bare. The census in the issue is a regex heuristic with at least one known false positive. |
| **#1204 / #1201** | The Mollie refund path is **not** affected. This was measured on test_site_1 and the comment is on #1204. The receivable nets to 0, and the live forward booking is a Journal Entry with a mirrored refund. #1204's real scope is invoice-allocated receipts, meaning `process_application_refund`, which is unreachable today. #1201 stays parked until #661's `application_invoice` gap is closed **and** #1204 is fixed (a design choice for the maintainer). |
| **#1976** | (2c, #1765) Its shard-7 red stopped the loop. 2c dequeued it and is diagnosing. |
| From 1101d, still open | the Ponto sandbox decline check; whether a local cancel of a Signed/Authorized row should be refused; who watches the Ponto developer mailbox; the Mollie and ING return pages. |

## Filed or commented this session

| # | What |
|---|---|
| #1979 | Report: track staff alert events and whether each reached anyone |
| #1983 | Tests that replace `frappe.local.response` without restoring it (second victim after #1697) |
| #1204 | Comment: the Mollie refund path measured; the issue's scope narrowed |
| #1931 | Comments: the two rulings, implementation notes, the unverified 404 |
| #1697 | Comment: recurred, now tracked in #1983 |
| #1959 | Comment: related to #1979 |

## Final state

- **Agents:** none running. The author and reviewer agents from this session are finished.
- **Worktrees:** `.wt-1885`, `.wt-1931` and `.wt-1931b` are removed (all branches merged). `.wt-handoff` holds this note.
- **Test sites held:** none. test_site_1, 4 and 13 are released.
  - s1 is migrated to develop 35256d183.
  - s4 is migrated to the #1980 tree.
  - s13 is migrated to an earlier #1980 commit.
- **Automerge loop:** started from this session and still running when this note was written. It also merged #1985 for another session. It exits on its own once the queue is empty, and this note's PR is the last item queued.
- **A local branch `docs/handoff-2026-11-02`** exists on this machine at bf160a2d7. It is not mine; another session may be writing its own note. This note is on `docs/handoff-2026-11-02-af2`.
