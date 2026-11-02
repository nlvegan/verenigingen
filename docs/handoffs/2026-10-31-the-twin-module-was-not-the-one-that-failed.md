# 2026-10-31: the twin module was not the one that failed

This session (2026-10-30e, running into 10-31) started from the 2026-10-30c handoff (PR #1760). A
parallel session ("2026-10-30d": #1753, #1762, #1767, #1770, #1779) ran the whole time and shared the
dispatch ledger and the test-site pool.

The maintainer's instructions, in order:

1. "PR #1760 < please read"
2. Two decisions:
   - #1741: reuse the existing dues schedule; the record worth keeping is the membership.
   - #1740: the cause is that there is no separate application record → "let's go with option 3".
3. Answers to #1765's six design questions (recorded on #1765).
4. "start with #1741/#1737"
5. "write the implementation plan for #1765", then "go with your recommendation" (one author per task, reviewed before the next).
6. "the fee-override reason approach is fine"
7. "generate a handoff when it's green and merged"
8. When develop's own red blocked #1776: "option 1" (fix #1782 first).
9. "yes, push the #1765 branch as a backup"
10. "merge 1776 when green"

A standing instruction from the maintainer, recorded in another session (memory `standing-merge-when-green`): merge when CI is green unless a breaking issue was found. Merging another session's PR still needs the user's say-so.

## What shipped

| PR | Closes | What |
|---|---|---|
| #1776 | #1741, #1737 | A voluntary-Quit rejoiner reuses the old dues schedule. Approval reactivates it with the new template and the chosen amount, and bills from the rejoin date via a new `coverage_anchor_date`. Billing chains on the last invoice, not on `next_invoice_date`, so the anchor is what stops catch-up billing for the months away. |

| #1787 | #1782 | develop was red after #1770. EnhancedTestCase/VereningingenTestCase started a rate-limit stub in `setUp` and stopped it only in `tearDown`, and unittest skips `tearDown` when `setUp` raises or skips. `test_payment_processing_http_integration` skips in CI (no live server), so it leaked the stub into the later Mollie rate-limit test. Fixed with `addCleanup` in both bases. **Merged by session verenigingen-0c on its user's go.** |

#1776 merged as `89641bbe7`, pinned to the reviewed head `346c44833`, after the premerge gates and 54/54 green. CI needed two rounds:
- Shard 2 reddened on `flags.get(...)` being truthy on a MagicMock. Fixed with `is True`.
- Shard 11 reddened on the develop red above.

#1787 merged as `769adfdee`.

**veg11 is deployed.** Session verenigingen-0c migrated and restarted it at about 10:25 on 2026-10-31, on develop `d4deb1006`, which includes #1776 and #1787 (backup `20261031_101922`). Verified: `tabMembership Dues Schedule.coverage_anchor_date` exists on veg11.

## Decisions the maintainer made (also recorded on the issues)

| Subject | Ruling | Where |
|---|---|---|
| Quit rejoiner | Reuse the old schedule: reactivate it, apply the new template and chosen amount, re-anchor on the rejoin date. A new Membership is created on each rejoin. | #1741, #1737 comments |
| Chosen amount on a rejoin | Taken from `Member.dues_rate` only when `fee_override_reason` is set (the application and staff both set it). A consequence: a staff override from the first membership carries over to the rejoin. | #1776 body |
| #1740 anonymous overwrite | Fix at the root: the application becomes its own record, and the Member is written only on approval. | #1740, #1765 |
| #1765 design | See below. | #1765 comment |

The #1765 design answers:
1. Both forms use one record.
2. A Member is created only on approval.
3. Review shows which fields would change.
4. No applicant field is excluded in principle. IBAN history is kept through a normal save. Blanks never clear a value, and non-applicant fields (email, statuses, user/customer, ids, staff fee override) are out of reach.
5. 30-day retention is fine.
6. No migration: the existing data is test data.

The maintainer also said that a Pending member followed by a separate activation step would be acceptable. The plan keeps one approval call (create the Member as Pending, then the existing approval core, in one transaction) because it reuses all the existing code and rolls back cleanly.

## #1765 in progress: application as its own record

- **Plan:** `docs/superpowers/plans/2026-10-30-application-as-record.md` on branch **`feat/1765-application-record`** (worktree `~/frappe-bench/worktrees/plan-1765`).
- **The branch is pushed as a backup, with NO PR** (head `c767602a8`, on the maintainer's go). It becomes one PR when all 9 tasks are done, because the intermediate states cannot ship on their own. The first backup push was refused by the pre-push Submittability Drift Guard: a Task 2 test `.submit()`ed a Membership Termination Request, which is not submittable. Neither the task review nor the re-review caught it. Fixed in `c767602a8` by driving the Quit through the real termination service.
- **Ledger:** `~/frappe-bench/worktrees/plan-1765/.superpowers/sdd/2026-10-30-application-as-record/progress.md`. It is git-excluded and holds every ruling (A–O), the deferred minors, and the per-task commit ranges. **Read it before resuming.**

| Task | State | Commits |
|---|---|---|
| 1 MAS becomes the record (statuses, fields, `set_status`) | complete, reviewed | `342fb708e` |
| 2 Both forms stage + email confirm; confirm creates no Member; guest responses uniform | complete, reviewed (opus) + 1 fix round | `9d7fc9317`, `0f347dda6` |
| 3 Board permissions by `MAS.chapter` (read: any active seat; approve: admin seat) | complete, reviewed (opus) + 1 fix round | `86baaeb93`, `3ab633700` |
| 4 Approval materialises the Member | **next**. #1776 is now merged, so rebase or merge develop into the branch first (Ruling F). Expect conflicts in `membership_creation_service.py` and `application_helpers.py`. | |
| 5-9 Reject, change preview, review surfaces, status page/retention, removing old writers | not started | |

Carry into Task 4 (each is in the ledger):
- Reuse `create_volunteer_record`'s re-link-by-email so that no second Volunteer is created.
- Set `MAS.member`.
- Replace `tests/utils/legacy_submit.py` (`submit_and_materialise`).
- Lock the MAS before `set_status`.
- Write `application_id` as None, never "".
- Call `validate_application_permission_or_throw` before loading the MAS.
- Do the endpoint-level oracle comparison.
- Merge onto #1776's `_ensure_dues_schedule_exists` changes.

Implementers ran on test_site_5 and reviewers on test_site_12, and both sites were migrated from the branch. test_site_12 has since been released to session aanmeldformulier. Before reusing any site, check `dispatch/ledger.md` for what is free and migrate it from the branch.

## Coordinator notes: what this session taught

- **The twin module was not the one that failed (#1776).** The author reported `test_dues_schedule_lifecycle_service` green. That was `verenigingen.services.billing.test_…`; CI failed on `verenigingen.tests.services.test_…`, a second module with the same basename. When a report names a module, ask for the dotted path. Before a push, run `find . -name "<basename>"` for every module the change touches.
- **`flags.get(...)` on a MagicMock is truthy.** The new rejoin escape (`if schedule_doc.flags.get("rejoin_reactivation")`) let Cancelled → Active through for any mock, and in production for any truthy value. An escape hatch keyed on a flag should test `is True`.
- **The catch-up harm was not where the issue pointed.** #1741's ruling said "re-anchor `next_invoice_date`". The author measured that billing eligibility never reads that field: coverage chains on the latest submitted invoice. Resetting the field alone would still have billed the months away. Rule 1 applied to our own ruling: the system, not the source.
- **A control test can redden on its fixture.** #1776's "later involuntary termination" control first errored inside the reactivation, because it passed the old (Quit) membership. The coordinator ran it against the pre-fix commit and read the error. It was rebuilt so that it fails on the status assertion. "It went red" is not evidence until you have read why.
- **The old application form was an existence oracle.** It returned "you are already an active member" to anonymous callers. So were `validate_email` and `check_application_eligibility_endpoint`, and an Error Log row written only for a Quit-without-termination email. All are closed on the #1765 branch (the last by Ruling J, which filed #1777).
- **`frappe.call` drops a keyword the hook does not declare.** Six has_permission hooks name the argument `permission_type`, so they always see None and evaluate every check as "read" (#1778).
- **A `setUp` skip leaks whatever the base class started (#1782).** unittest runs no `tearDown` after `setUp` raises or skips, but `addCleanup` always runs. A test that passes alone and fails in a shard is an order problem. The author found the poisoner by diffing the "modules before it" list between the failing shard log and a passing one, then printing the patched function's `__qualname__` after each module. #1785 tracks the per-class instances of the same shape.
- **The pre-push gate caught what two reviews missed.** The Task 2 review and its re-review both passed a test that `.submit()`s a non-submittable doctype. Only the Submittability Drift Guard at push refused it. Per-task reviewers should run the push-only validators, not only the module's tests.
- **A narrower permission helper is a silent regression.** Task 3 reused `get_user_manageable_chapters` (admin seats) for READ. Today any active seat reads its chapter's pending applicants. The review caught it, and read was split from approve (Ruling N).

Dispatch README rules 19 (dotted module paths) and 20 (task reviewers run the push-only validators) were added for these lessons.

## Filed this session (open)

- #1765: design, the application as its own record. The six answers are in a comment.
- #1773: the first invoice at approval takes its period from the Membership Type, not the schedule (a monthly invoice for an annual schedule).
- #1774: approval with `create_invoice=True` silently creates no invoice for a non-Administrator approver (an Item PermissionError is swallowed). The approval-time invoice is therefore untested for rejoiners.
- #1775: approval reuses a schedule cancelled by maintenance or staff and leaves it Cancelled. Not reproduced through a real flow.
- #1777: integrity check for a Quit member with no Executed termination. The alert was removed from the guest path.
- #1778: has_permission hooks named `permission_type` never receive the ptype (now being worked by session aanmeldformulier).
- #1782: develop red (closed by #1787).
- #1785: about 25 test classes start patches in setUp without addCleanup.

Comments: #1741, #1737, #1740 (decisions), #1411 (MAS DoesNotExist-vs-PermissionError instance).

## Final state

- **develop:** includes `89641bbe7` (#1776). The live tree and veg11 are on `d4deb1006`, migrated and restarted by session verenigingen-0c (see above). Untracked and modified files in the live tree, left alone: `ONBOARDING.md` and `email_brand.css`.
- **Other sessions running in parallel:**
  - **aanmeldformulier** (the 10-30d coordinator) owns PR #1779 and 8 new dispatches, including #1778, which I filed. It holds test_site_1, 3, 4, 6–10, 12 and 13.
  - **verenigingen-0c** merged #1787 and is merging its own PRs (#1790–#1800). It holds test_site_2.
  - All three sessions share `dispatch/ledger.md`. Coordinate through it and by message before claiming a site.
- **Sites this session holds:** test_site_5 (#1765 implementer, idle).
- **Worktrees:**
  - `worktrees/issue-1741` and `worktrees/issue-1782` are merged and can be removed.
  - `worktrees/plan-1765` is the live #1765 branch. Keep it.
  - `worktrees/handoff-1031` holds this handoff.
- **Agents:** none running.
- **Open, mine:** #1765 (Tasks 4–9), plus #1773, #1774, #1775, #1777 and #1785 (filed, not started).
- **Follow-up filed during the #1782 review:** #1785, about 25 test classes that start patches in `setUp` without `addCleanup`.
