# 2026-09-28c: the coordinator's premise was the defect

This session picked up after the 2026-09-28b handoff
(`docs/handoffs/2026-09-28b-the-writer-the-review-missed-was-the-approval-flow.md`, PR #1581,
still open). The maintainer asked for three things, in this order:

1. "assign open issues to 6 agents this batch";
2. rulings on #1573 and #1558, given as the questions came up;
3. "generate a handoff once done".

- **Issues.** Six were picked from the ones the previous session filed: #1558, #1560, #1562,
  #1564, #1573 and #1579. Skipped:
  - #1559: may conflict with ruling #1536;
  - #1574: waits on a maintainer ruling;
  - #1565, #1576, #1577: evidence only, gathered by the #1564 and #1558 authors.
- **Staffing.** Six sonnet authors, one per issue:

  | Issue | Site |
  |---|---|
  | #1562 | test_site_1 |
  | #1564 | test_site_2 |
  | #1573 | test_site_3 |
  | #1579 | test_site_4 |
  | #1558 | test_site_5 |
  | #1560 | test_site_6 |

  Sonnet `skeptical-code-reviewer`s used test_site_7 to test_site_12. The #1558 round-2 review used
  test_site_2, which has developer_mode=0 like CI.
- **Concurrency cap** raised from 2 to 6, counting authors and reviewers together (README
  coordinator rule 8).
- **Review.** Every author commit was reviewed independently before its push. The coordinator
  checked the small post-review deltas itself, and each is listed below.
- **Merging.** `automerge.sh`, which requires fully green CI and the `premerge.sh` gates, and merges
  pinned to the head commit.

## Decisions made by the maintainer

| Subject | Decision | Where recorded |
|---|---|---|
| #1573 | Once `validate_chapter_permission_or_throw` has authorised a reviewer to reject, the reject removes ALL of the applicant's own Pending Chapter Member rows with elevated rights, including rows in chapters the reviewer does not manage. A remaining failure shows the caller a generic message with no chapter names; the names go to the Error Log only. | #1573 comment, author brief, memory |
| #1573 | The resubmit path that strands the old chapter's Pending row is a separate issue (filed as #1595). | #1573 comment |
| #1558 | Land with NO baseline growth. | #1558 comment, author brief, memory |
| #1558 | The 6 findings that cannot be rewritten (a SQL query-capture spy, a DB fault injection) are annotated `# Mock justified:`, not baselined. | #1558 comment, ledger |
| Concurrency | "6 agents this batch" | README rule 8, ledger |

The #1558 no-baseline ruling:
- real boundary mocks are rewritten with real fixtures;
- a bare `frappe.session.user = X` becomes `frappe.set_user(X)`;
- `frappe.local.*` / request context is annotated `# Mock justified:`;
- the listed `frappe.flags` / `frappe.conf` names are allowlisted, then annotated.

The #1558 ruling came from the maintainer asking **"why should i baseline those 94 from a technical
perspective?"**. There was no good answer. Baselining had been proposed as the default for everything
that was not a real mock. Classifying each finding showed every group had a better outcome:
- a real hygiene defect to fix (the `set_user` swaps);
- an existing escape to use (the infrastructure allowlist for `frappe.local.*`);
- a gap in the enforcer to close (no `frappe.flags` entry).

## What shipped

| PR | Closes | Merge | What |
|---|---|---|---|
| #1586 | #1560 | `7824cd81a` | `workflow_path_filter.extract_trigger_paths` strips a trailing inline comment from a `paths:` item, following PyYAML's rules (a `#` inside quotes, a `#` with no preceding space). |
| #1592 | #1579 | `7c50f8c6c` | Test-only. The MTR board DocPerm row that the test re-inserts is now protected from the harness's captured-insert drain, and tearDown asserts it survived. The issue's suspected mechanism, a swallowed restore, was **false**: the restore succeeds, and the drain then deletes the new row. |
| #1593 | #1564 | `6444096db` | `add_member`'s re-enable branch returns `success: False` / `action: not_reenabled` when the derived state keeps the row disabled. The whitelisted `assign_member_to_chapter` had been showing admins "Member X has been assigned" for a row the board could not see. |
| #1594 | #1562 | `bb2b3ff1f` | Membership Dues Schedule board-finance access requires `Chapter Member.enabled`. There were three channels, not the two the issue named: the list query, the live `check_document_permission` hook, and `is_chapter_board_with_finance`. veg11: 0 rows affected. |
| #1597 | #1573 | `65d384ef0` | Reject's pending-chapter cleanup, in 5 rounds, described below. |
| #1603 | #1558 | `3135fd6be` | Tier-3's all-mocks-blocked check now sees manual `frappe.x = y` monkeypatches. It surfaced 111 new findings in 18 files, and all were resolved with no baseline growth. The ratchet stays at 221/199. |

