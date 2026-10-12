# 2026-09-26: an unknown record must look exactly like a forbidden one

This session started from the 2026-09-23b handoff.
- **Staffing.** Issue units went to sonnet authors: first eight at once, then a rolling pool. The maintainer changed the pool cap several times (6, then 3, then 6, then 4 including reviewers).
- **Review.** Every commit got an independent `skeptical-code-reviewer` **before** it was pushed. Every answering round got a narrow re-review or a coordinator check: a mutation run against the pushed head.
- **Merging.** PRs merged after full green CI and a local pre-merge check against the then-current develop:
  - order-dependence regeneration;
  - the super-skip, duplicate-helper, log_error-order and harness-census gates.

  Each merge was pinned with `--match-head-commit` to the reviewed SHA by `automerge.sh`.
- **Framework.** Mid-session the bench moved to **frappe v16.35.0 / erpnext v16.36.0 / hrms + payments `version-16`**, matching what CI installs.

The headline class is **existence oracles**. About a dozen endpoints answered "not found" for an unknown record and "not permitted" for a forbidden one. The fixes kept finding a second channel that still told the two apart:
- the `message_log` (`_server_messages`);
- the query count;
- the synthesized response shape;
- the Error Log.

The same bug sits in **Frappe core**. A report is drafted but not sent (see below).

## Decisions made by the maintainer (recorded on their issues)

| Issue / PR | Decision |
|---|---|
| #1329 | Chapter Board Members see only their own chapter(s). |
| #1356 | The coordinator dropped the name-matching tier (recorded on the issue). |
| #1363 / #1395 | Delete `verenigingen/fixes/` instead of reviving it. Reviving it would have re-enabled an invoice-submitting dev tool on veg11 (`developer_mode=1`). PR #1409 was closed as superseded by #1422. |
| #1430 | Override `frappe.client.has_permission` / `get_doc_permissions` locally via `override_whitelisted_methods`, and draft an upstream report after verifying it ourselves. |
| #1435 | Confirmed there is no post-submit configuration flow, so refusing a misconfigured Ponto Payment Request at submit is safe. |
| merge policy | Merge when reviewed and fully green, pinned to the head commit, after a pre-merge check against current develop. |
| bench | Upgrade frappe, erpnext and the other apps to the latest v16 ("we're building for v16"). |

## What shipped

36 PRs, all reviewed before push.

| PR | Closes | What | Notable review finding |
|---|---|---|---|
| #1364 | #1320 | escape LIKE wildcards in Mollie consumer_name member match | |
| #1368 | #1352 | raise MariaDB 1969 (statement timeout) instead of swallowing it | |
| #1369 | #1336 | revive dead duplicate-key recovery in 2 of 6 `secure_document_operation` sites | |
| #1370 | #1334 | existence oracle in `update_member_mollie_fields` | code OK, the prose claimed User Permission scoping production does not use (#1366, #1367 filed) |
| #1371 | #1353 | reset MariaDB session variables between harness classes | asked to also reset at setUpClass **start**, so the first class after a non-harness leaker starts clean |
| #1374 | #1344, #1347 | re-point `self.factory` after `super().setUp()` | the regression test exercised its own copy of the fix |
| #1375 | #1328 | `validate_member_ownership()` existence oracle | 2 existing tests edited (DoesNotExist -> Permission), justified |
| #1377 | (#1329, closed by hand) | scope `get_mandate_issues` to own chapter(s) | maintainer decision on scope |
| #1381 | #1358 | existence oracle in `initiate_installment_payment` | |
| #1383 | #1323 | Ponto Payment Request Executed only after the PE | early returns committed Executed with no PE; CI red on the harness census constant (coordinator fix) |
| #1385 | #1346 | stop stranding an invoice via a NULL posting_date | |
| #1388 | #1373 | existence oracle in the `payment_plan_pay` page | |
| #1391 | #1343 | TestSEPAReconciliation tearDown orphaning GL Entries | |
| #1392 | #1356 | linked donor by link/exact fields, not unescaped LIKE | tier fall-through leak; 4 mocked tests defeated; name tier dropped |
| #1397 | #1382 | the derivation-error test now reaches its `except` branch | |
| #1405 | #1386 | team-existence oracle on the team_members page | |
| #1407 | #1376 | escape LIKE in `check_similar_customers` | |
| #1412 | #1378 | spurious Customer/Address leak from the tracked drain | |
| #1416 | #1401 | team_management raise-vs-False oracle | `clear_last_message()` was not enough; the fix trims `message_log` to its pre-call length |
| #1418 | #1404 | `force_unique_name` no longer guarantees a collision | the 8/8 repro was not replicated; reframed |
| #1419 | #1387 | purge ledger rows in about 26 cancel-then-delete cleanup sites, plus a gating invariant | |
| #1422 | #1363, #1395 | delete `verenigingen/fixes/` plus a patch removing 3 Critical Operation Rule rows | the first cut missed a 3rd COR row |
| #1423 | #1384, #1389 | refuse an ambiguous Donor-by-email/link match | missing `Donor.member` tier; `matching_donors` leaked other donors' names; 3 rounds |
| #1424 | #1394 | `can_review_application` existence oracle | |
| #1425 | #1400 | read `check_donor_exists`'s nested envelope in JS | |
| #1427 | #1393 | single-day Daily coverage | |
| #1428 | #1402, #1426 | equal query cost for unknown vs foreign team | NULL-parent sentinel |
| #1432 | #1417 | remap 14 invalid `log_security_event()` event types | the ratchet extension was coordinator-accepted |
| #1433 | #1372 | wire the super-skip and factory-shadow validators into CI | |
| #1435 | #1379 | refuse a misconfigured Ponto Payment Request at submit, before money moves | maintainer confirmed no post-submit config flow |
| #1436 | #1430 | local override of the Frappe core existence oracle | 3 rounds; see the pattern section |
| #1437 | #1362 | Ponto Payment Link status only after the PE; shared `atomic_status_transition` | callers swallowing; an unscoped PermissionError no-op; stacked on #1435 |
| #1444 | #1380 | annotate `initiate_installment_payment` params (dict plan refused at dispatch) | harm confirmed over HTTP as own-data-only |
| #1445 | #1286 | EUR guard on `validate_sepa_eligibility` | failed open on a blank currency (#1442 for the 2 siblings) |
| #1446 | #1296 | board-history permission refusal is no longer swallowed into `[]` | |
| #1447 | #1359 | root Cost Center create path works (ERPNext parity) | the non-duplicate control could not fail; CI red on the clone-family baseline (coordinator fix) |

