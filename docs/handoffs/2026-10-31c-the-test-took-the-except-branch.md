# 2026-10-31c: the test took the except branch

Session `verenigingen-0c`. The maintainer's instruction, in full: "please pick 8 issues for agents to
work on; order skeptical reviews once they're done, then iterate until approved, push, merge when CI
goes green, then write a handoff".

Coordinator plus 8 sonnet authors and 9 sonnet `skeptical-code-reviewer`s, briefed from
`~/frappe-bench/dispatch/`. Two other coordinators were live the whole time (`verenigingen-6c`:
#1765/#1782/#1776, test_site_1/5/11/12; `aanmeldformulier`: #1779). Sites and issues were agreed with
both by message before anything was dispatched; nobody shared a site.

## The eight issues

Picked for: no open PR touching the same files (PR #1776 owns the approval/billing files, so #1732,
#1774 and #1583 were skipped), no product decision needed (#1686 skipped), premise not already walked
back (#1598, #1681, #1738 skipped), not claimed by a peer (#1773-#1778, #1765, #1740).

| Issue | PR | What | State |
|---|---|---|---|
| #1700 | #1791 | Ship the 5 Workflow Action Masters the Periodic Donation Agreement Workflow uses (a Workflow re-save raised LinkValidationError without them) | MERGED |
| #1739 | #1792 | `_build_approval_response` reads `action`/`account_request` from `meta`; approvals said "pending" for every queued account | MERGED |
| #1669 | #1795 | 4 `secure_document_operation` sites ask for `bypass_validations` only when `can_use_bypass_validations()`; Treasurer/NBM writes were refused (fee history silently stale, invoice retry/manual-review flag lost) | MERGED |
| #1744 | #1790 | ACR bulk wait loop counts `Processing`, not the non-existent "In Progress" | MERGED |
| #1745 | #1794 | Chapter Join Request review trail (`reviewed_by`, `review_date`, `review_notes`, `rejection_reason`) can only be written by approve/reject | MERGED |
| #1631 | #1796 | `ChapterMembershipManager` copies `message` into `error` on failure; `not_reenabled` reason scrubbed for a caller who cannot read the Member | MERGED (also closes #1110) |
| #1584 | #1799 | `ChapterAssignmentService.assign_member` reports a refused add as `success: False` and writes no tracking/comment for it | MERGED |
| #1582 | #1800 | `add_member`'s new row reports `added_disabled` (success False) when the row came out disabled; status gated (#1590) | MERGED |

Every PR had an independent review of the exact SHA before its push; every verdict was APPROVE WITH
NITS, and every nit was fixed or dispositioned in the PR body.

## What the reviews found (beyond nits)

- **#1744 is correct but inert in production**: the wait loop polls on one connection in one
  REPEATABLE READ snapshot and never sees the workers commit, so every batch already waits the full
  600 s. Two-connection probe + real-loop probe (200 ticks). Filed **#1788**.
- **#1700's test committed invisibly**: `frappe.core...data_import.import_doc` runs an unconditional
  `frappe.db.commit()`. No gate sees it (they match the literal `frappe.db.commit()`). The test now
  inserts the fixture rows without the importer.
- **#1745**: `""` vs NULL counted as a change (fixed with `cstr` compare). `flags` cannot be set by a
  client (frappe strips them at `api/v1.py:55`, `client.py:313`, `api/v2.py:201`).
- **#1669**: at the two `save` sites the link-validation retry never fires (it exists only for
  `update_child_table`). Kept anyway: for a System Manager the argument still drives the audit row and
  the post-save `verify_document_integrity` check. Filed **#1789** (the retry fails for a deleted
  Chapter even for SM).
- **#1584**: a refused add could read "Member added successfully" (fixed). `assign_with_cleanup`
  removes the member from their old chapters BEFORE the add, so a refused add strands them in none.
  Filed **#1793**.
- **#1582**: approved members can end up with a DISABLED chapter row: approval assigns the chapter
  while `Member.status` is still Pending, and `_activate_pending_chapter_memberships` only flips rows
  whose status is "Pending". Pre-existing, driven through a real submit+approve. Filed **#1797**.
  Board "member joined" notification fires for a disabled row, plus a stray debug `print` in
  `communication_manager.py:232`: **#1798**.
- Four separately-written "only tell a Member-reader the status" helpers now exist (#1591's plus one
  per PR here). Filed **#1801** to consolidate after the three PRs merge.
- Authors filed **#1784** (donation workflow cannot leave Draft: `Pending Verification` is not a
  `status` option) and **#1786** (a plain Member can open a submitted join request for another member).

## The lesson: a test's `except` branch can be the only branch that ever ran

#1799 went red in CI on `test_member_status_transitions::test_chapter_transfer_status_rules`, a test
nobody had touched. It was written as "either the transfer is allowed (assert the rows) or it is
prevented (`except frappe.ValidationError: pass`)". On develop the service reported **success** for a
Suspended member, and the test's own next line, `member.save()`, raised `TimestampMismatchError`
(the service had re-saved the Member underneath it). `TimestampMismatchError` IS a `ValidationError`,
so the test logged "prevention is a valid business rule" and passed. The "allowed" branch, which
queried a column that does not exist (`Chapter Member.chapter`), had never executed. The fix made
the service return honestly, the stale save went away, and the dead branch ran for the first time.