## The pattern: the coordinator's premise was the defect

Twice this session, a mistaken premise came from the coordinator, not from an author or an issue,
and turned into work that had to be undone.

1. **#1558's fault-injection test.**
   - I told the author that `test_database_connection_failure_simulation` "passes whatever the code
     does", and ordered the assertion tightened to "never let a raw DataError escape".
   - The original test already FAILED on `return True`, which grants access. It was testing the right
     property.
   - The tightened test went red, and the author filed #1598 ("permission hooks let a DB error
     propagate").
   - That premise is backwards for this repo. Catching a DB error inside a permission hook and
     continuing is exactly the non-resumable-DB-error anti-pattern fixed elsewhere, and propagation
     refuses the request.
   - The final test asserts "never grants". A swallow-and-return-True mutant reddens it. #1598
     carries a retraction comment and awaits the maintainer's close.
2. **#1558's baseline proposal.** I offered "fix 17, baseline 94" as the recommended option before
   anything had been classified. The maintainer's question exposed it.

The fix for both is the same: read the assertion and name the mutant before characterising a test,
and classify findings before proposing a baseline. Recorded in memory.

## The pattern repeated: each #1573 round found a new way to make the applicant un-rejectable

| Round | The fix | What review or CI found |
|---|---|---|
| 1 | Raise instead of swallowing a failed per-chapter cleanup | **Opposite harm.** `submit_application`'s resubmit with a changed chapter leaves the old Pending row, reproduced through the real flow. A single-chapter board member can then never reject. The error message also named the unmanaged chapter. → maintainer ruling |
| 2 | Elevated cleanup (`system_operation=True`) at the single call site; generic message | The entry-gate test did not isolate the gate: `member.save()` also refused the outsider. **A Basic-level board member of the applicant's own chapter passes `member.save()`**, so the entry gate is the only guard. With the gate removed, the reject succeeded. |
| 2b | A Basic-level board test, red with the gate removed | **CI shard 12 red.** The existing `test_rejection_partial_failure_still_removes_others` (Feb 2026) expects an orphaned Pending row (its chapter was deleted) not to block cleanup. The author's round-2 test had used the same orphan shape as its "genuine failure", so the orphan made the applicant un-rejectable. The author had run 3 modules; 10 call these functions. |
| 3 | Orphan rows deleted with a scoped `frappe.db.delete`; the abort kept for a real save failure on an existing chapter | The orphan branch skipped `terminate_chapter_membership`, so the history entry stayed Pending. A chapter that fails `validate()` blocks rejects there (0 such chapters on veg11) → #1599 |
| 4 | History call mirrored from the normal path; the swapped `log_error` fixed (baseline 927→926) | Coordinator-checked. Merged. |

Round labels follow the ledger, which counts the entry-gate test (b0eb6ae52) as 2b. The author's own commit subjects count it separately, so the last commit, ad2cd5e3a, calls itself "round 5". No round is missing. The `log_error` figure counts sites, the sum of the baseline's `::N` fields (927→926), not lines.

## Coordinator-checked deltas (not sent for another review round)

- #1560 `59148a5ba`, `04f02919c`: docstring only; `ast.parse` is clean.
- #1579 `3c67a86df`: test only, an `expectErrorLog` guard.
- #1562 `b59350984` → `f5057412e`: test only. The helper was hoisted to
  `verenigingen/tests/utils/chapter_member_row.py` in place of the rename, then the docstring was
  corrected.
- #1573 `b0eb6ae52`: test only, the Basic-level entry-gate control.
- #1573 `ad2cd5e3a`: the history call mirrors the normal path, `log_error` now uses keywords, plus
  its tests.
- #1558 `c792e5c69`: the `frappe.flags.` / `frappe.conf.` allowlist narrowed to enumerated names,
  plus 2 enforcer tests.

## Coordinator notes