PR #1409 (#1363's LIKE fix) was closed as superseded by #1422.

## The pattern: an unknown record must look exactly like a forbidden one

Each row is a fix that closed the obvious channel and was caught still leaking through another:

| PR | First fix | Channel that still distinguished them | Caught by |
|---|---|---|---|
| #1436 r1 | catch `DoesNotExistError` and return the forbidden answer | `frappe.throw()` appends "X not found" to `message_log` **before** raising, so the text survives the catch and rides out in `_server_messages` | review |
| #1416 r2 | `frappe.clear_last_message()` on the unknown path | on frappe 16.30 the **forbidden** path also queued "does not have doctype access", from a nested `has_permission(doc.doctype)` with `print_logs=True`. The fix: trim `message_log` back to its pre-call length on both paths | author, with a Volunteer (read) caller. It appears only when the caller holds no blanket doctype-level grant; per `15b605f60`'s message, a Team Lead (write) caller does not show it |
| #1436 r2 | synthesize `get_doc_permissions`'s answer for an unknown name | a controller hook denies **per document**: User's hook refuses only Administrator/Guest, so an unknown email looked like Administrator and unlike every real user | coordinator probe |
| #1436 r3 | build the synthetic answer from `frappe.new_doc(doctype)` | `new_doc` fills link fields from the **caller's own default User Permissions**, so an unknown name looked like an in-scope record | review (Cost Center scoped by Company) |
| #1405 -> #1428 | #1405 removed the team page's raise-vs-False oracle | the query **count** still differed | #1405's review (filed #1402, fixed by #1428) |

The design that ended #1436 is to **refuse identically**, not to imitate. `get_doc_permissions` answers only for a document the caller can read. Otherwise it raises the same `PermissionError("Not permitted")` for unknown and forbidden records, and trims whatever the check queued.

The deliberate behaviour change was checked against DocPerm data for every in-repo caller: Frappe's Kanban view, and the HRMS FormView and RequestActionSheet. Those roles have unconditional read, so none of them can hit the new 403.

**Suggested rule:** for an existence-oracle fix, compare the unknown and forbidden cases on **every** channel:
- exception type and HTTP status;
- message;
- `message_log` / `_server_messages`;
- Error Log rows;
- query count;
- response shape.

Use a caller **without** blanket doctype-level access. A privileged caller hides half of these differences.

### Frappe core has the same oracle (report drafted, NOT sent)

