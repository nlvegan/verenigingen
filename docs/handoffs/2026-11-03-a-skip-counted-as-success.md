# 2026-11-03: a skip counted as success

Session "1102" (verenigingen, 2026-11-02 into 11-03). It continues `2026-11-02-the-test-never-reached-the-branch.md` and worked through that note's open list. Session `1102b` shared the bench, took the Ponto, return-page, #1959 and fresh-install items, and was idle by the end.

## The one lesson to carry forward

**EmailService reports a skipped send as `success=True`, so a test that asserts "success" can pass without ever building the email.**

- `test_communication_manager` asserted success for four sends whose Email Template fixture had an empty body: `response` was set, `response_html` was not, and `use_html=1`.
- It passed for months because its notification key had no Email Notification Type row, so every send was a skip.
- #1998 seeds a row for every registry key on fresh install, so CI's sites suddenly sent. All four failed with "Subject and content are required", on an unrelated PR (#2005, shard 5).
- Local sites are not fresh installs, so the same tests stayed green here. They only reproduced once the rows were seeded (`ensure_notification_registry_rows()`) on a test site.

The rule: when a fix changes whether a send is *gated*, the tests behind that gate start testing something new. #2013 hit the same thing a day later. Registering `payment_reminder_friendly` gave it a 7-day cooldown, and a test reminding one member twice went red.

**Reproduce CI's notification state before trusting a local green on any email test:** seed the rows, then clear the Redis `email_cooldown:*` keys.

The class is filed as #2010, and the staff-facing version as #2015 (cooldown-skipped reminders are counted as "sent").

## Merged this session

| PR | Closes / refs | What |
|---|---|---|
| #1995 | #1983, #1994 | Harness guard keeps `frappe.local.response` well-formed. It exposed a real HTTP 500 on `/brand_css_disabled` (#1994). The reviewer pinned the CI polluter: `test_ing_ponto_webhook_response_minimal`. |
| #2011 | refs #2009, #2010 | Test fixtures get a `response_html` body. Unblocked develop after #1998. |
| #2005 | #2000 | Monitoring alerts go to the **Verenigingen System Administrator** profile, not a hard-coded `admin@dev.veganisme.net`. Profiles are read from the `role_profiles` child table, because `role_profile_name` mirrors only the first profile. A once-a-day Error Log row is written when nobody holds the profile or the mail is not queued. |
| #2013 | #1999 | Seven sender keys registered. Per-key cooldowns in the registry, read by the seeder and by Sync Registry. A test fails on any sender key it cannot resolve. |
| #2014 | refs #2000, #2003 | Technical alerts go to System Administrator (`system_alert`). Business/finance alerts and the daily report go to **Verenigingen Administrator** (`business_monitoring_alert`). Each group has its own cooldown. |
| #2016 | #1959 follow-up | Migrate patch adds missing notification rows on existing sites, and never changes existing rows. Merged as e9b1a4c12. |

## Maintainer rulings (2026-11-02/03, each recorded on its issue)

- **#2000:** alerts go to the Verenigingen System Administrator profile, split by kind (b). Technical alerts go to System Administrator. Business/finance alerts and the daily report go to Verenigingen Administrator. Reviewing the checks themselves is #2004.
- **#1999:** register the missing keys (option a). Per-key cooldowns:
  - `payment_failure_first` / `_second`: 1440
  - `payment_reminder_friendly`: 10080
  - `payment_reminder_urgent`: 4320
  - `payment_failure_final` and `subscription_*`: 0
  - every other key: 60
- **#1959:** existing sites get the missing rows **at migrate, via a patch**. It only adds; it never changes rows.
- **#1979:** all 14 design decisions are answered on the issue (comment 6585799848). Point 7 ("who counts as someone") is to be **configurable**. Phase 1 (record + write-ahead) can now be dispatched. #1999 was its prerequisite and is merged.
- **veg11:** it is **not** production data (`~/CLAUDE.md` corrected; it said "a copy of production data").

## What you need to know

