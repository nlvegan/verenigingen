# 2026-11-02: a test edit re-packed the shards onto develop's pollution

This session (verenigingen-2c, 2026-11-01 into 11-02) continued from the 2026-11-01b handoff (PR #1941,
merged). Peer sessions active alongside it: verenigingen-ed ("ee", wrapped up, handed over #1954) and
verenigingen-1d ("af2"). They shared `dispatch/ledger.md`, `dispatch/approved_prs.txt` and the test sites.

The maintainer's instructions, in order:

1. "The handoff PR #1941 < please read this".
2. Ran `bench migrate` (no `--site`, so test_site_1) and it hung: see "Environment" below.
3. "okay do #1 #2 #3 and then #4 in logical order and clean the worktrees". These are the four #1765 steps
   from the previous handoff: 7b(b), merge develop, the final review, then the PR.
4. Approved queueing ee's PR #1954 ("yes").
5. "generate a handoff while we wait please".

## #1765: PR #1976 is open, everything reviewed. Waiting only on CI

**PR #1976**, branch `feat/1765-application-record`, head **`b0fb4b0be`**, worktree
`~/frappe-bench/worktrees/plan-1765`. The ledger is `.superpowers/sdd/2026-10-30-application-as-record/progress.md`
(git-excluded). It holds every ruling (A to AR), round and commit range, plus `final-review.md`.

**State at handoff:** CI was running at `b0fb4b0be` (32 passed, 8 in progress, 15 queued). **#1976 is NOT in
`approved_prs.txt`.** It was dequeued after a red. When CI is fully green at that head, re-queue it:
`sed -i '$ s/$/ 1976/' ~/frappe-bench/dispatch/approved_prs.txt`. This is the session owner's own reviewed PR, and the
standing merge-when-green rule applies. If it goes red, read the shard log first (see "CI reds" below).

What happened, in the order the work was done:

| Step | Outcome | Commits |
|---|---|---|
| Develop merge 1 (95 commits) | 5 conflicts. Develop's #1917 `invoice_failed` handling landed in the wrong function and was reverted. #1914's escaping gate passes. | `c12f55b77` |
| Task 10 | Ported develop's #1773/#1774 invoice tests to `approve_application`. Bulk approve counts `invoice_failed` separately. **Must-fix:** the purge deletes only `/files/` and `/private/files/` urls (an external url's basename deleted an unrelated private file). | `735410b2a` `ee63f9610` `b24ada635` |
| Final whole-branch review (opus) | Needs fixes. All ~35 deferred minors triaged (resolved, accepted or filed). The "board member saw extra applications" flake was environment, measured: s5's Redis-cached hooks came from develop, which lacks the MAS permission query. | `final-review.md` |
| Fix round (Ruling AQ) | F1: validation test pins the shrunk baseline (89/44). F2: an involuntary Quit is checked before `application_status`, so it is refused. S1: sanitise the application name first. S2: maintainer rule 4, blank answers never clear. Re-reviewed, with mutants. | `1d79a5761` `5bde19166` `c31f09f54` `645baf32b` `a8844a442` |
| Develop merge 2 | Brought #1862/#1797 and #1820. Task 11: ported the #1797 tests and pinned the `@handle_api_error` census by name. | `7f2353944` `ba3115ec5` `ce3d6acd5` |
| Develop merge 3 + 7b(b) | Brought #1932's `_refuse_unknown_chapter`. **Ruling AR:** `approve_application` uses it in place of the branch's stricter T4 guard (one #1908 rule for both paths). Ported the tests and deleted `tests/utils/guest_application.py`. The review compared the unknown-chapter and foreign-chapter refusals over HTTP: 417 both, 15 queries both, identical bodies. A sentinel test pins "refused before any write". | `159c951b0` `1381754a5` `7d1bb62a7` `f502e62b4` |
| CI red 1 (shards 7 and 9) | Test-side carries: #1914's escaping test used the old `member` context, and a churn test hit F2's intended block. | `860629c9a` |
| CI red 2 (shard 8) | Order dependence that already existed on develop. Fixed on develop by #1985, then develop merge 4. | `b0fb4b0be` |

**Rulings in the PR body that the maintainer should see:**
- **AO:** reject no longer marks the CRM Lead Do-Not-Contact.
- **AR:** a scoped approver may place an applicant in another chapter it manages.
- **#1968:** reapplying resets magazine delivery to the form's preselected default.