`frappe.client.has_permission` and `frappe.client.get_doc_permissions` load the document before checking permission. An unknown name raises `DoesNotExistError`, while a forbidden one returns `False` or a dict.
- **Reproduced:** over HTTP on **v16.35.0** with stock endpoints, core doctypes (User, ToDo, Role) and a roleless user. A Guest gets a uniform 403, which is the control.
- **Not tested:** `develop` at `d5e67002b7` has the same code; that was read, not run.
- **Why 403 versus 404:** `frappe.permissions.handle_does_not_exist_error`, which wraps `app.handle_exception`, converts the escaping error to a 403 when the caller has no doctype-level permission. That explains why a session-cookie request saw 403 and a token request saw 404.
- **v16.35 changed one thing:** the nested check now passes `print_logs=False`, so the forbidden path no longer leaks a message. The exception-versus-`False` split remains.

The draft recommends Frappe's private vulnerability-reporting form, per its SECURITY.md, over a public issue. The fix it suggests was verified in-process on 16.35. The draft is in the session scratchpad, not in the repo; the maintainer decides the channel and sends it.

## The second pattern: a control that cannot fail

Several tests passed for the wrong reason. Most were control tests with **nothing for the wrong behaviour to find**:

| PR | Test | Why it could not fail |
|---|---|---|
| #1447 r1 | "a non-duplicate failure is not recovered as a race" | the fixture deleted every matching Cost Center, so the wrongly-run recovery lookup found nothing either way. Mutating `is_duplicate_key_error` to always return True kept all 20 tests green. Fixed by planting a real matching row. |
| #1374 r1 | the #1344 regression test | it exercised its own copy of the fix, not the real `PaymentHistoryScalabilityTest.setUp` |
| #1392 r1 | 4 mocked donor-match tests | the review found all 4 defeated by their own mocks |
| #1397 | `test_fallback_handles_derivation_errors` | it never reached the `except` branch it is named for (#1382) |
| #1418 | `force_unique_name` | a hard-coded `seed=12345` guaranteed a collision within one run (#1404) |
| #1445 | the new EUR guard test | alone, it passed a wrong "compare to company currency" fix, because the fixture's INR company differed from both currencies. The module's sibling EUR tests catch it, so no change was needed. |

**Suggested rule for briefs:** "Mutate the fix toward the plausible wrong fix, not just away. And give every control test a real row for the wrong behaviour to find."

## Framework upgrade (frappe 16.30.0 -> 16.35.0, erpnext 16.30.0 -> 16.36.0)

- **Versions.**
  - frappe v16.35.0 with the parallel-test-weights patch re-applied; it is the same patch CI applies via `frappe-parallel-test-weights.patch`.
  - erpnext v16.36.0.
  - hrms `version-16` (16.20.0). It was a 2025 `develop` checkout reporting 16.0.0-dev.
  - payments `version-16`.
- **Preserved before switching.** The earlier heads and local patches are in `frappe-bench/upgrade-2026-09-25/`, and veg11 was backed up with files (`20260925_232729`).
- **HRMS local change.** hrms carried an uncommitted deletion of 19 `desktop_icon` / `workspace_sidebar` files. It was **not** re-applied, for CI parity; the patch is saved.
- **Migration.** All 15 sites migrated with exit 0, veg11 was restarted, and assets were rebuilt.
- **test_site_5** had never run `add_mollie_payment_entry_idempotency_key`. 52 leaked test Payment Entries on fixed Mollie IDs blocked it (the patch correctly refused). Their accounts no longer existed, so `cancel()` raised a TypeError, and they were raw-deleted. See #1438.
- **One test lost its discriminating power on 16.35.** #1436's message-log test no longer distinguishes old code from new. Its docstring now says so, and it is kept as a regression guard.

## Gates and instruments

- **`automerge.sh` + `premerge.sh`** (session scratchpad) merged 20+ PRs unattended. They merge only when CI is all green AND every premerge success marker is present:
  - "baseline: in sync";
  - "0 harness-super-skip";
  - "No newly duplicated";
  - "log_error order: ok";
  - "census unchanged".

  A first version stopped on the *success* strings. Require the markers; don't grep for failure words.
- **The harness-logger census gate reddened #1383 in CI** (MRO_TEARDOWNS 11 -> 12). The coordinator fixed it on the branch. It is push-only, as recorded before.
- **#1421 claimed duplicate-helper drift is a CI failure.** It is not: CI compares clone-family lines only.
- **`frappe.get_lazy_doc` was added to the test-quality enforcer's allowlist** for a deadlock-propagation test in #1436. The review judged it narrowly scoped, with the same shape as `frappe.get_doc` / `frappe.new_doc`.

## Coordinator and agent mistakes (so they are not repeated)

