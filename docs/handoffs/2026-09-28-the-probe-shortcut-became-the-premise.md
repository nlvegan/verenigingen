# 2026-09-28: the probe's shortcut became the issue's premise

This session picked up after the 2026-09-27b handoff
(`docs/handoffs/2026-09-27b-the-next-path-came-from-a-second-writer.md`, PR #1538, still open).
The maintainer asked for four things: clean up the worktrees, add the "every writer" line that
handoff proposed, put agents on the open follow-ups, and close #1360 if it was fully resolved.
Later: "generate a handoff when all of these issues are fixed and the fixes reviewed and CI
greened."

- **Staffing.** Five sonnet authors, one per issue unit, on test_site_1 to test_site_5. Sonnet
  `skeptical-code-reviewer`s ran on test_site_6, 7, 8 and 10. Each reviewer was resumed for the
  later rounds of the same PR, with one exception, covered below.
- **Review.** Every author commit was reviewed independently before the push. The coordinator
  checked four small deltas itself instead of sending them for another review round. Each one
  is listed where it happens.
- **Merging.** `automerge.sh`: full green CI, the `premerge.sh` gates, and a pin to the head commit.

## Housekeeping and kit changes

- **Worktrees.** Removed 34 merged, clean issue worktrees and their merged local branches, plus
  the detached `pr-1509-ci` and an empty `issue-1510-review-scratch` directory. Kept the handoff
  worktrees and `issue-906`, whose PRs are open.
- **`author_brief_common.md` step 3 ("every writer"):** when a fix keys on a row's state, grep
  every writer of that state. For each writer, say which state it leaves the row in and how the
  fix classifies it, and test the writers that matter through their real flows.
  - Reviewer brief item 4 has the matching check.
  - README rule 12: reject a report that has no writer table.
- **Both briefs, `scripts/validation/tests`:** any test that imports a `scripts/` file needs that
  file in `server-tests.yml` `push.paths` and `pull_request.paths`. Run
  `python -m unittest discover -s scripts/validation/tests -p 'test_*.py'` before reporting.
  #1528 was red on `test_workflow_path_filter` for four rounds before a reviewer ran it.
- **Author brief attribution** now uses this session's link.
- **Author brief policy paragraph** now includes #1541 and #1544.

## #1360: closed

Verified on develop `451e15dc9` before closing:
- `quick_approve_member` without `chapter_name` refuses a nonexistent member, a member of another
  chapter and an ambiguous member with the same message.
- `test_chapter_dashboard_api_coverage` 26 OK on test_site_4.
- A message mutant reddens `test_approve_without_chapter_name_refuses_identically_regardless_of_reason`.

The closing comment lists what was not re-measured: query count, Error Log rows, and the
explicit-`chapter_name` path, which relies on #1414's ordering.

## Decisions made by the maintainer

| Subject | Decision | Where recorded |
|---|---|---|
| #1541 | The Zabbix churn metric counts ALL terminated Member statuses: `Quit`, `Deceased`, `Banned`. | issue comment, author brief, memory |
| #1544 | A rejoined member does not count old terminations. Only a termination belonging to the member's CURRENT membership counts against them. | issue comment, author brief, memory |
| #1544 push | "yes, send that message": authorised the final round and the push after the permission classifier blocked it (see below). | chat, ledger |

## What shipped

| PR | Closes | Merge | What |
|---|---|---|---|
| #1545 | #1532, #1540 | `e81abc63b` | Three churn and lost-member KPIs filtered `Membership Termination Request.status` on the invalid `"Completed"`: `predictive_analytics`, `analytics_alert_rule`, and the snapshot's `calculate_member_metrics`. They now use `"Executed"`, tested with real terminations and a Draft control. The fourth site was reverted out and became #1544. |
| #1549 | #1529 | `c704de771` | The Desk Member and Membership list queries now match doc-level access for the enabled/Pending mechanism: `cm.enabled = 1`, and a Pending row counts only for a real applicant. A writer table covers 8 writers through real flows. |
| #1551 | #1528, #1539 | `d3bd88cde` | `performance_profiler.py`: dropped the `current_chapter_display` column crash, and gave the dead input (`get_unreconciled_payments(customer=None)` always returns `[]`) a real per-customer source. It also bounds the query cost to the batch budget, guards `batch_size <= 0`, and adds the file to the server-tests paths. |
| #1552 | #1541 | `2ab4de765` | The Zabbix churn metric counts `Quit`/`Deceased`/`Banned` within `member_end_date BETWEEN today-30 AND today`. Before, it filtered on the invalid `"Terminated"` with a `modified` window. |
| #1555 | #1544, #1548 | `501da7e78` | The member `before_save` hook no longer forces Quit from a termination that predates the current `member_since`, or while a reapplication filed after the termination is pending. Rejoiners could never become Active before this. Cohort retention now counts only current-membership terminations. Approval refuses when a termination postdates the application. |

## The pattern: the probe's shortcut became the issue's premise

On #1545, a reviewer showed the cohort hunk was reachable. They drove a real termination, then
**set `status='Active'` directly** to stand in for re-approval. That shortcut went into #1544's
issue text and into the product question put to the maintainer. It was false. The real
reapplication and approval flow never reaches Active, because the Member `before_save` hook
(`member_utils.update_termination_status_display`) re-derives the status from any Executed
termination on every save. A direct status write skips that hook's effect. The probe measured
a state production cannot produce.

The #1541 author found it (#1548) because the "every writer" rule made it drive the real
reapplication flow. Two later reviewers confirmed it end to end, approval included. The
maintainer's #1544 ruling then settled the fix, because the hook breaks the same principle.

**The same shape turned up four more times this session:**

| Where | The shortcut | What it hid |
|---|---|---|
| #1544 round 1 | Every hook test set `application_status="Approved"` | `application_status` is a Select with no default, so it auto-fills `"Pending"`. The new reapplication skip fired for nearly every member and cleared `member_end_date` on any save. Found only by running #1552's test against the #1544 branch. |
| #1528 rounds 1-3 | The test monkeypatched the input, then later used a fixture where every customer had exactly `batch_size` rows | First, the fix was inert under the real entry point (#1539). Then a flat-limit mutant passed. |
| #1541 round 1 | A helper was renamed to `_create_*` | The name-prefix exemption moved 2 bare commits out of the blocking order-dependence total. That was the whole difference between red and green. |
| #1528 rounds 1-4 | The self-review ran the three habitual gates | `test_workflow_path_filter` was red from round 1 and nobody ran it. |

**Brief line (added to the kit after this handoff, at the maintainer's request: author brief step 4 "Probe shortcuts", reviewer brief item 1, README rule 13):** a probe or test that sets a field directly
(`db.set_value`, `db_set`, hand-assigned status) to stand in for a flow must say so. Any claim
built on it is unverified until the real flow reproduces the state. A reviewer who finds a
reachability claim resting on a direct write treats it as not established.

## Coordinator decisions worth knowing

- **Folded in, against "file it separately":** #1539 into #1528 (the fix was inert without it);
  #1540 into #1532 (the same literal on the same doctype); #1548 into #1544 (the same principle,
  and it made #1544 testable through the real flow).
- **Took out of a PR:** the cohort hunk in #1545 was reverted, with a coordinator-checked one-line
  delta, and became #1544 once it was shown reachable and in need of a product ruling.
- **Held from the queue:** #1552 conflicted with #1551 in `server-tests.yml`. It was queued only
  after #1551 merged and the author merged develop in, keeping both entries. The coordinator
  confirmed the PR's net diff against develop equalled the reviewed diff.
- **Coordinator-checked deltas, not sent for another review round:**
  - #1545 `8c92eefcc`: the one-line revert.
  - #1549 `59c3036da`: test file only; 10/10 on test_site_9.
  - #1552 `174f63d7f`: merge resolution; diff equal to the reviewed diff.
  - #1555 `833e7f4ca`: test file only; 58/58 on test_site_9.

## Process and coordinator notes

- **A reviewer stalled twice.** The #1544 round-2 reviewer backgrounded a long run and ended its
  turn. It was nudged, then stalled again. Its report never came back through the agent channel.
  The maintainer pasted it from the transcript: APPROVE, with a `>=` boundary gap and a corrected
  diagnosis (the author's "set to today" red run was `frappe.utils.getdate(None)` returning
  today, not a second writer). A fresh reviewer that had just been dispatched was stopped, and
  its clean worktree removed. **Lesson:** a notification saying "stopped with background work of
  its own still running" needs an immediate process check, not waiting. The coordinator missed
  this the first time.
- **The permission classifier blocked a push authorisation** because the reviewer's approval had
  arrived only as pasted text. The coordinator stopped and asked. The maintainer confirmed, and
  the message was then sent. That is the right outcome: an approval that reaches the coordinator
  only through a paste is not the coordinator's to act on without the user.
- **A reviewer used `git stash` once** (#1544 round 1). It disclosed this, and the stash stack
  was verified intact with its 2 foreign entries. The same agent's round-2 report says it used
  no stash.
- **veg11 has zero `Executed` Membership Termination Requests**, so every opposite-harm count for
  #1544/#1548 on real data is 0. Real data cannot settle that risk; it was settled from code and
  probes.
- **The order-dependence baseline cannot be grown by a PR** (step 2 reads the regenerated file).
  So a needed bare commit in a test has to be removed, not recorded. #1541 removed all 6.

## Filed this session, still open

- #1542: `test_quality_enforcer.py` cannot see a manual `module.attr = x` monkeypatch; only `unittest.mock.patch` calls.
- #1543: the Donor/SEPA Mandate/Address/Employee board list queries still match a disabled Chapter Member row.
- #1546: board-user identity resolution diverges: the list query falls back to email, `has_member_permission` uses `Member.user` only.
- #1547: `member_manager.add_member`'s re-enable branch restores `enabled` but not `status`.
- #1550: `test_workflow_path_filter`'s AST scan cannot see a `sys.path` insert plus a bare import.
- #1553: `TerminationMixin.update_termination_status_display` has the #1548 bug; it is dead but callable.
- #1554: `member_end_date` written by the Mollie sync or the reconstruction report is not cleared on rejoin.

**Also, handoffs:** PRs #1448, #1527 and #1538 are still open.

## Final state

- **Merged (PR → merge commit):** #1545 → `e81abc63b`, #1549 → `c704de771`, #1551 → `d3bd88cde`,
  #1552 → `2ab4de765`, #1555 → `501da7e78`. Each had full green CI and passed the `premerge.sh` gates.
- **Closed:** #1360 (verified on develop, closed by the coordinator); #1528, #1529, #1532, #1539,
  #1540, #1541, #1544 and #1548 (by merge).
- **veg11:** the tree is at develop `501da7e78`. The merged changes touch no DocType JSON, hooks,
  patches or fixtures, so no migrate was needed. Web and workers were restarted via `supervisorctl`
  (7 processes RUNNING). The HTTPS `/api/method/ping` returned 200, and the new code is loaded
  (`membership_application_review._refuse_if_terminated_after_application` exists).
- **Main tree:** `apps/verenigingen` is at develop `501da7e78` and clean.
- **Automerge:** finished with "ALL APPROVED PRs MERGED"; `approved_prs.txt` is empty.
- **Agents:** none running.
- **Worktrees:** this session's five issue worktrees are removed, with their merged branches. What
  remains: `handoff-0926`, `handoff-0926b`, `handoff-0927b` and `handoff-0928` (PRs open), and
  `issue-906` (PR #1201 open).
- **Stash stack:** exactly its 2 foreign entries.