Also in the PR body: the 10/h per-IP limit on the full form, that the IBAN mask in the preview is cosmetic, and that
#1900 is still open (no approval email without an invoice).

## Other PRs this session

| PR | What | State |
|---|---|---|
| #1976 | #1765 (above) | open, CI running, **not queued** |
| #1985 | test-only: restore stock Email Templates from the fixture after tests delete them (Closes #1982, Refs #1981) | **merged** |
| #1954 | ee's #1922, ownership handed to 2c. The maintainer approved queueing it | **merged** |

## Filed this session

#1961, #1962, #1963, #1964 (deferred minors from the final review); #1968 (magazine delivery default, product
decision); #1970 (account-creation job recursion in `_()` when the job user is gone); #1981 (approval email template:
a test pollution, now fixed by #1985, plus a latent product defect, still open); #1982 (sibling template deleters, closed
by #1985); #1984 (setup UPDATES seven stock template rows). Commented on #1855 and #1900.

## What this session taught

- **Editing a test file re-packs the CI shards, and can expose a pollution that already exists on develop.**
  #1976's second red was `test_member_events_coverage`. It was green alone on the branch AND on develop, and red only
  after `test_membership_email_templates` (which deletes a stock template) and `test_setup_workspace_onboarding`
  (which recreates a different body). The re-pack came from my own two-test-file fix commit. Before blaming a red on
  the branch, run the victim alone on the branch and on develop; if both are green, bisect the shard prefix
  (`scripts/testing/order_dependence_detector.py`, module order taken from the shard log). `show_test_shards.py`
  cannot reproduce the layout from a worktree path without `/apps/`.
- **A fix that blocks a state also breaks every test that builds that state as a shortcut.** F2 correctly refused a
  Quit member with no executed termination. A churn test had cancelled the termination BEFORE reapplying, as its
  #1548 workaround, and only CI found it. When a guard tightens, grep the tests for fixtures that construct the newly
  refused state.
- **Merging develop into a long branch brings develop's tests for paths the branch deleted.** All three merges
  brought member-keyed tests (`approve_membership_application`, `member_record`, `guest_application`). After every
  merge, sweep the merged diff for the removed symbols (the command is in the ledger). Auto-merge also put #1917's
  `invoice_failed` block into the wrong function; read the auto-merged hunks in files the branch rewrote.
- **A snapshot restore saves whatever pollution is already there.** #1985's first round restored the row it found at
  class start; the fixture is the only source of truth for stock rows.
- **The permission classifier refuses queueing a PR you did not author unless the maintainer asked.** Queueing #1954
  needed an explicit "yes". Dequeueing and re-queueing my own PR did not.
- **CI job logs can be read before the run finishes:**
  `gh api --allow-escape-sequences repos/nlvegan/verenigingen/actions/jobs/<job>/logs`.
  `gh run view --log` refuses while the run is still in progress.
- **Ledger claims still collide.** Another session migrated test_site_5 from a develop tree while I held it. Results
  from that window were re-verified on s12.

## Environment

- `bench migrate` hung at "Removing orphan doctypes". `apps/verenigingen/node_modules/node_modules` was a symlink to its
  own parent (created 2026-09-26), and `verenigingen/public/node_modules` links into that tree. Frappe's recursive glob
  follows symlinks, so it walked about 48k files about 40 levels deep for each entity type. I deleted the self-link
  only. If it reappears, find it with `find -L node_modules -maxdepth 8 2>&1 | grep -i loop`.
- Removed 99 merged agent worktrees and their local branches. Left: worktrees with open PRs, `plan-1765`, and three
  without a PR and with unmerged commits (`.wt-1907`, `issue-1611`, `issue-1613`). Merged since then and now removable:
  `~/agent-worktrees/fix-1981-email-template-restore`, `fix-1922-rest-board-row-sync` (ee's), `worktrees/handoff-1101b`.
- **Sites:** test_site_5 and test_site_12 were last migrated from `plan-1765`, but the claims are released. A reviewer's
  migrate on s12 (developer_mode=1) wrote onboarding JSON churn into a worktree. Revert that if you see it.
- **Agents:** none running at handoff.
- Live tree at develop; `ONBOARDING.md` untracked (not mine).
