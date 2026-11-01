# 2026-10-31d: the tests pinned the path we removed

Session `verenigingen-ed` (coordinator). The maintainer asked, in order:
- "work on #1797, put agents on 8 more issues";
- "are there any free sites? If so, run as many new agents as there is room";
- "merge when green" (standing).

Two other coordinators were live the whole time:
- `verenigingen-2b`: #1765 application-as-record, test_site_5 and test_site_12, later also sites 1/2/4/9/11 for its own round.
- `aanmeldformulier` (session name `verenigingen-e4`): Ponto/webhook work, test_site_3/7/10/13.

Sites and issues were agreed by message before every dispatch, and recorded in `~/frappe-bench/dispatch/ledger.md` under `[2026-10-31 ed]`.

## What shipped

Every PR had an independent `skeptical-code-reviewer` on the exact SHA before its push. Every verdict was APPROVE WITH NITS, or CHANGES REQUIRED followed by a delta review.

| Issue | PR | What | State at hand-off |
|---|---|---|---|
| #1797 (coordinator) | #1862 | approval assigns the reviewer's chapter AFTER the member is Active; a chapter the approval could not assign is logged (Error Log) | queued |
| #1798 | #1845 | board "member joined" only when the new row is enabled; 3 debug `print`s removed | MERGED |
| #1789 | #1847 | the link-validation retry restores links Frappe blanked; no-op bypass removed from `save` sites | MERGED |
| #1788 | #1849 | the ACR batch wait loop counts on a fresh connection (stale REPEATABLE READ snapshot) | MERGED |
| #1811 | #1854 | request-scoped guard: PDA status Active only via the workflow; button hidden while a workflow is active | MERGED |
| #1786 | #1857 | a Chapter Join Request may name only the caller's own Member (`Member.user`) or come from ADMIN_ROLES | MERGED |
| #1802 | #1861 | db_clock `explain_shrink` no longer blames the survivor of a partial fix | MERGED |
| #1665 | #1863 | test Role deletes remove `Has Role` grants first (Refs only; drains are #1856) | MERGED |
| #1793 | #1864 | `assign_with_cleanup` runs cleanup + add in one savepoint; 1205 rolls back then re-raises | MERGED |
| #1578 | #1871 | wall-clock bound replaced by a query budget (drain clock pinned) | MERGED |
| #1517 | #1872 | unchecked `get_suspension_status` deleted, plus COR prune patch | MERGED |
| #1785 | #1882 | 38 setUp patch starts get `addCleanup`, plus a ratchet | MERGED |
| #1513 | #1884 | order-dependence scan sees implicit-commit DB calls (baseline +4 real findings) | MERGED |
| #1758 | #1881 | harness mirrors CI's mail conf in-process when the site has no outgoing account | queued |
| #1662 | #1887 | install steps raise instead of swallowing, so the runner records them | queued |
| #1694 | #1889 | national-board tests clean up the Employees the profile sync creates | queued |
| #1877 | #1892 | `len(d.get(k) or "")` in the chapter validator (3 sites) | queued |
| #1672 | #1893 | the refused direct board-role grant is removed; the board flush re-raises lock errors | queued |
| #1846 | #1895 | `transfer_member_between_chapters` runs leave + join in one savepoint | queued |
| #1856 | #1904 | test drains route Role deletes through `delete_role_and_grants` | queued |
| #1866 | #1913 | unchecked `get_suspension_list` deleted, plus COR prune patch | queued |

Not pushed: **#1860** (maintainer ruling: refuse an approval naming a nonexistent chapter). It is reviewed and committed locally in `~/agent-worktrees/fix-1860-refuse-unknown-chapter` (6090d48f1 and ba0fcff21), with a module-level `_refuse_unknown_chapter` that 2b's #1765 will reuse. **It must wait for #1862**, then be rebased, and #1862's `test_an_assignment_the_approval_could_not_make_is_logged` (unknown chapter, expects success) must be flipped to expect the refusal in the same PR. Ping 2b when it merges.

## The lesson: when you remove a path, the tests that drove it are callers too

Four PRs went red in CI after review, all for the same reason: a test depended on something the fix changed, and the review sweep was keyed on production callers.

