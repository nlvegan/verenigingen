# 2026-09-27b: the next path came from a second writer of the same state

This session picked up after the 2026-09-27 handoff
(`docs/handoffs/2026-09-27-the-fix-closed-the-named-path.md`, in PR #1527, still open). The
maintainer asked for two things: put that handoff's suggested brief line into the dispatch kit,
then pick two open issues.

- **Staffing.** Two sonnet authors, one per issue, on test_site_1 and test_site_2. Two sonnet
  `skeptical-code-reviewer`s on test_site_6 and test_site_7. Each reviewer was resumed for
  every later round of the same PR, so it kept its context.
- **Review.** Every author commit was reviewed independently before the push. Every answering
  round got a re-review, except for one docstring-only delta that the coordinator checked.
- **Merging.** Before either PR was queued, both branches were merged onto develop in a scratch
  tree and all four affected test modules were run together. Then `automerge.sh`: full green
  CI, the `premerge.sh` gates, and a pin to the head commit.

## Kit changes (`~/frappe-bench/dispatch/`, not in the repo)

- **`author_brief_common.md` step 3:** "Then sweep the OUTCOME, not only the pattern." List every
  other way the same bad outcome can still be reached: other callers, other lifecycle steps,
  other failure branches. Put one test on each, or say why it can't be reached. The list goes in
  the report.
- **`reviewer_brief_common.md` item 4:** the reviewer builds its own list of such paths before
  reading the author's, compares them, and tries to reach the harm on any path the author
  missed or called unreachable.
- **`README.md` rule 11:** reject an author report that has no list of paths.
- **`README.md` rule 10, extended:** `watch_prs.txt` must be one PR per line. `automerge.sh`
  removes a merged PR with `/^<pr>$/d`, which never matches a space-separated line, so
  #1535 stayed on the watch list after it merged.
- **`author_brief_common.md` policy paragraph:** now includes #1533 and #1536.

## Decisions made by the maintainer

| Subject | Decision | Where recorded |
|---|---|---|
| #1533 | Chapter-scoped Membership Goals attribute each member to **one** chapter: the chapter they are in, or were in when terminated. A transfer counts only for the destination; the source drops the member. Exclude `enabled=0 AND status='Active'` rows (transferred out, or left); keep `status='Inactive'` rows (terminated). The alternative, chapter-level headcount, was not chosen. | issue comment |
| #1536 | "Suspended members count until terminated." A Suspended member's born-Inactive Chapter Member row counts. Closed as not planned. | issue comment |
| kit | Add the "sweep the outcome" line to the dispatch kit and the briefs. | chat (this file, kit) |

Both rulings are also in memory (`product-policy-decisions-2026-09-23.md`) and in the author
brief's policy paragraph.

## What shipped

**2 PRs merged**; the merge commits are in **Final state**.

| PR | Closes | Commits | What |
|---|---|---|---|
| #1535 | #1518, #1534 | `04749b4cb`, `ef90cd08a`, `cbc574005` | Board members can see and act on their own chapter's pending applications. Pending Chapter Member rows now count only when the **target Member's** `application_status` is `Pending`. `_is_member_in_chapters` now requires `enabled = 1`. |
| #1537 | #1516, #1530, #1531, #1533 | `c91ca6451`, `94ad84a98`, `1878b5c86` | The crashing `current_chapter_display` read is removed from `quick_approve_member`. The chapter is now resolved from the applicant's single Pending row, with one identical refusal otherwise. That also removes the existence oracle analysed in issue 1360, which stays open for the maintainer. Chapter-scoped Membership Goals query Chapter Member rows per the #1533/#1536 rulings. The termination status is `"Executed"`, not the invalid `"Completed"` (3 sites). |

## The pattern: the next path came from a second writer of the same state

The new brief line worked on paths **along the call chain**. On #1518 the author found on its
own that approving runs two more permission checks with the same Active-only shape
(`member.save()` → `has_member_permission`, and `Membership.insert()` →
`has_membership_permission`), and fixed all three. On #1516 the author found that removing the
crash would reopen #1360's existence oracle, and closed it in the same change.

What every review round still found was a **second writer of the row state the fix keyed on**:

| PR, round | The fix keyed on | The writer the author did not consider | Harm found by review |
|---|---|---|---|
| #1518 r1 | a Pending `Chapter Member` row | `member_manager.request_to_join`, reached from the portal `Chapter.join_chapter`: an **Active** member asking to join a second chapter | That chapter's board got read and write on the member's whole record, with no expiry. The reviewer measured `has_permission` read/write for chapter B's board on the Active joiner: True/True on `04749b4cb`, False/False with `permissions.py` reverted to develop. This is from the reviewer's report; the PR body gives it as prose. |
| #1518 r1 | the same | (the status filter itself) | Dropping `_is_member_in_chapters`'s status clause kept all 15 tests green. |
| #1518 r2 | the new `enabled = 1` check | `remove_member(permanent=False)`, a departed member's row left as `enabled=0, status='Active'` | Not a harm from the fix: a pre-existing hole the fix closed. On develop the SOURCE chapter's board kept read and write on the departed member: True/True on develop, False/False after `ef90cd08a`. Filed and closed as #1534; its list-view half moved to #1529. |
| #1516 r1 | an Active, enabled row = "belongs to the chapter" | termination (`disable_chapter_memberships_safe`, which writes `enabled=0, status=Inactive`) | Terminated members could never count as lost (#1531). This was masked by `status="Completed"` (#1530), which made lost-members 0 for every goal. |
| #1516 r2 | any non-Pending row | transfer or leave (`remove_member(permanent=False)`, which writes `enabled=0` and leaves `status='Active'`) | A transfer was counted as new in both chapters (#1533). |
| #1516 r3 | an Inactive row = "terminated" | `add_member`, which writes `Inactive` for a non-Active member at assignment | Filed as #1536; ruled correct behaviour. |

**Suggested brief line (not yet in the kit):** when a fix keys on a row's state (a status, an
`enabled` flag, a child row's existence), grep for **every writer** of that state, not only the one
the issue names. Say which state each writer leaves the row in and whether the fix classifies it
correctly. Test the writers that matter with their real flows.

## Coordinator decisions worth knowing

- **#1531 was folded in, against the reviewer's recommendation.** The round-1 reviewer approved
  with nits and suggested fixing #1531 later, since #1530 was already hiding it. The coordinator
  sent it back instead, because this PR introduced the defect, in the function it changed.
  #1530 was fixed with it, because #1531 can't be observed red/green without it.
- **#1534's list-view half was moved to #1529.** The #1518 author found that
  `get_member_permission_query` and `get_membership_permission_query` (the Desk list views) also
  lack the `enabled` check. Closing #1534 through #1535 would have dropped that half, so it is
  now tracked on #1529.
- **A combined run before automerge.** `premerge.sh` merges each PR onto develop and runs the push-only
  gates, but runs no tests across two unmerged PRs. Both PRs changed the approval path, so both
  branches were merged in a scratch tree and run on test_site_3:
  - `test_member_approval_permissions` 19 OK
  - `test_chapter_dashboard_api_coverage` 26 OK
  - `test_membership_goal` 11 OK
  - `test_member_doctype_coverage` 40 OK

## Disclosed limitations (in the PR bodies)

- **#1535:** `test_escalation_guard_keys_on_application_status_not_member_status` uses a state
  (`status='Pending'` while `application_status!='Pending'`) that no production writer
  produces. It is set with `db.set_value`, because it is the only state that catches the
  wrong-field mutant. The oracle comparison on #1535 did **not** measure query count or Error Log
  rows.
- **#1537:** `test_retention_rate_decreases_after_real_termination` can still fail if leaked site
  data clamps the baseline to 0. It now fails as a labelled precondition. `_chapter_member_names()`
  fetches every historical row of the chapter, which is unbounded but not a correctness issue.

## Process and coordinator notes

- **`gh` from `dispatch/` again.** The 27th's handoff listed this slip, and it happened again: the
  first queueing of #1535 failed with "not a git repository". Run `gh` from `apps/verenigingen`.
- **A reviewer used `git stash` once** (#1516 round 1, in its own detached tree) and disclosed
  it. The coordinator checked that the stash stack still holds exactly its 2 foreign entries.
  Every later round avoided it.
- **An ambiguous mutant name.** The author reported "`enabled=1` alone" as 4 failures. The round-3
  reviewer's first reading of that phrase gave 3 failures, and only the second reading gave 4, so it
  had to try both. This is from the reviewer's report; the PR body gives only the 4. Ask authors to name the exact filter
  dict in mutation reports.
- **veg11 restart needs no sudo.** Use `supervisorctl restart frappe-bench-web: frappe-bench-workers:`.
  `sudo -n supervisorctl` asks for a password.
- **veg11 has zero Pending Chapter Member rows**, so it can't show how long such rows live in
  real data. That question had to be settled from the code.

## Not done

- **Filed this session, still open:**
  - #1528: `scripts/performance/performance_profiler.py` has the same `current_chapter_display`
    field-list crash, swallowed by a broad except.
  - #1529: the Desk member and membership list-view permission queries still exclude Pending
    applicants and lack the `enabled` check.
  - #1532: two more sites use the invalid `"Completed"` termination status
    (`predictive_analytics.py`, `analytics_alert_rule.py`), so churn KPIs always read 0.
- **#1360 is still open.** The #1516 author commented there with the oracle-closure evidence and
  recommended closing it once #1537 merged. It has merged; the close is the maintainer's call.
- **Not established (#1536):** whether un-suspending a member flips their born-Inactive row to
  Active. It doesn't change the count under the ruling.
- **Handoffs:** PRs #1448 and #1527 are still open.

## Final state

- **Merged (PR → merge commit):** #1535 → `5dac44640`, #1537 → `451e15dc9`.
- **Closed:** #1516, #1518, #1530, #1531, #1533, #1534 (by merge); #1536 (not planned, ruled).
- **veg11:** the tree is at develop `451e15dc9`. The merged changes touch no DocType JSON, hooks or
  patches, so no migrate was needed. Web and workers were restarted via `supervisorctl`, and the
  new code was confirmed loaded (`MembershipGoal._chapter_member_names` exists; `/api/method/ping`
  returned 200).
- **Main tree:** `apps/verenigingen` is at develop `451e15dc9` and clean.
- **Automerge:** finished with "ALL APPROVED PRs MERGED"; `approved_prs.txt` holds no PR numbers.
- **Agents:** none running.
- **Worktrees:** `/home/frappeuser/agent-worktrees/issue-1516` and `issue-1518` are merged and safe to
  remove. They were not removed.
