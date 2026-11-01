# 2026-11-01d: the guard trusted the client's doc

Session "af" (2026-11-01). This session continues "aanmeldformulier" (handoff PR #1940, still open), picking up its
open list. It shared the bench with sessions `ee` and `2c`, and ee's `automerge.sh` loop was running throughout.

**The one lesson to carry forward.** #1907 round 3 guarded the money-path fields of a submitted Ponto row with a flag
that "only system code" sets. The guard returned early whenever the flag was on. But `refresh_status` is whitelisted,
and `frappe.handler.run_doc_method` builds `self` from the **client's** JSON, not from the database. So a decorator
that set the flag around the whole method saved the client's tampered `payment_entry` with system authority. The
reviewer reproduced it as a Treasurer and as a Verenigingen Administrator (#1965, finding F1). The rule: **a
whitelisted doc method that elevates trust must re-read the row from the database first** (`as_system_update_from_db`).

A second lesson came from #1927: a fallback can hide an install that has been broken all along (see below).

## State at handoff (nothing of this session's has merged yet)

| PR | Closes | Head | State |
|---|---|---|---|
| **#1820** | #1768, #1769 | b36d71c09 | Queued in `automerge.sh`. Shard 1 was INFRA (the apt mirror was unreachable, no test ran). I re-ran the failed jobs of head run 41248869680, and that shard was still running at handoff. No other failure. |
| **#1927** | #1876 | 85d701843 | Queued. Fix round done (see below), coordinator-checked. CI on the new head was still running, with no failures so far. |
| **#1965** | #1907, #1848 | 3d105ef94 | Queued. Round 4 (6b6a44142) passed independent review with nits. 3d105ef94 is a merge of develop that only resolves a `patches.txt` conflict, keeping both lines. CI was still running. |
| **#1929** | #1885, #1840 | d889f3933 | **Not started.** Rebase only AFTER #1965 merges (recipe below). |
| #1838, #1896 | #1815; #1833, #1834, #1883 | unchanged | Still HELD on the Ponto sandbox check (open question 1 in the #1940 handoff). |
| #1940 | (handoff) | | The previous session's handoff PR is still open and **not queued**. Queue it, or merge it with this one. |

`approved_prs.txt` at handoff: `1944 1949 1951 1952 1955 1820 1927 1966 1965` (ee's PRs plus mine). A background
watcher in this session was waiting for #1965 to merge. It dies with the session, so the next session checks
`gh pr view 1965` itself.

## #1927: the webhook user never existed on a fresh install (pre-existing, unmasked)

CI on 29984d39b had 22 new failures across 5 shards. All were webhook or service-user tests, and the cause was
`Verenigingen Payments Settings.webhook_user` being unset.

- Frappe's `install_app` runs `after_install` (`frappe/installer.py:374`) BEFORE `sync_fixtures` (`:381`), and runs
  `after_sync` (`:385`) after it. The webhook user's Role Profile ships as a fixture, so the `after_install` step
  fails with "Role Profile Verenigingen Webhook User not found". The user is created without roles and the setting
  stays unset.
- CI does `reinstall` plus `install-app` and never migrates (`.github/actions/setup/action.yml:423-440`), so the
  `after_migrate` repair never runs there.
- **This failure is in every develop CI install log too** (e.g. job 124704772734 of #1929). It was invisible while
  `get_service_user` fell back to Administrator. #1927 removed that fallback, as the maintainer ruled, and that
  exposed it.
- Fix in 85d701843: `after_sync = ["verenigingen.setup.webhook_user_setup.ensure_webhook_user"]`, with `after_migrate`
  kept. The new test `test_a_fresh_install_converges_through_the_after_sync_hooks` goes red when the hook is removed.
- With `webhook_user` blanked on test_site_2, the author reproduced the same failures as CI in every module, and they
  went green with the user set.
- **Not done:** a real fresh-site install. The bench has no `MARIADB_ROOT_PASSWORD`, so the author could not create a
  throwaway site. The install order was read from source, not run. CI on 85d701843 is the real proof, so check it
  before trusting the fix.
- Siblings filed: **#1956** (other `after_install` steps need fixture rows, such as membership types needing
  "Verenigingen Member") and **#1957** (the public document creator fails on a fresh install with a `company`
  mandatory error; not reproduced locally).

## #1965 (#1907 + #1848): review rounds 3 and 4

- **Round 3 review of 5701d695c: CHANGES REQUIRED.**
  - F1 (HIGH): the `run_doc_method` bypass described above.
  - F2: Administrator was a computed recipient of the alert, because the patch's roles match it. Delivery failed only
    by accident (an email passed as `for_user`), leaving one Error Log row per alert.
  - F3: the row lock was untested, because the threads were staggered by 1 s.
  - F4: an unseeded notification key dropped the alert silently.
- **Round 4, 6b6a44142:**
  - `as_system_update_from_db` reloads before setting the flag, on both `refresh_status` methods.
  - `notify_administrators(exclude_users=["Administrator"])` excludes by user name and by that user's email.
  - A barrier-synchronised concurrency test: the lock-removal mutant now gets a 1213 deadlock.
  - A distinct Error Log row, "…NOT DELIVERED to anyone", when nobody was notified.
- **Delta review: APPROVE WITH NITS.**
  - The reviewer re-ran the bypass for both doctypes: closed.
  - `savedocs`, `frappe.client.save` and `frappe.client.set_value` are all refused, and a client cannot inject `flags`.
  - Only the two `refresh_status` methods among the `as_system_update` users are whitelisted.
  - Nits, deferred: no direct unit test for `exclude_users` (the alert test covers it and reddens on both mutants);
    the email match also drops a real person who shares Administrator's mailbox (noted on #1960); the NOT DELIVERED row
    repeats while the key is unseeded (intended).
- Filed by the round-4 author:
  - **#1958**: `create_system_notification` passes an email as `for_user`.
  - **#1959**: notification registry keys are never seeded on a fresh install.
  - **#1960**: the general recipient helper includes Administrator for every key.
- **veg11:** #1965 adds `allow_on_submit` in JSON plus a patch, and #1851 (merged earlier) adds a Select option. Run
  `bench --site veg11.veganisme.org migrate` before the next deploy check.

## #1929 rebase recipe (after #1965 merges)

1. Rebase onto develop. The known conflict is in `ponto_payment_link.py` `refresh_status`: keep #1929's
   `new_status = map_link_status(...) or self.status`, then re-add #1907's two `alert_executed_on_cancelled_row` lines.
2. **New since the #1940 handoff:** `refresh_status` is now wrapped by `as_system_update_from_db`, which reloads the
   row. Check that the poll calls `refresh_status` on a row it has not modified in memory first (the reviewer grepped
   the callers that existed then and found none that did, but the poll is new). Its writes must go through the system
   flag, not around it.
3. Add a poll test on a REALLY submitted row (rule 22), stubbing only the HTTP client below `with_retry` (rule 17).
4. Implement #1931 (ruled yes): the poll also checks rows cancelled within its window, only to detect Executed and
   raise the #1848 alert.
5. Independent review of the new commit before pushing.

## Coordinator notes

- **The fix-round brief for #1907 told the author to push.** I corrected it by message before the commit existed
  ("commit locally, do not push") and pushed only after the delta review. The rule in `~/frappe-bench/CLAUDE.md`
  ("is code about to become visible?") applies to round briefs too, not only first dispatches.
- **A PR can turn CONFLICTING the moment it is opened** when its branch is behind develop. Check
  `gh pr view N --json mergeable` before queueing. For a conflict that keeps both sides, merge develop (do not rebase:
  that changes the reviewed SHA), then regenerate the order-dependence and clone-family baselines and run the affected
  modules on the merged tree. Done here on test_site_4 (migrated first).
- **Read the whole failing shard log, not the first ERROR line.** Every #1927 shard printed pip `ResolutionImpossible`
  noise first. That noise is harmless and also appears on green runs. The real signal was the
  "introduces test failures not in the baseline" block, and the install log's "Install step failed".
- Sites used this session: s13 for both reviews, s2 for the #1927 author, s4 for the #1907 author and the merged-tree
  check. All are released. **test_site_2's** `webhook_user` was blanked and restored, and a backup sits at
  `sites/test_site_2/private/backups/20261101_125145-*`. **test_site_4** is migrated to the #1965 merged tree.

## Filed this session

| # | What |
|---|---|
| #1956 | `after_install` steps that need fixture rows fail on a fresh install (membership types, etc.) |
| #1957 | the public document creator setup fails on a fresh install (`company` mandatory on Verenigingen Settings) |
| #1958 | `create_system_notification` passes an email as `for_user` (a Link to User) |
| #1959 | notification registry keys are never seeded on a fresh install, so alerts are skipped |
| #1960 | the role-based recipient helper includes Administrator for every key (comment added: email-match caveat) |

## Final state

- **Agents:** none running. Worktrees: `.wt-1876` and `.wt-1907` are clean. The review and merge worktrees are
  removed.
- **Test sites held:** none.
- **Open for the maintainer** (carried over from #1940, all still unanswered): the Ponto sandbox decline check; whether
  a local cancel of a Signed or Authorized Ponto row should be refused; who watches the Ponto developer mailbox; the
  Mollie and ING return pages.
