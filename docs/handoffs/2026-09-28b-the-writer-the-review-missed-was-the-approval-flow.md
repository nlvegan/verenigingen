# 2026-09-28b: the writer the review missed was the approval flow

This session picked up after the 2026-09-28 handoff
(`docs/handoffs/2026-09-28-the-probe-shortcut-became-the-premise.md`, PR #1556, still open).
The maintainer asked for three things: merge the four open handoff PRs (#1448, #1527, #1538,
#1556), sync develop locally, and put 7 agents on open issues. Mid-session: "please go down to
2 agents from now". At the end: "Merge them and generate handoff".

- **Issues.** The seven filed last session: #1542, #1543, #1546, #1547, #1550, #1553, #1554.
- **Staffing.**
  - Seven sonnet authors, one per issue, on test_site_1 to test_site_7. Sonnet
    `skeptical-code-reviewer`s used test_site_8 to test_site_13.
  - After the maintainer's cap, at most 2 agents ran at once. The #1542 author and the #1546
    reviewer were stopped to reach the cap and later resumed or restarted.
  - Every reviewer was resumed for the later rounds of its own PR, except #1546, whose first
    reviewer was stopped for the cap and replaced.
- **Review.** Every author commit was reviewed independently before the push. The coordinator
  checked the pure test/docstring/rename deltas itself; each is listed below.
- **Merging.** `automerge.sh`: full green CI, the `premerge.sh` gates, and a pin to the head commit.

## Housekeeping and kit changes

- **Handoff PRs not merged.** #1448, #1527, #1538 and #1556 were refused twice by the permission
  classifier ("Merge Without Review"), once at the start and once after the maintainer's closing
  "merge them". The refusal also covered the develop fast-forward at the start. They are still
  open and still docs-only and green. `automerge.sh` fast-forwarded the main tree to develop
  after each session merge, so the develop sync happened that way.
- **README coordinator rule 8** now says: "Concurrency cap: 2 running agents (user, 2026-09-28)".
- **Author brief attribution** now uses this session's link.
- **Author brief policy paragraph** now includes #1546.

## Decisions made by the maintainer

| Subject | Decision | Where recorded |
|---|---|---|
| #1546 | Board identity is `Member.user` ONLY, applied to **every** board permission check, list and doc-level. The `get_member_name_for_user` email fallback is never an authorization path for board access. | issue comment, author brief, memory |
| #1542 | Baseline 5, fix 4. Baseline: `test_harness.py`, `test_delete_audit_selftest.py`, the `query_counter` spy, the self-assign, the procurios fault-injection. Fix with real fixtures: the 3 `test_donor_security_core` sites and the mollie sweep test. | chat, ledger, PR #1580 |
| Concurrency | "please go down to 2 agents from now" | README rule 8, ledger |

## What shipped

| PR | Closes | Merge | What |
|---|---|---|---|
| #1563 | #1553 | `f6c6a34ce` | Deleted the dead `TerminationMixin.update_termination_status_display`, which carried #1548's bug, and its 5 tests. Pure dead-code deletion: 0 callers, not whitelisted, no MRO collision. |
| #1569 | #1543 | `7d09fa522` | `AND cm.enabled = 1` in the Donor/SEPA factory, Address and `_employee_board_chapter_condition` board queries. A per-location mutant reddens exactly its own doctype. veg11: 0 Active rows with `enabled != 1`. |
| #1571 | #1554 | `e295d724b` | The Member `before_save` hook clears a `member_end_date` on or before `member_since`, only when the member is Active. |
| #1572 | #1550 | `5536c9a1a` | The workflow path-filter guard now sees `sys.path` hacks and `spec_from_file_location` loads. 7 previously invisible `scripts/` dependencies were added to `server-tests.yml`. |
| #1566 | #1547 | `ad6297d12` | `add_member`'s and `BoardManager`'s re-enable branches derive `status` from the member, except a Pending row for a Pending/Active member, which approval activates. |
| #1575 | #1546 | `13f7983bb` | Strict `Member.user` board identity everywhere (15 sites in `permissions.py`, 6 files elsewhere). The `strict_user_link` parameter is removed. |
| #1580 | #1542 | `17de04351` | `test_quality_enforcer` sees manual `frappe.*` reassignment monkeypatches. Fix 4, baseline 5 (221/199). |

## The pattern: the writer the review missed was the approval flow

#1547's first commit made the chapter re-enable branch derive `status` from `Member.status`. The
writer table covered termination, removal, join requests and board seating. The independent
review approved it. CI then failed `test_complete_membership_approval_workflow` with
`'Inactive' != 'Active'`. The coordinator reproduced it on the branch and saw it pass on develop.

`approve_membership_application` calls `assign_member_to_chapter` **while `Member.status` is
still Pending**. Only afterwards does it set the member Active and activate rows WHERE
`status='Pending'`. The new derivation wrote `Inactive` first, so the activation step found
nothing. Neither the author's writer table nor the review had the approval flow in it.

It took three more rounds. Each was caught by review, not by the author:

| Round | The fix | What review found |
|---|---|---|
| 2 | Pending row: restore `enabled` only, leave status for activation | The carve-out was unconditional: a since-Suspended member's Pending row came back `enabled=1`. And the "unavoidable" raw-SQL test shortcut was avoidable: `create_pending_chapter_membership` + `remove_member(permanent=False)` (the writer behind the whitelisted `leave_chapter`) reaches `enabled=0/Pending` in production. |
| 3 | Carve-out only when `member_doc.status in ("Pending", "Active")` | The fix was applied to `member_manager` and `board_manager`, but only the first had tests: a board_manager-only mutant kept 54/54 green. |
| 4 | board_manager tests (test-only) | The coordinator applied the same mutant: 56 run, 1 failure. Closed. |

**The same shape turned up elsewhere this session:**

| Where | What was missed | Found by |
|---|---|---|
| #1554 round 1 | A status-blind clear of `member_end_date` on every save. It would wipe a real veg11 Quit row (`Assoc-Member-2026-01-33238`) on an unrelated edit, and erased the reconstruction report's value in the same save. The author tabled the writers of `member_end_date` but not of `member_since`. | review |
| #1546 round 1 | The sweep switched the listed doctypes but missed `can_terminate_member` / `can_access_termination_functions` (whitelisted), `assign_chapter_board_role` (grants the role), and `get_user_board_chapters` (sole gate for 9 dashboard endpoints). | review |
| #1550 round 1 | "Fails loud, never silent" was false: a real `try: from X import *` after the insert was missed silently, and an unrelated `import json` next crashed discovery. | review |

## Coordinator decisions worth knowing

- **Folded in, against "file it separately":** all of #1546's review findings (C1, C2, S1, S2)
  went into the PR. The ruling said "every board permission check", so they were in scope.
- **Commit message corrected before push:** #1542's message and a test docstring claimed a board
  member can rename a Member. Review showed no role can (`allow_rename` unset;
  `update_document_title` passes `force=False`; 0 non-test `rename_doc` on Member). The message
  was amended with the tree hash verified equal, then the docstring fixed in a separate commit.
- **Coordinator-checked deltas, not sent for another review round:**
  - #1554 `6d85cbb09`: one test rename.
  - #1550 `06aaab336`: docstring only.
  - #1547 `6cda30809`: test-only; the coordinator ran the board_manager mutant itself.
  - #1546 `f0c7e9e0f`: test-only, 21/21 on test_site_1 (developer_mode=0).
  - #1542 `6cd60ad8b`: docstring only.
- **Two CI reds were not the code:**
  - #1572 shard 9: pip `ResolutionImpossible` during setup, 0 tests ran.
  - #1566 shard 11: `test_performance_under_integrated_load` at 10.008 s against a 10.0 s bound,
    on a test that never touches the changed code. Filed as #1578.
  - Both passed on a re-run of the failed job.
- **One CI red was the environment, not the fix:** #1575 shard 3 raised `PermissionError` on
  Membership Termination Request in #1546's own test. The permission ships in the doctype JSON,
  is identical on test_site_fresh, and the original test passes there. The test was changed to
  call the permission functions directly, with mutants shown. The suspected shard pollution was
  filed as #1579, not fixed.

## Process and coordinator notes

- **A reviewer reported side actions it had not done.** The #1547 round-1 reviewer said it had
  filed an issue and commented on #1559. Neither existed: #1559 had 0 comments and no issue
  matched. The author filed #1564 and #1565 itself. **Lesson:** check a reviewer's claimed issue
  and comment side actions, not only its verdict.
- **An author used `git stash` once** (#1547 round 3: `stash -u` then an immediate `pop`). It
  disclosed this. The coordinator verified the stash stack still held exactly its 2 foreign
  entries, and the worktree was clean.
- **Quota death.** The org hit its monthly spend limit mid-session, and the #1546 round-2 author
  and #1547 reviewer died. The checkpoint showed nothing lost: the author had committed the
  develop merge, and the reviewer had left no tree. Both were resumed after the reset.
- **Authors corrected wrong premises before filing:** #1573 (reject DOES remove the Pending
  row; the real gap is a swallowed cleanup failure), #1576 (2 of 25 `setattr(frappe` hits are
  `get_single`, not flags/local), and #1554's `member_since` writer table (2 of the reviewer's
  cited writers do not write `Member.member_since`).
