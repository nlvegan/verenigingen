# 2026-11-01: the admin tests hid the board approver

This continues session `verenigingen-ed`, after `2026-10-31d-the-tests-pinned-the-path-we-removed.md` (PR #1923). Read that note first. This one covers only what changed afterwards. The session ended because its context was nearly used up. No agents are running.

## Maintainer rulings, NOT yet recorded anywhere else (record them first)

- **#1853: require the link.** `join_chapter` identifies the member by `Member.user` ONLY, with no `Member.email` fallback. A logged-in user with no linked Member is refused with a clear message. Also drop the #1786 `member_verified_by_caller` exemption for email-only matches.
- **#1894: wire it** (`transfer_member_between_chapters` into a real staff transfer action), UNLESS that duplicates existing logic. For example, if the normal chapter join/leave notifications already tell both boards about a transfer, delete the unused function and its transfer-only readers and templates instead. Check this first.
- **#1908: no.** A chapter-scoped approver may not assign a chapter it doesn't manage. Already commented on #1908, added to `dispatch/author_brief_common.md`, and implemented in PR #1932.
- **#1860:** "automerge when ready". PR #1932.

To do: comment both rulings on #1853 and #1894, add them to the policy list in `~/frappe-bench/dispatch/author_brief_common.md`, then dispatch authors.

## The lesson: every test ran as Administrator

#1862 (#1797) passed review twice and was in the merge queue. It moved the chapter assignment to after the member becomes Active, which left a `member.save()` running as the APPROVER on an Active member. A non-admin board member may write a Pending applicant but not an Active member, so every board-member approval with a chapter raised PermissionError after activation. All of #1797's tests and both reviewers' probes ran as Administrator. #1860's scoped-approver test found it.

Fix: def6ec420 persists only the stored `current_chapter` with `db_set`; it was reviewed and approved. **Rule: an approval/permission-path change needs at least one test as the least-privileged real caller (`create_test_board_member`), not only Administrator.**

## Other changes this stretch

- **#1887** (shard 10): two tests pinned the old "swallows errors" contract. Flipped; pushed.
- **#1893** (shard 7): `test_chapter_board_permissions` seated board rows with a standalone child insert, which no production path does. Moved to Chapter append+save. The test edit was independently reviewed, with a sync-skip mutant red. Filed #1922: an Administrator REST create of a standalone row skips the sync.
- **#1881** (shard 2) and **#1913** (shard 7): INFRA only (`apt-get update`: Ubuntu mirror unreachable; no test ran). Both were pulled from the queue. Background jobs in the dead session were waiting to `gh run rerun --failed`, and they died with it. **Re-run them by hand** (`gh run rerun <run> --failed` once the run is completed), then re-queue.
- **#1932 (#1860 + #1908):** an unknown chapter, or (for a scoped approver) an unmanaged one, is refused with ONE message ("Chapter X cannot be assigned"), closing the unpublished-chapter existence leak. The review page's default chapter prefers a managed one. The branch MERGES #1862's branch (stacked). The background job that would queue #1932 after #1862 merges died with the session: **append 1932 to approved_prs.txt by hand once #1862 is MERGED.**
- **Shared test helper** `tests/utils/guest_application.submit_application_as_guest`. It replaced copy-pasted Guest-submit helpers; renaming a copy only hid it from the duplicate gate.
- **`automerge.sh`** now refuses to merge a PR with zero registered checks (seconds after a push it read as mergeable).
- **Filed:** #1922, #1930 (a board-member approval reports success but creates no invoice, dues schedule or account; pre-existing).

## State at hand-off

- **Merged this session:**
  - 1845, 1847, 1849, 1854, 1857, 1861, 1863, 1864, 1871, 1872, 1882, 1884, 1889, 1892, 1895.
  - Also the 10-31d handoff #1923, if automerge reached it.
- **Queue (`~/frappe-bench/dispatch/approved_prs.txt`, shared with 2b):**
  - Mine: 1904, 1887, 1893, 1923, 1862.
  - 2b's: 1905, 1906, 1910, 1914, 1917.
  - **automerge.sh ran in session ed and stopped with it: restart it.**
- **Out of the queue:**
  - 1881 and 1913: infra rerun needed.
  - 1932: queue after #1862.
- **veg11:** last migrated at 1e118df29. It needs `migrate` once the queue drains, for the COR prune patches (#1872, #1913).
- **Test sites held by ed:** s6 and s8. Both are free now. s6 carries probe rows and a changed Administrator password.