- **veg11 mail cannot leave:**
  - Jobs is disabled.
  - The only outgoing account is the leaked test fixture `_Test Email Account 1`, pointing at `smtp.example.com`.
  - The scheduler is off.
  - It holds **~38.6k unsent Email Queue rows**. They would flush if a real account and the scheduler were ever both enabled.
- **veg11 has no holder of either admin profile.** Someone must hold Verenigingen System Administrator and Verenigingen Administrator before any monitoring mail reaches a person anywhere.
- **The migrate patch switches on ~every notification on an existing site.** On veg11, 79 of 80 keys had no row. The scheduler-reachable senders are listed in PR #2016's body.
- **Cooldowns diverge** between existing sites (v15 patches) and fresh installs (registry) for about 45 keys. The two v15 patches even disagree on the reminder keys. This needs a decision, filed as #2012.
- **A CI npm `ETARGET` on a just-published package** (`@tailwindcss/node@4.3.4`) is registry lag, not code. Bring develop into the branch, or re-run on the current head, once it resolves (`npm view <pkg>@<ver>`).
- **CodeQL flags a domain substring check in a test** (`"x.net" in r`) as "incomplete URL sanitization" (high) and fails the PR. Assert exact membership instead.

## Open items

| Item | State |
|---|---|
| #1979 | **Ready to dispatch phase 1** (record + write-ahead), then the EmailService funnel. The rulings are on the issue. |
| #2012 | Maintainer decision: copy the v15 cooldowns into the registry, or keep 60. |
| #2003 | Within one alert group a LOW alert still suppresses a CRITICAL one within the cooldown, and cooldown skips are not logged. |
| #2004 | Monitoring checks review: proxies, a check that never runs (`CRITICAL_ERRORS`), unvalidated thresholds. |
| #2010 / #2015 | Skip-as-success: in tests (census of ~18 fixtures in a comment on #2010), and in the reminder counts. |
| #2009 | Setup code creates HTML templates with the body in `response`. 0 broken on veg11; install order not traced. |
| #2002 | Other hard-coded recipients (`admin@example.com`, `@vereniging.nl` placeholders, `finance@company.com`). |
| #2006, #2007, #2008 | Missing "Payment Failure Notification" template; `chapter_assignment` notifications never sent; three missing payment templates (one without a fallback). |
| #1997 | A Role-Based row with no roles crashes the recipient lookup. The migrate patch leaves existing rows alone, so this is not fixed by it. |
| Carried over | The Ponto sandbox checks (#1931 404, redirectUri decline) still need someone with sandbox access. 1102b's Ponto PRs #1838/#1896 are HELD. |

## Filed or commented this session

- **Filed:**
  - #1994: `/brand_css_disabled` 500 (fixed).
  - #1999 and #2000: fixed.
  - #2002, #2003, #2004.
  - #2006, #2007, #2008: by the #1999 author.
  - #2009, #2010, #2012, #2015.
- **Commented:**
  - #1830: a second flake symptom in `test_national_board_profiles`.
  - #1979: the design, its independent review and the rulings.
  - Rulings recorded on #1959, #1999 and #2000.

## Final state

- **develop** is at e9b1a4c12. The live tree is fast-forwarded to it, and web and workers have been restarted.
- **veg11:**
  - Backed up at `sites/veg11.veganisme.org/private/backups/20261103_025431-*`, then migrated.
  - The seeding patch ran once. Notification rows went from 2 to 89, and both existing rows are unchanged.
  - The patch wrote the per-key cooldowns itself, because those rows were missing before.
  - The Email Queue is unchanged, at 38,621 Not Sent rows.
  - Its scheduler is still disabled.
- **Agents:** none running.
- **Test sites held:** none. test_site_2, 4, 5, 6, 9, 12 and 13 were used and released. Sites 6, 12 and 13 were left as found; the reviewers restored their notification rows by hand.
- **Worktrees:** every worktree from this session is removed except `agent-worktrees/handoff-1103`, which holds this note. The other `agent-worktrees/*` belong to other sessions.
- **Automerge:** the queue is empty, and only this note's PR is left.
- **`~/CLAUDE.md`** (not in git) is corrected: veg11 is not production data. A dated note on veg11's mail safety was added.