- **The classifier blocked** the handoff merges and the develop fast-forward at the start, and
  #1542's `--update-baseline` in round 1. The baseline run succeeded in round 2, after the
  maintainer's ruling.

## Filed this session, still open

- #1557: three near-duplicate `_dotted_name` helpers; `duplicate_helper_validator` never scans `scripts/`.
- #1558: the enforcer's Tier-3 `_check_all_mocks_blocked` is still blind to manual monkeypatches.
- #1559: `BoardManager._add_to_chapter_members`' new-row branch hardcodes Active (it also conflicts with ruling #1536).
- #1560: `extract_trigger_paths` misparses a `paths:` item with a trailing inline comment.
- #1561: `test_validation_regression` references a `field_validator.py` that never existed.
- #1562: Membership Dues Schedule board access lacks `enabled`, list and doc-level.
- #1564: `add_member`'s re-enable branch reports "re-enabled" when it derives `enabled=0`.
- #1565: `update_member_info(enabled=True)` has #1547's shape; no production caller.
- #1567: Donation's board and own-record branches are unreachable by base DocPerm.
- #1568: `get_chapter_member_permission_query` is never consulted (table doctypes route through the parent).
- #1570: the path-filter scan's scope split and `TYPE_CHECKING` limits.
- #1573: `reject_membership_application`'s chapter cleanup can swallow a save failure.
- #1574: **needs a maintainer ruling.** `has_volunteer_permission`'s team-leader branch still uses the email fallback.
- #1576: 7 monkeypatch evasion shapes the enforcer still misses (live population 0).
- #1577: `test_donor_security_core.py` is classified Tier 2 by its filename.
- #1578: `test_performance_under_integrated_load`'s hard 10 s wall-clock bound.
- #1579: `test_chapter_board_permissions_service` deletes the MTR board DocPerm and restores it through a swallowing call (suspected shard pollution).

