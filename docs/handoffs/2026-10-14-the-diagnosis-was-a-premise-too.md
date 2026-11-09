# 2026-10-14: the diagnosis was a premise too

This session (verenigingen-74) started from the 2026-10-13 handoff (PR #1675). The maintainer's
instructions, in order:

1. "merge 1675 as is, then let's start work on open issues plus on adding a nightly run for this
   calculator" (the role-profile calculator).
2. Rulings on #1650, #1626, #1676, the Membership-permission question (below).
3. "repair that site, password is in memory" (test-site reset).
4. "merge 1677 when green"; then "merge 1676 too when it's approved and green"; then "merge the
   other PRs too when approved and green".
5. "once all work is skeptically reviewed and CI greens, merge, then write a handoff".

Coordinator plus sonnet authors and sonnet `skeptical-code-reviewer`s, briefed from
`~/frappe-bench/dispatch/`. Every PR had at least one independent review before it was pushed;
#1676 took three, #1659 three, #1670 three, #1642 two plus a post-approval delta review, #1650 two.

## Decisions made by the maintainer

All recorded on the issue named.

| Subject | Decision | Where |
|---|---|---|
| Chapter Admin vs financial | Admin does **not** imply financial rights; only `permissions_level = Financial` | #1650 |
| General Admin chapter powers | Unchanged (add board members, manage members, accessible chapters, project levels) | #1650 |
| National treasurer routing | Any claim with no chapter/team Financial approver goes to the national board's Financial seat | #1650 |
| No Financial approver anywhere | Claim stays **unassigned**; nobody auto-granted Expense Approver; no newest-user fallback | #1650 |
| Daily approver refresh | When no Financial approver exists, `Employee.expense_approver` is left as is (manual values survive) | #1650 |
| `national_board_chapter` | Only the **Verenigingen Administrator** role (VA + Verenigingen System Administrator profiles); bare System Manager may not | #1626 |
| Nightly sync: direct roles | The nightly job keeps roles held outside profiles; the event path keeps its replace (#1293) | #1676 |
| Nightly sync: no record | No strip without a sync-granted record; writes a record only if it **added** a profile | #1676 |
| Legacy record-less users | Accepted as is (~438 veg11 Volunteer holders keep Volunteer until an event touches them); no cleanup command | #1676 |
| veg11 seat data | Maintainer configures seats/national chapter himself; code ships without data changes | #1650 |

**Coordinator decisions, not ruled by the maintainer** (stated so they can be overruled):
team bulk-assign delegates to the role-profile sync like chapter bulk (#1659); a creator account is
identified by role AND the `public-creator(-N)@` address (#1670); `read` is never lowered while a
`CORE_GRANTS` tuple stays declared (#1642).

**Answered without code:** "add Membership create/edit for Staff" — Staff already has
create/write/submit/cancel/amend on Membership (measured with a real Staff-profile user). The two
level-0 Staff rows the maintainer saw on another instance are the read-only twin removed from the
JSON in #1589, frozen into that site's Custom DocPerm set; rights on one (role, level) are OR'd, so
the twin removes nothing. That instance's list also lacked the Verenigingen Member (if_owner) row —
not explained; check there.

## What shipped (merged to develop)

| PR | Closes | What |
|---|---|---|
| #1675 | — | Previous session's handoff |
| #1677 | #1626 | `national_board_chapter` changeable by the Verenigingen Administrator role only |
| #1683 | #1678 | Dues-split admin test seeds its own chapter instead of asserting an empty global report |
| #1691 | #1659 | Unused `assign_chapter_board/team_role_profile` endpoints deleted (they REPLACED a victim's profiles, e.g. stripping Staff); team bulk-assign delegates to the sync; patch removes the two stale COR rows |
| #1693 | #1670 | Public document-creator account cannot authenticate (no password, credentials locked on setup/migrate/refused login, `on_login` + `auth_hooks` refusal indistinguishable from a wrong password) |
| #1695 | #1688, #1689 | Two order-dependent tests that reddened #1684's shards |
| #1698 | #1697 | `run_doc_method` test installs its own response; 11 tests that replaced `frappe.local.response` now restore it (polluter: `test_page_donate`) |
| #1692 | #1642 | Removing a `CORE_GRANTS` entry revokes it (ledger in `set_global`); admin/HRMS/stock flags never lowered; garbled ledger or #1629 snapshot no longer aborts migrate |
| #1696 | #1650 | Expense approver keyed on the Financial flag; Admin not financial; national Financial step; no fallback; seat order by `idx`; unassigned counted separately |
| #1684 | #1676 | Nightly (`daily_long`) role-profile sync of every enabled member-user, with the rulings above |

## Coordinator notes — what this session taught

- **The diagnosis was a premise too.** I filed #1689 as "a test leaks `frappe.session.user`". The
  author measured the session user after every test: Administrator every time. The real cause was
  untracked stub Employees whose User had been deleted. The brief's step 1 ("verify the issue's
  premise") applied to an issue the coordinator had filed an hour earlier.
- **A fix that makes a design consistent can make an older design inconsistent.** #1659's first
  fix (additive bulk assign) was correct in isolation and flip-flopped against the sync, which
  derives only the top-ranked profile; the review found it only by running bulk → sync with a
  member of two teams. Route new writers through the one source of truth instead of adding a second.
- **A ruling's premise can be false in the code.** "Keep profiles until an event touches them"
  (#1676) would have been "for ever": night 1's empty record disarmed the event-path bootstrap.
  Reviewers should test the ruling's stated consequence, not only the code against the ruling.
- **Two predicates for one identity diverge.** #1670's login refusal used a regex; setup's
  adoption used `LIKE 'public-creator%'`. The account setup itself designated could still log in.
- **Real-data probes changed a ruling.** #1650's review queried veg11 read-only: zero Financial
  seats, one active board seat, no national chapter. Every claim would have reached the
  newest-user fallback (`background.service`) and granted it Expense Approver.
- **A class sweep by direct name misses transitive callers.** #1696 narrowed three checks; CI then
  found three tests still asserting "Admin may see payments" — one direct, two through
  `can_view_financial_info` / `check_member_payment_access`. Sweep the call graph outward from the
  changed function, not just its name.
- **Coordinator error:** `echo "$(cat approved_prs.txt) N" | tr ... > approved_prs.txt` truncated
  the queue (the redirect empties the file before `cat` reads it) and dropped two PRs. Now in the
  dispatch README, rule 10. Also: an author committed its `.pr-body-*.md` scratch file; caught by
  checking the post-review delta's file list before queueing.
- **Shard re-packing exposed five latent order-dependent tests** (#1678, #1688, #1689, #1697, plus the #1694 leaker).
  All were fixed as separate small PRs ahead of the PR they blocked; re-running a shard would have
  repeated the same order.

## Filed this session (open)

Open:
#1679 (creator cannot serve the public donation/membership forms — pre-existing) · #1680 (webhook
user created with a password) · #1681 (newest-user approver fallback; resolved by #1696's deletion,
recommend closing) · #1682 (approver goes stale until the daily job after seat/level changes) ·
#1685 (`assign_role_profile` still replaces; test-only callers) · #1686 (bulk assign has no
per-team/chapter check — admin-only?) · #1687 (Team form bulk button always shows 0 members) ·
#1690 (legacy stray `public-creator-*` account adopted by older setup is never locked; not on veg11) ·
#1694 (`test_national_board_profiles` leaves 5 dangling Employees per run).

## Not started

#1651 (enforce per-chapter approval amount limits) — unblocked now that #1696 is merged; dispatch next.
#1681 — resolved by #1696's deletion of the fallback; close it after confirming.

## Final state

- **veg11**: the live tree (`apps/verenigingen`) has been fast-forwarded to develop by
  `automerge.sh` after each merge, but veg11 has **not been migrated** (last Patch Log 2026-10-12;
  `User.custom_sync_granted_profiles` absent) and was not restarted by this session. Workers or a
  restart will load the new Python against the old schema. Deploying (migrate, restart) is the
  maintainer's call. Before deploying, read: #1674 (sync-granted record), #1684 (nightly job; legacy users
  stay record-less by ruling), #1696 (with veg11's current seats, every expense claim will be
  unassigned until a Financial seat or national board chapter is configured; Utrecht's Secretary
  seat loses automatic approval), #1691 (patch deletes 2 COR rows).
- **Test sites**: reset 2026-10-14 (1,2,3,5,7,8,9,11,12,13). Since dirtied by reviews: 6 and 11
  (CORE_GRANTS ledger probes), 8 and 7 (creator probes), 9/10/13 (migrated with branches). Reset
  before the next dispatch round.
- **Worktrees**: issue worktrees for merged PRs can be removed.
- **develop** is at `447a66e53` (#1692 merged). All PRs of this session are merged; the only open PR is the older #1201.
- **Agents**: none running.
