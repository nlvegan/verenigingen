# 2026-09-23b: green here was not green there

This session started from the unmerged 2026-09-23 handoff (PR #1319, still open). The maintainer
ruled on the four decisions it listed. Nine issue units then went to sonnet authors in a rolling
pool of four, and three more agents were dispatched for problems CI surfaced along the way. Every
PR got an independent `skeptical-code-reviewer`, and every answering round got its own narrow
re-review or a coordinator check. **Ten PRs merged**, each pinned with `--match-head-commit` to the
approved SHA after full green CI and a pre-merge check against the then-current develop. 24 issues
were filed.

The headline is not the fixes. Most of the blocking findings this session came from **the gap
between this bench and CI, or between the fixture and production**: a check that passed here and
failed there, or the reverse. The 2026-09-23 handoff's rule ("what state does production have
that the fixture lacks") caught two of them. The rest needed a sibling question: **what does the
CI runner have or lack that this bench does not?**

## Decisions made by the maintainer (all recorded on their issues)

| Issue | Decision |
|---|---|
| #1101 | Staff MAY act on a member's behalf. "Staff" = `Roles.ADMIN_ROLES` (System Manager, Verenigingen Administrator, Verenigingen Staff) "for now". Board and treasurer roles are excluded. |
| #1267 | Uniqueness per `(bank_account, reference_number)`, **amended mid-session** to apply to system-issued references only (Mollie `tr_`/`stl_`/`baltr_`, Ponto, e-Boekhouden `EB-`). MT940, manual and payer references are unconstrained. |
| #1288 | Change both: Paid only after the Payment Entry succeeds, and stop swallowing the PE error. |
| #1306 | Anonymise instead of deleting. Goods/services invoices are never auto-deleted, and dues debt is not pursued. After three rounds, **option C**: keep anonymising and fix the test harness's delete order. |

## What shipped

| PR | Issue(s) | What it does | Rounds |
|---|---|---|---|
| #1324 | #1277 | 8 LIKE patterns on external identifiers escaped, each with its own red/green | 1 |
| #1331 | #1311 | order-dependence scanner walks `tests/` helper modules and flags unscoped `get_value` in setUp (1270 -> 1349 findings, 0 removed) | 1 |
| #1322 | #1101 | staff may cancel a member's subscription (4 of 5 sites turned out to be session-resolved no-ops, see #1321) | 2 |
| #1345 | #1307 | `super()` restored in 3 test classes, plus an AST ratchet over ~2972 harness classes | 1 |
| #1326 | #1288 | installment Paid only after the PE, inside a savepoint; the PE error propagates to the webhook | 2 |
| #1340 | #1267 | re-runnable v2_2 patch plus a Custom Field **fixture**; MT940 swallow removed; dead duplicate-key recovery revived | 2 |
| #1335 | #1314 | get_doc-before-permission existence oracles closed in payment_dashboard / manage_donations | 3 |
| #1351 | #1350 | a test leaked `max_statement_time=1` through the shard's DB connection | 1 |
| #1333 | #1088, #1093 | ownership check on 6 member-money endpoints (staff allowed); shared probe mixin | 2 |
| #1327 | #1306 | read-only pre-pass, then anonymise; the harness defers a blocked Member until its invoices are released | 5 |

Closing-keyword gaps: #1324 and #1331 had no `Closes`, so #1277 and #1311 were closed by hand.

## The pattern: green here was not green there

| PR | Passed where | Failed where | Why |
|---|---|---|---|
| #1340 r1 | the author's sites (patch run via migrate) | every fresh site, including CI | **`install_app()` marks every patch in patches.txt as done WITHOUT running it.** A Custom Field created only by a patch never exists on a new site. Ship it as a fixture too (as #809 already did). |
| #1335 r3 | locally: wkhtmltopdf fails fast (`HostNotFoundError`) | CI: the whole shard hung until the 60-minute cancel | the receipt test reached a real PDF render, and wkhtmltopdf fetched assets from the fake `http://test_site_N` host. Stub `frappe.utils.pdf.get_pdf` only. |
| #1333 | locally, run alone | CI shard 2, deterministically, 3 times | `get_open_count` runs `SET SESSION max_statement_time = 1` and never resets it. One shard is one DB connection, so a lock test 81 modules later got MariaDB **1969** instead of 1205. Shard re-packing from new test files exposed it. |
| #1327 r3 | CI (no RQ workers) | this bench: `FOR UPDATE NOWAIT` "being modified by another user" | **this dev box runs live RQ workers.** The invoice submit enqueues `payment_history_update_<member>` after commit, and a worker locks the Member row within ~10ms. It cannot happen in CI. This also explains #1137 and #1233, which had marked this lock holder "unidentified". |
| #1326 | author and reviewer: "no growth, byte-identical" | CI "Baseline is in sync with the tree" | both had compared counts. A `COMMIT_EXEMPT` entry does not grow the gate, but it must still be **recorded** in the regenerated file. |

And the fixture-versus-production gap, the previous handoff's rule, caught these:

| PR | Fixture had | Production has |
|---|---|---|
| #1335 r1 | every test invoice had `member` set | **3009 of 3471** Sales Invoices on veg11 have `member IS NULL`. Staff got a false "Invoice not found". |
| #1340 r1 | system-shaped references only | MT940 payer end-to-end references repeat on one account (a member paying monthly with the same reference). The second one was **silently dropped** by an existing `contextlib.suppress(UniqueValidationError)`. |

**Suggested rule:** for any change touching install, patches, fixtures, background jobs, external
binaries or DB session state, ask "what does CI's runner have or lack that this bench does not?"
Known differences, all measured this session:
- CI has no RQ workers; this bench does.
- CI sites are fresh installs, so patches are not run.
- CI has no reachable site host, so wkhtmltopdf hangs there.
- A CI shard is one process and one connection for about 116 modules.
- CI has no gateway credentials (known before).

## The second pattern: a test that passes for the wrong reason

- **#1322 r1:** the control test "an ordinary member cannot act on another member" used a plain
  `Verenigingen Member` user. `@high_security_api` refused that user before the ownership check
  ever ran. The reviewer mutated the ownership comparison to `if False:` and the test stayed
  green. The fix is an attacker that clears the tier gate but holds no admin role (a Chapter Board
  Member), plus asserting the ownership *message*. Every later brief carried this, and #1333 and
  #1335 got it right first time.
- **#1327 r2:** to satisfy the leak ratchet, the harness was taught not to count an anonymised
  Member, whose row still survived the test, committed. The review caught it as silencing. The
  real fix (r4) keeps the ratchet intact and changes the drain order.

## Gates and instruments

- **Harness-logger census (push-only).** #1327 r4 added one below-ERROR teardown warning (14 -> 15).
  The reviewer ruled that WARNING is correct: losing it is inside `harness_logger.py`'s documented
  residual limit, because the leak ratchet already surfaces the real failure. The baseline was
  regenerated and the prose moved from 18/22 to 19/23. That paragraph still says "three ERROR
  sites" where the constant is 4 (stale since #1154, noted on #1327, not fixed).
- **After #1331 merged**, every later PR got a local pre-merge check: merge the PR head with the
  current develop, regenerate the baseline, run the super-skip validator. None tripped, but
  #1326, #1327 and #1331 all touched the same baseline file.
- **Cancelled runs leave a red "Test Summary".** Check `gh run view` for `cancelled` before
  diagnosing. #1333's tests never ran on one head, and a 504 from `gh pr merge` hid a successful
  merge (#1345). Verify with `gh pr view --json state`.

## Coordinator mistakes (so they are not repeated)

- I resumed the #1101 author for a fix round without reassigning its site. It ran on test_site_2
  while the #1088 author owned it. An answering round needs a free site too.
- I asked the reviewer to scrutinise #1326's `_create*` exempt commits as possible gaming. The
  measured leak count was zero. The exemption is keyed on the name, but this use was honest.
- The CI monitor re-emits every PR's state on each re-arm. Mute parked PRs from the watch list,
  don't re-diagnose.

## Not done

- **veg11:** the delete of the 10 leaked `REF123` Bank Transactions was refused by the permission
  classifier. They no longer block migrate under the narrowed rule. A backup was taken
  (`20260923_155819-veg11_veganisme_org-database.sql.gz`), and the maintainer can run the prepared
  script. veg11 also still needs a `bench --site veg11.veganisme.org migrate` for #1340's patch and
  fixture.
- 4 agent worktrees with untracked scratch files remain (issue-1101/1277/1288/1311). Their branches
  are merged.
- PR #1319 (the previous handoff) is still open.

## Filed this session

#1320, #1321, #1323, #1325, #1328, #1329, #1330, #1332, #1334, #1336, #1337, #1338, #1339, #1341,
#1342, #1343, #1344, #1346, #1347, #1348, #1349, #1350 (fixed by #1351), #1352, #1353.

Highest value:
- **#1330:** a permanent PE failure leaves a paid installment Pending, with no alert after gateway retries end.
- **#1353:** the harness never resets MariaDB session variables between modules; #1350 was one instance.
- **#1328:** `validate_member_ownership` itself is an existence oracle (about 12 call sites).
- **#1336:** 6 more `secure_document_operation` sites swallow IntegrityError.
- **#1321:** 4 "staff may act" endpoints take no target member, so staff cannot use them at all.
- **#1352:** `BaseHistoryManager` swallows a 1969 statement timeout. Dormant unless `enable_db_statement_timeout` is set.
