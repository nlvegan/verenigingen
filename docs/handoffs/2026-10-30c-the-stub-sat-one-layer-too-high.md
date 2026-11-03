# 2026-10-30(c): the stub sat one layer too high

This session (verenigingen-76) started from the 2026-10-29 handoff (PR #1728, unmerged at the start).
A parallel session's `/word-lid` work (PR #1727, handoff PR #1736) was open the whole time; nothing
here touched its files. The maintainer's instructions, in order:

1. "PR #1728 < please read this handoff, pick 8 new issues for agents to work"
2. "go, keep #1731 in"
3. "yes you may merge once green" (the classifier still refused every later write to
   `dispatch/approved_prs.txt`; the maintainer ran each queue command by hand with `!`)
4. "generate a handoff when all PRs are merged"

Coordinator plus sonnet authors and sonnet `skeptical-code-reviewer`s, briefed from
`~/frappe-bench/dispatch/`. Every PR had an independent review before push; every changed delta after a
review was either re-reviewed (#1703, #1709) or read by the coordinator (#1730, #1639, #1701, #1717, #1731,
#1718).

## What shipped

| PR | Closes | What |
|---|---|---|
| #1746 | #1730 | A Rejected/Pending reapplication replaces the earlier dues template and the application's own fee; a staff override survives |
| #1747 | #1639 | A refused account-creation queue writes an Error Log and the approver sees a fixed reason code; an in-flight ACR is no longer a "refusal" |
| #1750 | #1701 | Chapter dashboard expense tiles/rows read through `get_list` as the caller; the payload cache is per-user again |
| #1751 | #1731 | `submit_application`'s chapter steps run as the system user; only published + Active chapters accepted |
| #1752 | #1703, #1704 | Bulk join approval stops at a destroyed transaction (any exception type); join-request status changes only via approve/reject |
| #1754 | #1718 | Chapter bulk role-profile sync counts only real successes, lists failed/skipped, escapes them in the UI |
| #1755 | #1717 | Two termination test modules stop leaking (setUp fixtures with hashes; Contact cleanup) |
| #1757 | #1709, #1710 | The ACR pipeline honours Cancelled at every writer (locked reads); dashboard cancel/queue go through the server; cancel keeps the original error |

All merged to develop by `automerge.sh` (CI green + pre-merge gates), in order: #1746 `e51290082`,
#1747 `87030a2a3`, #1751 `d18d8c4f2`, #1752 `188da1e3f`, #1750 `4d86c0248`, #1757 `262476218`,
#1754 `50fe604d8`, #1755 `0ff1da804`.

Coordinator commit (mechanical): #1754 `01dc5fb4b`, the one shrunk line in
`log_error_arg_order_baseline.txt` (the fix removed a swapped `log_error`; CI's shrink gate requires the
shrink in the PR).

Post-push CI reds, all handled on the same PRs: #1750 shard 7 (an older test asserted the shared cache;
rewritten with a per_user=False control, coordinator-reviewed), #1754 log_error ratchet (above), #1755
shard 12 (fixture-isolation invariant: region code must come from `unique_region_code()`), #1755 shard 9
(infra: npm 404 on `@tiptap/extension-code-block-lowlight@3.32.2` during setup, no test ran; job re-run green).

## Decisions waiting for the maintainer

| Subject | Question | Where |
|---|---|---|
| **#1741** Quit rejoiner | Re-approval reuses the old dues schedule, which stays **Cancelled**: no dues are ever billed. Reactivate and refresh the old schedule, or create a new one like a new member? This also decides #1737 and the part of #1730 that #1746 scoped out | #1741 |
| **#1740** anonymous reapplication | Anyone who knows a Rejected/Pending/Quit member's email can overwrite that Member's name and **IBAN** via `submit_application` (pre-existing). Require email confirmation like `/word-lid`, or refuse identity/bank changes from an anonymous submission? | #1740 |

**Coordinator decisions, not ruled by the maintainer** (stated so they can be overruled):
- #1731: a suggested chapter must be published **and** `status == "Active"`; the form still lists published Inactive/Dissolved chapters, which are now silently dropped (follow-up noted in the PR).
- #1730: scope narrowed to Rejected/Pending; a fee override counts as staff-set unless it matches the application's own stamp.
- #1718: a disabled board member is "skipped" (neither updated nor failed); partial failure still returns `success: True` (differs from #1721's team majority/rollback rule; per-user writes are independent).
- #1709: Cancel on the dashboard stays offered on Requested/Queued/Processing (the pipeline now honours it); a cancelled request cannot be reopened through the UI; an account created before a late cancel is recorded, not rolled back.
- #1639: an approval whose account creation is refused still succeeds; the reason is shown as a code, details in the Error Log.

## Coordinator notes — what this session taught

- **The stub sat one layer too high (#1703).** The author's deadlock test patched
  `assign_member_to_chapter` to raise. In production a 1213 in the roster write is caught one layer
  lower and returned as `{"success": False}`, so it reached bulk approve as a ValidationError and the
  "fix" never fired. The reviewer injected at `MemberManager.add_member` and got the original false
  success. A fault-injection test must inject **below every swallowing layer** on the real path.
- **A red that only reproduces on one site is a site fact, not a code fact (#1717).** The author's
  "15/15 fail on a clean run" was real on test_site_3 and absent on test_site_1. The difference was an
  enabled default outgoing Email Account with no SMTP server on site 3 (`Jobs`); the author proved it
  with an on/off control. Before a red becomes a premise, run it on a second site.
- **The fix made per-test names unique and leaked a Contact per test (#1717 r1).** Unique fixtures
  move the leak from "collides next run" to "accumulates forever" unless cleanup covers every row the
  name creates. Census every doctype the fixture touches, not only the ones the author created.
- **An older test encoded the design the fix deliberately changed (#1750).** #785's test asserted the
  dashboard cache was SHARED; #1701 made it per-user. Neither author nor reviewer ran that module
  (`test_chapter_dashboard_page` vs `test_page_chapter_dashboard`). CI shard 7 caught it. When a fix
  changes a cache/permission scope, grep the tests for the OLD behaviour's words ("shared", per_user).
- **Removing a swapped log_error call is a baseline shrink CI requires you to commit (#1754).** Rule 15
  already says so for deleted functions; it applies to any fix that removes a baselined finding. The
  coordinator now regenerates all six `--update-baseline` validators in every PR worktree before
  queueing (only #1754 needed it this round).
- **`limit_page_length` / "get_list pages at 20" is false in Python (#1701).** The 20 default is
  REST/desk only; the paging test asserted nothing. Measure framework defaults before writing them
  into a docstring.
- **Unlocked read → sleep → write revives a cancelled row (#1709).** `queue_processing` checked status,
  waited for queue capacity (can sleep), then wrote Queued. Any "check then act" around a wait needs
  the locked re-read immediately before the write.
- **The test sites were reset from a snapshot older than the schema.** After `reset_test_sites.sh`
  (no `--refresh`), `Expense Claim.custom_chapter` was missing on most sites and the tests that need it
  SKIPPED silently. Sites 2-5, 12, 13 were migrated by the coordinator; 1, 9, 11 by agents. Next reset:
  use `--refresh`.
- **The scripts/validation unittest suite does finish** (711 OK on test_site_2 in one run), but four
  modules take 60-96 s each; most agents gave up on it. Run it per module or with a 600 s timeout.
- **Rule 4 (`pkill -f`) was broken once by a reviewer** and probably killed the coordinator's own timing
  run. The brief says it; reviewers still reach for it when a background job outlives them.
- **automerge.sh stops on ANY queued PR's red**, including one queued minutes earlier. Pull a red PR
  from `approved_prs.txt` immediately (removal was allowed by the classifier; additions were not).

## Filed this session (open)

#1737 (Quit rejoiner's chosen amount dropped) · #1738 (chapter expense report: Staff + board role sees
all claims; premise corrected in a comment) · #1739 (`_build_approval_response` reads `action` at top
level; success branches never match) · #1740 (anonymous reapplication overwrites name/IBAN) · #1741 (Quit
rejoiner re-approved onto a Cancelled schedule) · #1744 (stale "In Progress" ACR status in
account_creation_api) · #1745 (join-request review fields forgeable after submit) · #1749 (team
bulk_apply counts failed syncs) · #1756 (test customer cleanup refused: Contact linked to Member).
Comments added: #1595 (Pending-row leak now live after #1751), #1276 (4 more tearDownClass-without-commit
modules), #1738 (premise correction), #1718 (sweep).

## Final state

- **develop:** `0ff1da804`. The live tree (`apps/verenigingen`) was fast-forwarded to it by
  `automerge.sh`, but **veg11 was NOT migrated or restarted this session**, so none of these PRs is
  deployed. #1752 changes a DocType JSON (`Chapter Join Request.status` read_only) and needs `migrate`.
  Untracked/modified in the live tree, left alone: `ONBOARDING.md`, `email_brand.css` (timestamp, see the
  10-29 handoff).
- **Test sites:** reset from the snapshot at the start, then migrated (the snapshot lacks
  `Expense Claim.custom_chapter`); all used since. Reset with `--refresh` before the next round.
  test_site_3 has frappe's `Jobs` Email Account enabled as default outgoing with no SMTP server (it makes
  mail-sending tests raise from `commit()`); the parallel session added the same row to test_site_10.
- **Parallel session:** the `/word-lid` session ("aanmeldformulier-cont") ran at the same time, wrote to
  the same `dispatch/ledger.md` and used test_site_10/13 while this session had reviewers on 6-11. No
  phantom failure was traced to it, but two coordinators sharing one site pool is the
  site-sharing hazard in CLAUDE.md. It merged #1727 and opened handoff PR #1759 (`2026-10-30b`), hence this
  file's `c`. Its PR #1753 is still open.
- **Worktrees:** `worktrees/issue-{1701,1703,1709,1717,1718,1730,1731,1639}` are merged and can be removed.
- **Open PRs:** this handoff, #1759, #1753, #1736, #1728, #1699, #1201.
- **Agents:** none running.
- **Queue friction:** after "yes you may merge once green", the auto-mode classifier still refused every
  *addition* to `approved_prs.txt` (removals were allowed). The maintainer ran each queue command by hand.
  If that is to be avoided next time, add a Bash permission rule for that file.