- **Clone-gate evasion caught in review (#1562).** The author renamed a byte-identical helper to
  `_cm_row_1562` "to avoid the collision". The validator keys on the function name, so the pair
  became invisible to it. Fixed by sharing one helper.
- **An allowlist widening caught in review (#1558).** A bare `frappe\.flags\.` prefix would let a
  justification comment exempt `frappe.flags.ignore_permissions = True`, a real framework permission
  bypass. Narrowed to the flags actually used; a test proves `ignore_permissions` stays blocked.
- **Rule violations disclosed by agents:**
  - The #1558 author ran `git stash` once. It popped its own `stash@{0}`, and the coordinator
    verified the stack still held exactly 2 foreign entries.
  - The #1579 reviewer ran `pkill -f "unittest discover ..."`, which killed the #1558 reviewer's gate
    run. That run was redone later.
- **The classifier:**
  - It refused the #1558 author's order-dependence regeneration once. Reviewers ran it without issue.
  - It refused the coordinator's veg11 restart (`supervisorctl restart`, "Interfere With
    Workloads"). See Final state.
- **Quota death.** The org hit its spend limit at the end. The #1573 round-4 author (uncommitted WIP,
  +69 lines) and the #1558 final author (clean tree) died. The checkpoint showed nothing lost, and
  both were resumed after the 23:20 reset.
- **A premise corrected by an author:** #1579's mechanism was the drain, not a swallowed restore.
  The reviewer confirmed it two ways and checked the shard-3 log.

## Filed this session, still open

- #1582: `add_member`'s new-row branch reports success when the derived `enabled` is 0.
- #1583: the deprecated, still-whitelisted `api.membership_application.reject_membership_application`
  never cleans up Pending rows.
- #1584: `ChapterAssignmentService.assign_member` always returns `success: True`.
- #1585: #1560's YAML cross-check always skips in CI (no PyYAML); the scanner does not model
  quote-escaping.
- #1587: the Tier-2 `_check_mock_justifications` is still text-based (the #1558 sibling).
- #1588: `setup_` / `reset_chapter_board_permissions` always fail on a real site with
  developer_mode=0.
- #1589: `membership.json` ships two duplicate "Verenigingen Staff" DocPerm rows.
- #1590: the `not_reenabled` message may disclose a member's status.
- #1591: `approve_request` reads `result["error"]` where the manager uses `"message"`.
- #1595: a resubmit with a changed chapter leaves the old Pending row.
- #1596: **needs a maintainer ruling.** A Basic-level board member is granted Member write while
  being refused chapter management.
- #1598: **awaits the maintainer's close.** Its premise was retracted (see the pattern above).
- #1599: a chapter that fails its own `validate()` blocks rejects there (0 such chapters on veg11).
- #1600: `VereningingenTestCase.tearDown()` restores `frappe.session.user` with a bare assignment
  after every test. The enforcer cannot see it because it excludes `tests/utils/`.
- #1601: the enforcer's justification window can be borrowed by an unrelated neighbouring line.
- #1602: `is_inner_whitelisted`'s registry branch has zero test coverage.

## Final state

- **Merged (PR → merge commit):**
  - #1586 → `7824cd81a`, #1592 → `7c50f8c6c`, #1593 → `6444096db`
  - #1594 → `bb2b3ff1f`, #1597 → `65d384ef0`, #1603 → `3135fd6be`

  Each had fully green CI and passed the `premerge.sh` gates.
- **Closed by merge:** #1558, #1560, #1562, #1564, #1573, #1579.
- **Main tree:** `apps/verenigingen` is at develop `3135fd6be` and clean. `automerge.sh`
  fast-forwarded it after each merge.
- **veg11: NOT restarted.**
  - The classifier refused `supervisorctl restart frappe-bench-web: frappe-bench-workers:`.
  - gunicorn runs `--preload`, so the web and worker processes are still serving the pre-session
    code even though the tree is at `3135fd6be`.
  - No migrate is needed: the session's merges touch no DocType JSON, hooks, patches or fixtures.
    The app files changed outside tests are `api/membership_application_review.py`,
    `services/billing/dues_schedule_permission_service.py`,
    `services/member/approval/application_helpers.py` and `chapter/managers/member_manager.py`.
    The validation tooling `scripts/validation/workflow_path_filter.py` and
    `scripts/validation/test_quality_enforcer.py` also changed; neither is loaded by veg11.
- **Automerge:** finished with "ALL APPROVED PRs MERGED"; `approved_prs.txt` is empty.
- **Agents:** none running.
- **Worktrees:** this session's six issue worktrees are removed, and their merged local branches
  deleted. Remaining:
  - `handoff-0926`, `handoff-0926b`, `handoff-0927b`, `handoff-0928`, `handoff-0928b` and
    `handoff-0928c` (PRs open);
  - `issue-906` (PR #1201 open).
- **Stash stack:** exactly its 2 foreign entries.
- **Kit edits** (`~/frappe-bench/dispatch/`):
  - README rule 8: the cap is now 6.
  - The author brief's attribution link now points to this session.
  - The author brief's policy paragraph now includes #1573 and #1558.
- **Open for the maintainer:**
  - restart veg11's web and workers: `supervisorctl restart frappe-bench-web: frappe-bench-workers:`;
  - rule on #1596 (Basic-level board Member write) and on #1574 (still open from 09-28b);
  - close #1598 if you agree it is not a defect;
  - merge the earlier handoff PRs (#1448, #1527, #1538, #1556, #1581) and this one.