The coordinator first wrote the author "on develop the service raised ValidationError". That was
inferred from the test passing, not measured, and it was wrong; the author's probe and then the
reviewer's corrected it. Both "either/or" transition tests now assert the actual rule.

**Rule**: a test that accepts "X happened OR exception E was raised" proves nothing until you know
which branch ran. If E is a broad base class (`ValidationError` covers TimestampMismatch, Mandatory,
Link, DataError...), assume the except branch is catching something incidental. Grep for
`except frappe.ValidationError:` followed by `pass` in tests around the code you change.

## Other process notes

- **Two pushes were refused by the pre-push cache-guard** (`has_permission` read before `set_user`,
  stale permission cache). Both were authored by agents that had run the full self-review; the guard
  is push-only, so the self-review checklist should name it. Coordinator moved the reads after the
  switch and re-ran.
- **#1796 reddened on the log_error ratchet** because #1631 fixed a swapped `log_error` call that was
  baselined (dispatch rule 16). The shrunk baseline line was committed; only that line.
- **#1800 reddened on a fixture** that asserted the old `add_member` contract (success for a
  Suspended new row). A contract change needs a grep of the tests for the old OUTCOME, not only the
  callers; the author ran ten sibling modules and missed this one.
- **#1796 reddened a second time on "Every shrink was actually a fix"**. That was a bug in the gate,
  already filed as #1110: after a PARTIAL fix (2 -> 1), `explain_shrink` blamed the still-counted
  surviving call as "[unscanned] the file left SCAN_ROOTS". The fix (14b684e61) went to its own
  independent review because it makes a gate report less. That review ran a 15-case abuse matrix and
  found two LOOSENING mutants surviving (no test covered the `unscanned` branch); 2a1273723 pins it.
  Sibling with the same shape in `db_clock_date_window_validator`: **#1802**.
- **develop was red most of the session** on #1770's `test_the_31st_call_through_the_real_decorator_is_not_refused`
  (#1782; fix #1787, owned by `verenigingen-6c`). Every PR whose shard packing included it went red
  on that one test. Re-running a job does NOT pick up a later develop merge (it reuses the PR's merge
  ref); `gh pr update-branch` does. On the maintainer's okay (with 6c's consent) this session merged
  #1787, then updated #1790/#1794/#1800.
- One infra red: #1792's "JS Coverage → Codecov" died in `npm install` with `EEXIST` on the runner's
  npm cache. `gh run rerun --failed` only works once the whole run has finished.
- The pre-existing duplicate-helper drift (`_clear::2`, `_key::2`) showed up in every regeneration;
  no PR committed it (#1421 class).
- `ci_watch.sh` re-emits on every count change while a PR carries any failure, so one infra red made
  it fire every two minutes. `~/frappe-bench/dispatch/ci_watch_quiet.sh` (added this session) emits
  only a NEW failed check name and once when nothing is pending.
- The same except-swallow shape is still in CI logs elsewhere: a volunteer edge-case test prints
  "✅ Extreme date range properly rejected: ... has been modified after you have opened it". That is a
  TimestampMismatchError reported as a business rejection. Not investigated.

## Standing instruction added this session

**"Merge when green unless you've discovered breaking issues"** (maintainer, 2026-10-31). Recorded at
the top of the coordinator rules in `~/frappe-bench/dispatch/README.md`. Green means every check
passes after review and `premerge.sh`; someone else's develop red is not green, and a PR owned by
another session still needs the maintainer's say-so.

Dispatch kit also gained two author self-review items: the push-only cache-guard, and "a changed
return contract needs a grep of the TESTS for the old outcome".

## State at hand-off

- All 8 PRs merged: #1791, #1792, #1795, #1799, #1796, #1800, #1790, #1794 (plus 6c's #1787).
  Closed: #1700, #1739, #1669, #1584, #1631, #1110, #1582, #1744, #1745.
- **veg11 deployed**: backup `20261031_101922`; live tree fast-forwarded to `d4deb1006` (local
  `email_brand.css` edit and untracked `ONBOARDING.md` left alone); `migrate` exit 0; no bundle
  changes, so no build; `bench restart`. Smoke test: `ping` gives pong, `/word-lid` returns 200, all
  5 Workflow Action Masters are present, and the 4 CJR review fields are `read_only=1`.
- No agents running; this session holds no test sites. Worktrees under `~/agent-worktrees/fix-<n>-*`
  can be removed.
- Filed this session: #1784, #1786, #1788, #1789, #1793, #1797, #1798, #1801, #1802.

## Next

- #1788 (wait loop stale snapshot) makes #1744 effective; needs a red test with a second connection.
- #1797 (approved members with a disabled chapter row) is the most user-visible finding of the round.
- #1801 (consolidate the four Member-read-gated reason helpers) is unblocked: all three PRs merged.
- #1802 (port the #1110 explainer fix to the db_clock validator, with its tests).