- **`git stash` was used by three authors** (#1328, #1286, #1436), despite the brief. Each popped cleanly and no stranger's stash was touched; verified with `git stash list`. The brief line was one clause among others. It is now a standalone rule with alternatives:
  - `git show HEAD:<path>`;
  - a patch file plus `git checkout --`;
  - a detached worktree.
- **Agents still backgrounded `git push`** after the 120s default timeout. The brief says to set the Bash timeout to 900000. They recovered by waiting for the notification, but "run the push in the foreground with timeout 900000" belongs in the step itself, not the preamble.
- **Two sites were double-assigned**: a reviewer and an author on site 12, and two reviewers on site 9. SendMessage corrections fixed them. Check the ledger's site column before every dispatch, including answering rounds.
- **The CI-watch Monitor delivered nothing for 30 minutes.** `D=$(dirname "$0")` was relative after `cd`.
- **`pkill -f <pattern>` killed the coordinator's own shell twice**, because the pattern appeared in its own command line. Stop servers by the PID listening on the port.
- **A reviewer reported a "pre-existing failure on develop"** (`test_test_quality_enforcer::PathKeyTest`) that the coordinator could not reproduce, from either the main checkout or a worktree. It was not filed.
- **An org spend limit killed 3 agents** at about 16:00. The maintainer paused all agents for 30 minutes later on; every agent saved a `.pause-wip.patch` and resumed cleanly.

## Not done

- **Frappe core report: drafted, NOT sent.** The maintainer picks the channel (private advisory recommended) and submits it. The text needs no changes for 16.35 or `develop`.
- **Follow-ups unblocked by this session's merges, not started** (the maintainer closed the queue):
  - #1396, the remaining Donor-by-email picks (unblocked by #1423);
  - #1414, approve/reject membership application (unblocked by #1424);
  - #1415, the `force_unique_name` re-check (unblocked by #1418);
  - #1420, member.js fee-history response shape (unblocked by #1425);
  - #1434, the `%Ponto%` account fallback (unblocked by #1437).
- **Still queued from before:** #1399 (half of it was corrected in its own comments), #1357, #1390, #1355, #1325, #1398, and the six new ones #1438–#1443.
- **Add to the reviewer brief's gates:** the duplicate-helper **clone-family sync** step (`baseline_shrink_gate.py --require-marker "# clone family" --already-regenerated`). #1447 went red in CI because nobody ran it: not the author, not the reviewer, and not `premerge.sh`. That script runs this step only after CI is green, and CI had already failed.
- **Put the "push in the foreground with timeout 900000" instruction in step 6 itself**, not just the preamble. Several authors missed it.
- **hrms local change:** the uncommitted deletion of 19 `desktop_icon` / `workspace_sidebar` files is saved at `frappe-bench/upgrade-2026-09-25/hrms-local.patch`. It was not re-applied. Re-apply only if hiding those HR icons on veg11 is still wanted.
- **Leaked fixed-ID test rows** may still sit on other test sites. Rows were cleaned on test_site_4 and test_site_5 only; #1438 tracks the cause.
- **42 agent worktrees** remain under `/home/frappeuser/agent-worktrees/`. All their branches are merged except `issue-906` (#1201, open, predates this session) and `issue-1363` (PR #1409, closed as superseded by #1422). They are safe to remove with `git worktree remove`; they were left in place because removal was not requested.
- **veg11** is on develop `f29a1bdac`, migrated (#1422's patch ran), and restarted. It serves the #1436 override: both hooks were verified to resolve to the app functions.

## Filed this session

#1356–#1363, #1365–#1367, #1372, #1373, #1376, #1378–#1380, #1382, #1384, #1386, #1387, #1389, #1390,
#1393–#1396, #1398–#1404, #1406, #1408, #1410, #1411, #1413–#1415, #1417, #1420, #1421, #1426,
#1429–#1431, #1434, #1438–#1443.

Highest value (open):
- **#1411:** the `frappe.has_permission(doctype, ptype, name)` raise-vs-False oracle, swept app-wide. It is the app-level twin of the core oracle.
- **#1440:** automated monthly SEPA collection (`get_sepa_invoices_with_mandates`) has no currency filter. Two dd_batch candidate producers (`dd_batch_optimizer.py:177`, `dd_batch_api.py:398`) are recorded in a **comment** on the issue, not its body. A non-EUR row sticks the whole batch.
- **#1442:** two older SEPA currency guards fail OPEN on a blank currency. #1445 fixed the third.
- **#1396:** four more Donor-by-email arbitrary picks, one of them guest-reachable. Unblocked by #1423.
- **#1414:** approve/reject membership application share #1394's existence oracle. Unblocked by #1424.
- **#1439:** 144 whitelisted parameters still lack type annotations; each needs its own caller audit.
- **#1365:** a census of 66 `@standard_api(REPORTING)` endpoints for unscoped per-member data.