- **#1893** removed the board row's own after_insert/on_update role grant. `test_chapter_board_permissions` seated board members with a **standalone** `Chapter Board Member` insert, which ran that hook. No production path does this (`frappe.client.insert` routes a child row through the parent's save). The fix moved the tests to Chapter append+save. A sync-skip mutant proves they now pass through the real path.
- **#1887** made install steps raise. `test_setup_termination` had two tests named `*_swallows_*` that asserted the old contract.
- **#1862** and **#1881** pinned ambient LOCAL state, not CI's:
  - `suggest_chapter_for_member` matches on the applicant's CITY. CI shards carry `Test Amsterdam Chapter`, so a test applicant from "Amsterdam" got a chapter at submit.
  - CI's site_config already has `mail_server=localhost`, so "conf is None after cleanup" was false there.

The dispatch brief already said "a changed return contract needs a grep of the TESTS for the old outcome". It was skipped in two of these four. **Rule: when a fix removes or changes a path (a hook, a swallow, a grant), grep the tests for every way they REACH that path, not only for assertions on its outcome.** Both CI-environment facts are now in `author_brief_common.md` and `reviewer_brief_common.md`.

Every one of the four was reproduced locally before the fix, by recreating the CI condition (a committed matching chapter; `mail_server` in a site config; the standalone-insert shape on the branch).

## What review caught before push

These are worth knowing as patterns.
- **#1672:** the first fix let a Chapter save succeed after a deadlock in the role sync, because the sync swallows 1213/1205 for event-driven callers. The board path now passes `reraise_non_resumable=True`. Other callers are #1888.
- **#1797 (mine):** I claimed the only non-success an approval reaches is the benign `already_exists`. The reviewer approved with a nonexistent chapter and showed a silent success. This led to the logging and to #1860's ruling.
- **#1793:** a real 1205 (second connection holding FOR UPDATE) proved the half-applied state; the fix rolls back to the savepoint before re-raising.
- **#1662:** the author's "workflow setup returns False on a healthy site" was false (it returns True); False is now a failure.
- **Hollow tests:** several were caught by mutants.
  - #1798 used an always-True guard.
  - #1786's board test had a role but no real seat.
  - #1811 used a bare `assertRaises(ValidationError)`.
  - #1694's nested guard re-ran a flaky test.
  - #1785's ratchet was lenient.
  - #1758's cache clear was untested.

## Process notes

- `gh issue view N --comments` prints NOTHING for an issue with 0 comments (comments only, no body). That is not a tool failure; use `--json body`.
- A reviewer ran `git stash` in its own detached tree. The reviewer brief now bans it explicitly in every worktree.
- One author (#1672) repeatedly stopped "waiting on its own background work" without reporting. The coordinator stopped it and finished its review round and push by hand.
- `approved_prs.txt` is now shared with 2b. Append with `sed -i '1s/$/ N/'`, never read-modify-write.
- A red PR stops automerge for the whole queue. Pull it, then restart the loop; the loop runs in whichever session started it.

## Issues filed this session

#1842, #1843, #1844, #1846, #1850, #1852, #1853, #1856, #1858, #1859, #1860, #1865, #1866, #1879, #1880, #1886, #1888, #1891, #1894, #1908, #1911, #1922.

Decisions waiting on the maintainer:
- **#1908:** may a chapter-scoped approver assign a chapter it doesn't manage? The #1860 message also reveals unpublished chapter names.
- **#1853:** `join_chapter`'s email fallback.
- **#1894:** the transfer path is test-only.
- **#1842/#1843:** board and welcome notifications.

Security, unfixed: **#1911**. `get_suspension_preview` gives a HIGH-tier scoped board member data about members outside their chapter.

## State at hand-off

- Queued in `approved_prs.txt`: #1862, #1881, #1887, #1889, #1892, #1893, #1895, #1904, #1913, plus 2b's #1905/#1906/#1910/#1914/#1917. `automerge.sh` runs in session ed.
- veg11 was fast-forwarded and migrated at the start of the session (at 1e118df29), not since. The merged PRs include two COR prune patches (#1872, #1913 once it merges), so veg11 needs `migrate` after the queue drains.
- Test sites:
  - test_site_8 holds ed's #1860 work.
  - test_site_6 carries reviewer probe rows and a changed Administrator password.
  - test_site_fresh had verenigingen uninstalled and reinstalled by the #1662 reviewer.
