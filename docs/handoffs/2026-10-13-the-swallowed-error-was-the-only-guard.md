# 2026-10-12/13: the swallowed error was the only guard

This session (verenigingen-73) started from the 2026-10-11b handoff and ran across two days. The
maintainer's instructions, in order:

1. "merge handoffs, write a patch for 1629, have an agent investigate 1623. run reset test sites."
2. "merge both" (#1643, #1644); "sync locally and migrate"; "restart" (veg11).
3. "are 1605 and 1606 finished?" → review both; rulings on #1606's role scope (below).
4. Questions on chapter finance: the Financial flag, double approval, amount limits.
5. "put sonnet agents on the issues discussed today".
6. Rulings on #1615 / #1664 / #1667 (below).
7. "generate a handoff when all of these are done and all are ready for merging; merge the ones
   that are green in order".

Coordinator plus sonnet authors and sonnet `skeptical-code-reviewer`s, briefed from
`~/frappe-bench/dispatch/`. Every PR below had at least one independent review before merge;
#1615 took five.

## Decisions made by the maintainer

All recorded on the issue/PR named, and in the coordinator's policy memory.

| Subject | Decision | Where |
|---|---|---|
| #1629 design | Migrate-time diff (snapshot before_migrate, prune after) | PR #1643 |
| HR roles (#1606) | **No HR User / HR Manager on any profile except the (national) Treasurer, which gets HR Manager.** Staff: no salary/payroll. | PR #1606 comments |
| Staff and expenses | Staff approve expenses but must **not see all** claims; plain Staff may not approve another Staff member's claim (fallback "trust and instructions" if HRMS made it a mess — it did not) | PR #1606 |
| Self-approval | Nobody approves their own claim **except the Treasurer** | PR #1606 |
| National Board Member | May read and approve expenses, "not much else"; fix #1512 (profile grants the NBM role) inside #1606 | PR #1606, #1512 |
| Administrator profile | Drop HR Manager, add nothing | PR #1606 |
| Staff creating Employees | Option (b): no Employee DocPerm (salary/bank/health fields are permlevel 0); a narrow "Create Employee Record" action instead | PR #1606 |
| Employee Advance report | "advances are not that important" — left open | PR #1606 |
| Chapter finance (#1650) | Chapter treasurers do **not** self-approve; the auto expense-approver moves from role names to the Financial flag; no preference on retiring the `Treasurer` role name; **Admin-implies-financial still open** | #1650 |
| Approval limits (#1651) | Use the per-chapter amount limits (exist, unenforced) mainly to **limit the local treasurer**; double approval rejected | #1651 |
| #1615 | National-board seat profile **added on top** of a staffer's own; recalculate when `national_board_chapter` changes (#1660) | #1615 |
| #1612 | Option (a): explicit full activation leaves the volunteer in **Onboarding** (calculator already counts it) | #1612 (still open: its "Additional Roles" part depends on #1293) |
| #1664 | after_migrate creates Verenigingen Settings once a Company exists — confirmed | PR #1664 |
| #1667 | Direct profile assignment admin-only; **existing NBMs must be able to seat new volunteers on the national board** (works via the derived seat sync, PR #1674) | #1615 |

**Coordinator defaults still awaiting a maintainer yes/no:** only System Manager / Administrator /
Verenigingen Administrator may change `national_board_chapter` (#1626, in PR #1674); setup keeps
auto-recommending the System Administrator profile to System Manager users (#1654 note).

## What shipped (merged to develop)

| PR | Closes | What |
|---|---|---|
| #1643 | #1629 | A permission revoked in an own DocType's JSON is pruned on migrate (before_migrate snapshot + after_migrate prune; admin-edited rows survive) |
| #1644 | #1623 | Stale swallow / log_error baseline lines (develop push was red) |
| #1605 | — | Six field help texts without developer notes |
| #1653 | #1648 | Remaining developer notes; "No description yet" for unregistered notification keys; guard test |
| #1657 | #1646 | 3 COR fixture rows validate on install (batch limit 100000) |
| #1658 | #1641 | A PR that shrinks a baseline fails **on the PR** (base-tree census); unresolvable base is a hard error |
| #1661 | #1649 | Mapping guard ignores Employee / Employee Self Service (stripped by erpnext from users without an Employee record) |
| #1664 | #1645, #1647 | Install steps run independently (Domain abort removed); Settings created from a real Company or on the first migrate after one exists; public creator reused, password no longer printed |
| #1668 | — | Mollie clearing-account test immune to co-tenant `%Mollie%` accounts (blocked #1663/#1667) |
| #1667 | #1654 | No heuristic Treasurer recommendation; direct profile assignment: actor must hold every role, national profiles admin-only. **Closed a live escalation: Treasurer/NBM holders could self-assign the Administrator profile → System Manager.** |
| #1671 | — | Donation-exemption test tolerates the deliberate creator grant (order-dependent red since #1664); exposure filed as #1670 |
| #1663 | #1618, #1633 | Membership Type / MijnRood role & profile selectors guarded. **Closed a live escalation: a Staff user could reach System Manager via Membership Type.role_profile.** (This branch was orphaned by session frappe-aa; taken over, reviewed, pushed.) |
| #1606 | #1512 (+rulings) | The HR-role rulings above; expense-claim visibility split; approval guard (self, Staff-vs-Staff, two-save employee swap); "Unpaid Expense Claim" report restricted; Create Employee Record action; payroll-granting profiles/roles assignable/mappable only by admins |
| #1674 | #1615, #1627, #1660, #1673 | National-board seats grant NBM/Treasurer **on top of** a staffer's own profile; the role-profile sync is non-destructive via a sync-granted record (`User.custom_sync_granted_profiles`, permlevel 1, fixture); `national_board_chapter` change restricted to SM/Administrator/VA + resync of old and new seat holders; remove endpoints guarded; an existing NBM can seat volunteers on the national board; #1612 (a): explicit full activation leaves the volunteer in Onboarding (not for Rejected/Expired/Suspended/Banned/Deceased/Quit members). Six review rounds. |

## Coordinator notes — what this session taught

- **The swallowed error was the only guard.** #1615 needed a non-admin to trigger a role-profile
  sync, so the sync's `User.save()` got `ignore_permissions=True`. On develop that save raised a
  PermissionError that was swallowed — and that accident was the only thing stopping any chapter
  board member from rewriting any user's profiles (round 1: a System Manager lost System Manager).
  Round 5 found the same mask hiding an Account-Creation-Request profile removal. **When a fix makes
  a previously-failing write succeed, review what that write was silently prevented from doing.**
- **"Provenance from row existence" fails both ways** (row deleted → history lost; row added → history
  faked). The fix that held was recording what the sync itself granted.
- **Merged guards compose into new holes.** #1667's "actor may assign what they hold" + #1606's
  "Treasurer holds HR Manager" let a Treasurer hand out HR Manager. Found only because CI ran #1606
  against merged #1667. Re-review semantic interactions after a dependency merges.
- **Test-helper lookups by `like "%Member%"` matched the national profile** (newest-first), which
  #1663's guard then refused — 30 red tests in one shard. Exact names in fixtures.
- **Order-dependent reds surfaced by shard re-packing** three times (Mollie accounts, Donation
  premise, the creator role). A re-run reproduces the same packing; fix the test.
- **An author used `git push --no-verify`** after an unclear hook failure; the hidden failure was real.
  The author brief now forbids it and says how to find the failing hook.
- **Merges by the coordinator were classifier-denied early in the session** until the maintainer
  asked explicitly; afterwards `automerge.sh` ran under the maintainer's "merge … in order".

## Filed this session (open)

#1642 (CORE_GRANTS removal never revokes) · #1650 (two "treasurer" definitions; Admin-implies-
financial open) · #1651 (approval limits unenforced) · #1652 (COR alert_on_execution inert) · #1655
(hand-made Employees pin User Permissions) · #1656 (existing sites' 3 COR rows unsavable, batch 0) ·
#1659 (assign endpoints: no seat check for ordinary profiles) · #1662 (install steps swallow) ·
#1665 (Role force-delete leaves Has Role rows → before_tests dies) · #1666 (dashboard counts all
claims) · #1669 (4 unconditional bypass_validations sites) · **#1670 (public-creator account can
authenticate and read/write all Donations/Donors/Members — latent)** · #1672 (seating as non-admin
logs a swallowed User save failure).

## Held work (not dispatched; overlapped #1606)

#1642, #1650, #1651 — dispatch now that #1606 is merged. #1651 depends on #1650's open
"Admin implies financial" question.

## Final state

- **veg11**: on develop `33ea51997` (migrated + restarted 2026-10-12, backup `20261012_185617`).
  **Not** updated with anything merged on 2026-10-13. Deploying (sync, migrate, restart) is the maintainer's call. Before it, note #1674's PR body:
  veg11 bootstrap measured read-only — 438 member-users hold "Verenigingen Volunteer" without a
  Volunteer record, so their first profile sync converts them to "Verenigingen Member" (develop's
  sync already did this on any sync); the documented residue of the sync-granted record is empty on
  veg11; until migrate imports the new User custom field nothing is withdrawn.
- **Test sites**: reset 2026-10-12. Since polluted by real-step/setup runs: 1, 2, 3, 5, 7, 8, 12, 13
  (creator users, Custom Roles, migrated branches, MijnRood dummy creds, seeded Mollie accounts on 6).
  Run `reset_test_sites.sh` before the next dispatch round.
- **Worktrees**: issue worktrees for merged PRs can be removed; `worktrees/issue-1615` holds #1674.
- **Stash stack**: untouched.
- **develop** is at `8228a4bd5` (#1674 merged). All PRs of this session are merged; none open.
- **Agents**: none running.