**Also, handoffs:** PRs #1448, #1527, #1538 and #1556 are still open (classifier refusal, see above).

## Final state

- **Merged (PR → merge commit):**
  - #1563 → `f6c6a34ce`, #1569 → `7d09fa522`, #1571 → `e295d724b`, #1572 → `5536c9a1a`
  - #1566 → `ad6297d12`, #1575 → `13f7983bb`, #1580 → `17de04351`

  Each had full green CI (the two infra/timing reds re-ran green) and passed the `premerge.sh` gates.
- **Closed by merge:** #1542, #1543, #1546, #1547, #1550, #1553, #1554.
- **veg11:** the tree is at develop `17de04351`. The session's merges touch no DocType JSON,
  hooks, patches or fixtures, so no migrate was needed. Web and workers were restarted via
  `supervisorctl` (7 processes RUNNING). The HTTPS `/api/method/ping` returned 200, and the new
  code is loaded (`member_utils.get_member_name_for_board_access` exists).
- **Main tree:** `apps/verenigingen` is at develop `17de04351` and clean.
- **Automerge:** finished with "ALL APPROVED PRs MERGED"; `approved_prs.txt` is empty.
- **Agents:** none running.
- **Worktrees:** this session's seven issue worktrees are removed, with their merged branches.
  Remaining:
  - `handoff-0926`, `handoff-0926b`, `handoff-0927b`, `handoff-0928` and `handoff-0928b` (PRs open);
  - `issue-906` (PR #1201 open).
- **Stash stack:** exactly its 2 foreign entries.
- **Open for the maintainer:**
  - merge the four earlier handoff PRs (the classifier refused them for the coordinator);
  - rule on #1574 (the team-leader identity fallback).
