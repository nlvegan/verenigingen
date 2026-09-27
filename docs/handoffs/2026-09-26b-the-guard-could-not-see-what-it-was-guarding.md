# 2026-09-26b: the guard could not see what it was guarding

This session started from the 2026-09-26 handoff. That handoff is still open as **PR #1448** and not merged; read it first.

- **Staffing.** Issue units went to sonnet authors. The maintainer set the pool cap to 6, then 4, then 2, reviewers included.
- **Kit.** The briefs, merge gates and coordinator rules now live on disk in **`~/frappe-bench/dispatch/`**, no longer in a session scratchpad. Start with its README and `ledger.md`.
- **Review.** Every commit got an independent `skeptical-code-reviewer` before it was pushed. Every answering round got a narrow re-review or a coordinator delta check. The coordinator's own review was used only for a test-only 5-line hotfix (#1506) and for a one-line test fix (#1509's cache-guard commit). In both cases red and green were reproduced on a second site.
- **Merging.** Every merge went through `automerge.sh`: full green CI, the `premerge.sh` gates against the then-current develop, and a pin to the head commit.

Terms used below (defined in #1448 and CLAUDE.md):
- **existence oracle**: an endpoint that answers differently for an unknown record than for a forbidden one.
- **delta check**: the coordinator re-verifying only what changed since a reviewed commit.
- **the drain**: `EnhancedTestCase`'s teardown deletion of every row a test inserted.

The headline pattern this time: **several fixes were correct and still did not protect anything**, because the check or the surface could not see what it was supposed to guard. Details follow the tables.

## Decisions made by the maintainer (recorded on their issues)

| Issue | Decision |
|---|---|
| #1396 | Ambiguous `donor_email` on the **guest** donation form: create a new, unlinked Donor and write to no existing one. On ambiguity in the Mollie flow: a fresh customer. Availability wins for anonymous donors. |
| #1450 | Ambiguous donor on the **periodic donation agreement** form: **refuse** and ask the user to contact the association. No new Donor, no BSN write, no agreement. Stricter than #1396 because the form creates a legal/tax agreement. |
| #1461 | Keep the fail-closed ANBI consent rule. The web form collects consent (a checkbox). No controller change. |
| #1483 | The periodic donation agreement web form **is meant to be live**. Wire it to `process_agreement_form` and publish it. Not started (see Not done). |
| #1486 | Restrict `export_agreements` to exactly the ANBI report's roles, derived from the report itself. |
| #1504 | Merge #1486's report-role gate now, even though Role-Profile-provisioned Auditors/Treasurers do not hold the literal role and are refused. Fix #1504 later. Zero such users on veg11. |
| #1325 | A member merge whose source has an invoice-referenced dues schedule **refuses up front**, before any write. Accepted: 431 of 748 veg11 members (58%) cannot be a merge source. |
| cleanup | Approved: delete the dangling `Payment Request-payment_session_log` Custom Field on test_site_2/3/5 (#1337) and 3 leaked test Members on test_site_13. The coordinator's delete was **blocked by the permission classifier**, and the commands were handed to the maintainer. Whether they were run is **not known**. |
| pool | The concurrent-agent cap went from 6 to 4 to 2, reviewers included. |

## What shipped

**21 PRs merged** in this session. Three more were approved and queued (#1495, #1508, #1509); their outcome is in **Final state** at the end of this file.

| PR | Closes | What | Notable review finding |
|---|---|---|---|
| #1457 | #1434 | refuse an ambiguous `%Ponto%` bank-account fallback | disabled accounts counted as candidates; fixed with `disabled: 0` after an ERPNext probe |
| #1470 | #1451 | the same for the `%Mollie%` clearing account | the veg11 clearing account belongs to a leaked test company (#540) |
| #1458 | #1414 | approve/reject existence oracle: permission check before the existence check | all channels identical in fresh processes; "all"-access callers keep the distinct error |
| #1487 | #1453 | the same oracle in the deprecated background-approval endpoint, plus a status channel | a self-catch bug had hidden "Invalid member reference" even from staff |
| #1459 | #1396 | 3 remaining arbitrary Donor-by-email picks | the ambiguity decision escalated to the maintainer; 3 tests only suppressed the Error Log |
| #1472 | #1450 | refuse an ambiguous donor on the agreement form | the tri-state resolver is the 4th copy of the tier logic (#1471) |
| #1500 | #1449 | donation-form prefill ambiguity | the web form is unpublished, and `/donate` is served by `donate.py` (#1499) |
| #1460 | part of #1411 | `permission_allowed_without_oracle` helper at 12 sites | a `clear_last_message` mutant survives on 16.35; disclosed as a regression guard |
| #1469 | #1440, #1442 | EUR filter on 3 SEPA producers; blank currency fails closed | the veg11 "565/565" claim was wrong: the real query returns 0 (#1465) |
| #1489 | #1463, #1464 | EUR check in the race manager; no `or "EUR"` defaults before XML validation | a 4th sibling default in `_append_invoice_rows` |
| #1456 | #1420 | fee-history JS reads the nested envelope | one mutant indistinguishable on the real schema; the claim was corrected |
| #1491 | #1452 | 3 more member.js envelope misreads; manual invoice was broken for everyone | a redundant test helper hid a 49-copy clone |
| #1480 | #1454 | delete a dead JS test file, port 5 real tests, fix a donor.js crash | CI's `js-coverage` is not a required check, and develop has no branch protection |
| #1492 | part of #1365 | census of 95 REPORTING endpoints; 4 listing leaks scoped | multi-writer worktree collision (see mistakes) |
| #1478 | #1441 | root Cost Center fallback when no parent exists | a 5th creator missed (#1477); CLAUDE.md "Pattern 3" note was stale and is now corrected |
| #1473 | #1415 | `force_unique_name` re-checks its collision candidate | the test had no collision-fired control |
| #1494 | #1466 | drop a dead Volunteer collision check | the test-quality enforcer is blind to `patch.object(frappe.db, …)` (#1493) |
| #1474 | #1438 | per-test Mollie ids; `addCleanup` drains, so a failed setUp stops leaking | switched to the harness's own `addCleanup` idiom |
| #1498 | #1468, #1496 | 15 more hard-coded ids; `addCleanup` on 2 more classes | a sibling class leaked 6 Donations/PEs/Members on a setUp failure |
| #1482 | #1390 | remove two mid-test commits | the leak needs live RQ workers (dev box only), and the order-dependence baseline shrinks |
| #1506 | #1505 | **hotfix**: order-dependent test from #1469 | reddened #1495's CI shard; see the pattern section |

Queued at the time of writing: **#1495** (#1461, consent checkbox), **#1508** (#1325, merge refuse-up-front plus a savepoint wrapper), and **#1509** (part of #1486; its body states the #1504 Auditor gap prominently). See **Final state**.

## The pattern: the guard could not see what it was guarding

| Where | What looked fixed | Why it protected nothing, or less than claimed |
|---|---|---|
| #1507 / #1508 | a second "is the source deletable" check just before the delete | Under MariaDB REPEATABLE READ, a reference **committed by another connection** after this transaction's snapshot is invisible to plain reads. That covers the new check **and** Frappe's `check_if_doc_is_linked`, which #1306's delete guard uses. The reviewer reproduced with two connections: a real `delete_dues_schedule_with_backlink_cleanup` deleted a schedule a committed invoice still referenced. #1508 honestly claims **same-transaction** protection only. |
| #1483, #1499 | fixes to `process_agreement_form` (#1472, #1495) and `get_existing_donor` (#1500) | Both Web Forms are **unpublished**. The agreement form's generic JS posts to `accept()`, not `process_agreement_form`. `/donate` is served by `templates/pages/donate.py`. The fixes are reachable only by direct API call until #1483 wires the form. |
| #1488 | a Web Form JSON field change (#1495's checkbox) | The JSON's frozen `modified` timestamp makes `bench migrate` **skip** the import. #1495 bumps its own file; other web forms have the same trap. |
| #1505 / #1506 | #1469's currency tests, green on develop | They relied on another suite creating the "SEPA Direct Debit" Payment Terms Template earlier **in the same shard**. A re-pack reddened an unrelated PR (#1495). |
| #1504 / #1509 | "Auditor keeps access" via the report's own role list | Role Profiles do not grant the literal role the report lists, so a real Auditor is refused. |
| #1509 (push) | a test that reads `frappe.get_roles(user)` as a precondition | It reads before `set_user` from a stale cache. It was caught only by the **push-only** cache-guard gate, after pre-commit and review passed. |
| #1461 first cut | consent recorded, then the agreement created | Consent was committed even when the agreement failed, because the outer handler returns `{success: False}` and the POST request commits. Fixed with a savepoint. The class is #1501 (whitelisted wrappers commit partial writes); the swallowed-deadlock variant is noted on #1361. |

**Suggested rule for briefs:** before calling a guard fixed, ask **"what can this check actually observe?"** Four questions:
- Is the row visible under the isolation level?
- Is the surface reachable at all? Check the published flag, the route and the real caller.
- Does the change deploy? Check for a JSON `modified` bump, and for a fixture versus a patch.
- Does the test's precondition exist on a fresh CI site?

## Second pattern: setUp failures and fixed ids leak through the drain

`EnhancedTestCase`'s drains run from `tearDown`, and unittest skips `tearDown` when `setUp` raises. A shared fixture that commits unconditionally (`ensure_mollie_reversal_accounts`) then persists the half-built rows on the NEXT test's setUp. The measured effect was 6 of 7 rows leaking. The fix is the harness's own idiom: `self.addCleanup(self._drain_tracked_documents)` and `self.addCleanup(self._drain_captured_inserts)` right after `super().setUp()`. It is applied per class in #1474 and #1498; the general harness fix is **#1467**.

## Process and coordinator notes (so they are not repeated)

- **A fork collision cost about 30 minutes (#1365).** The #1365 author spawned 3 "read-only census" forks and completed. Two forks edited 8 files with a design contradicting a ruling, and the third reported to the coordinator as though it were the author. After those forks were stopped, **the "completed" original author resumed by itself** and red/green-cycled against the surviving fork in one tree, each reverting the other's files and killing the other's runs. The brief now forbids forks, and `dispatch/README.md` rule 9 says: name the ORIGINAL author as the sole writer and invalidate the overlap.
- **Two org spend-limit stops** (around 11:00 and 17:00) killed 4, then 2, agents mid-work. Checkpointing every worktree (tracked patch plus untracked tarball) before resuming lost nothing. Automerge kept merging through both.
- **The coordinator double-assigned a test site once** (#1325 and #1449 both on test_site_4). It was caught before any run conflict and moved to test_site_1.
- **The permission classifier blocked destructive test-site cleanup** (deleting a Custom Field, leaked Members) for both agents and the coordinator. That happened even with maintainer approval in chat, while one agent's identical delete on test_site_1 went through earlier. The coordinator did not work around it and gave the maintainer the commands.
- **Under the cap of 2, the coordinator pushed and opened 4 PRs itself** (#1500, #1506, #1508, #1509) instead of resuming a finished author just to push. Three pushed cleanly. The fourth (#1509) hit the push-only cache-guard gate described above and needed a one-line test fix first; this was caught before merge.
- **Agents still backgrounded `git push`** twice despite step 6. They recovered by waiting; the brief line is already in step 6.
- **`git stash` was used once** (#1452): the author popped its own entry and reported it.
- **Baseline drift (#1421).** Regenerating `duplicate_helper_baseline.txt` rewrites about 23 unmarked lines unrelated to any change. Three early commits included that drift. The brief now says to commit only lines your change caused.

## Not done

- **#1483**: wire and publish the agreement web form (ruled). It must also bump the JSON `modified` (#1488) and pick a route that does not collide (#1499 is the donation-form analogue).
- **#1504**: Role Profile vs literal role for Auditor/Treasurer (ruled as later).
- **#1507**: delete guards blind to concurrent references under REPEATABLE READ. It needs locking reads in shared delete machinery; no fix has been proposed yet.
- **#1501**: about 55 files where a whitelisted wrapper catches after a write and returns `fail`, which POST then commits. This is a raw grep, and the exposures are unverified.
- **#1467**: the general harness `addCleanup` fix.
- **#1486 remainder**: `review_account_types` (an under-scoped read counterpart to a HIGH-tier write endpoint; not confirmed live, and deprioritized for time, not a policy call), and #1502 (the membership_applications page 500s for everyone).
- **Smaller filed items:**
  - JS: #1475 (6 more uncollected test files), #1476, #1485 and #1490 (envelope patterns).
  - Arbitrary picks and oracles: #1497 (Mollie-id arbitrary pick), #1484 (background-approval progress has no chapter check).
  - SEPA: #1481, #1455 and #1465 (automated SEPA selects 0 on veg11).
  - Other: #1471 (4 copies of the donor tier logic), #1477 (a 5th cost-center creator), #1493 (enforcer mock blind spot), #1503 (divide-by-zero), #1462.
- **Still from the previous handoff:** the Frappe core existence-oracle report (drafted, not sent), and PR #1448 itself.
- **Environment:**
  - The #1337 Custom Field removal on test_site_2/3/5 and the 3 leaked Members on test_site_13 were handed to the maintainer; state unknown.
  - Agent worktrees under `/home/frappeuser/agent-worktrees/` are safe to remove once their PRs merge.
- **veg11**: see **Final state**.

## Filed this session

#1449–#1455, #1461–#1468, #1471, #1475–#1477, #1479, #1481, #1483–#1486, #1488, #1490, #1493, #1496, #1497, #1499, #1501–#1505, #1507.

## Final state

Filled in by the following session (see `2026-09-27-the-fix-closed-the-named-path.md`):

- **#1509 went red first.** Its CI shard 12 failed: `test_staff_still_allowed` depended on an
  ad-hoc SEPA table that a fresh CI site never has (#1510), and the three refusal tests beside
  it were vacuous for the same reason. It was fixed and re-reviewed. The maintainer then held
  the automerge restart until #1504, #1510 and #1511 were dealt with.
- **Merged:** #1495 → `91588e1a1` (closes #1461), #1508 → `4e68ce060` (closes #1325), and
  #1509 → `d5fdcfef9` (part of #1486; #1486 stays open for its remainder).
- **Environment:** test_site_1..13 were reset from a rebuilt snapshot, which cleared the
  #1337 Custom Field on sites 2/3/5 and the leaked test_site_13 Members. The Members turned
  out to be 8, not 3 (counted by the coordinator before the reset). veg11 was migrated and restarted at develop `d4d8f827f`.
