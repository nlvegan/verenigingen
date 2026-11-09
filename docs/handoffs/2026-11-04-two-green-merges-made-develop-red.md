# 2026-11-04: two green merges made develop red

Session "1103" (verenigingen, 2026-11-03 into 11-04). It continues `2026-11-03-a-skip-counted-as-success.md` and worked through that note's whole open list. Concurrency cap was 2 agents throughout. Every fix had an independent skeptical review before push, and a re-review of every round after it.

## The one lesson to carry forward

**Two PRs that are each green can make develop red together, and the pre-merge gate will not see it.**

- #2030 (#1979 phase 1) had a test that made a send raise by using a Role-Based row with NULL `recipient_roles`, which crashed on `None.split`.
- #2031 (#1997) fixed exactly that crash.
- Each PR was green against the develop it was tested on. After both merged, `test_a_send_that_raises_still_leaves_a_failed_event` failed on every PR ("AttributeError not raised").
- A peer session (coordinator of #1964/#1988/#1989) reported it. #2047 fixed it by injecting the failure at the same boundary.
- `premerge.sh` runs gates, not tests. Before merging #2031 I had run its own modules on the merged tree, but not #2030's.

The rule is now dispatch README rule 24: before merging, also run the modules of every PR merged since the PR's base that touch the same function.

A second trap appeared during recovery. Re-running a failed `pull_request` job does **not** pick up a develop fix, because it reuses the merge commit computed at trigger time. Only `gh pr update-branch <n>` gives a fresh run (rule 25).

## Merged this session

| PR | Closes / refs | What |
|---|---|---|
| #1699 #1728 #1736 #1759 #1760 #1783 | | Six old handoff notes, docs-only. |
| #2026 | #2006, #2008, #2015 | Reminders report sent, skipped and failed separately, and only real sends are logged. The four missing templates ship as fixtures. The Final and Bulk fallback honours its key. The board gets one mail per chapter per run (ruling), and the new `cooldown_scope` on EmailService makes the cooldown per chapter. |
| #2030 | refs #1979 (P1) | MyISAM `Staff Alert Event`, written ahead of `notify_administrators(staff_alert=True)`. The outcome reflects the latest attempt. `event_reference` makes termination_overdue reuse one row. |
| #2031 | #1997 | An empty Role-Based `recipient_roles` no longer crashes. Sync Registry writes the admin roles. |
| #2035 | #2009 | The setup writes HTML template bodies to `response_html`. The dead `setup_email_templates()` is deleted. |
| #2040 | #2007 | `request_to_join` really mails the board, through a registered template and key. The cooldown is scoped per applicant. |
| #2047 | | Unbroke develop: test-only, it injects the lookup failure. Reviewed by the coordinator only, to unblock develop; the PR says so. |
| #2048 | #2012 | The registry takes the v15 cooldowns. Patch `apply_v15_cooldowns_to_seeded_rows` moves rows still at 60. |
| #2050 | #2003 | HIGH and CRITICAL monitoring alerts bypass the cooldown and do not record it. |
| #2051 | #2002 | No literal fallback recipients. There is one shared `resolve_admin_recipients(key_first=...)`, and `notify_administrators`' order is unchanged and pinned. SEPA alerts scope their cooldown per alert and escalation level. The sender-key walker follows module-level string constants. |
| #2054 | #2010 | 22 tests that passed by skipping now assert a real send. A new helper, `tests/utils/notification_state.own_notification_keys`, seeds named keys, restores them, and fails loudly if a commit made the seed permanent. |

## Maintainer rulings (2026-11-03/04, each recorded on its issue)

- **#2012:** copy the v15 cooldowns into the registry.
  - Where the two v15 sources disagree, `migrate_email_settings` wins, except for the #1999 reminder keys.
  - A patch moves rows still at the seeded 60.
  - The five #1999 dunning keys are in the patch table. That was the coordinator's call.
- **#2003:** HIGH and CRITICAL bypass the cooldown.
  - The coordinator, following the review, decided a bypassed send records no cooldown. Otherwise the daily report and the MEDIUM alerts were lost after a severe alert.
- **#2004:** parked.
- **#2006:** the board gets one mail per chapter per run, listing every overdue member.
- **#2002:** option B, one resolver with a precedence switch.
  - `notify_administrators` keeps category first, then key, then legacy.
  - The SEPA alerts are key-first. The Accounts Manager role is not in the fallback.

## What you need to know

- **veg11:**
  - Backed up at `sites/veg11.veganisme.org/private/backups/20261104_055142-*`, then migrated.
  - The cooldown patch ran once: rows at 60 went from 80 to 60, and the total stayed at 89.
  - The `Staff Alert Event` table exists and is MyISAM.
  - The Email Queue is unchanged at 38,621 Not Sent rows. The scheduler is still off.
  - Web and workers were restarted. The live tree is at da7127969.
- **SEPA recipients (operators):**
  - Payments Settings `financial_admin_emails` is effectively only a fallback, because the seeded key rows already carry the admin roles.
  - To send SEPA mail to a particular person, give the key a Fixed recipient list in Verenigingen Email Configuration.
- **`test_notification_configuration_integration` wipes every Email Notification Type row** (88 to 0). Because a missing row counts as disabled, later classes in the same shard see every key disabled. It is commented on #2029. The new helper makes the tests that use it immune.
- **Test sites polluted by this session's runs.** These need `reset_test_sites.sh`, which needs the MariaDB root password, which I did not have:
  - test_site_4: Email Notification Type rows were rebuilt by guess.
  - test_site_5: about 55 leaked `staff1979-*` users, and a leftover trigger that makes `test_termination_utils` fail with "site must have no other trigger", identically on develop.
  - test_site_7 and test_site_8: notification tables emptied.
  - test_site_9: rows reseeded to the registry defaults.

## Open items

| Item | State |
|---|---|
| #1979 | P1 merged. Next is phase 3, the EmailService funnel, ahead of P2, the report. Carry-overs are in #2030's body. |
| #2043 | Maintainer decision: when an alert passes both a category and a key, should the key's configured recipients win? |
| #2044 | ANBI and periodic-donation senders count cooldown skips as sent, now with a 30-day ANBI window. |
| #2029 / #2053 | `singleton_backup` does not restore child tables. One module wipes the rows. There are four seeding helpers, and `allow_reminder_sends` never restores. |
| #2018, #2019, #2020 | Reminder templates read variables that are never passed. Templates are missing from the deprecated map (the suspension mail never sends). Dead `{{ base_url }}` links. |
| #2027 | A v15 patch writes the invalid policy "Role" with a list for the roles. |
| #2034, #2036 | Placeholder destinations. SEPA paths that still reach Administrator or return user names. |
| #2039 | The board-seat test helper leaks Members and Chapters. |
| #2025 / #1072 | Pre-existing query-budget reds in two payment integration tests. |
| #2004 | Parked. The `check_critical_errors` amplifier note is on it. |
| Carried over | The Ponto sandbox checks still need someone with sandbox access. PRs #1838 and #1896 are held. |

## Final state

- develop is at da7127969. Nothing from this session is open. The automerge queue is empty.
- Agents: none running. Test sites held: none.
- Worktrees: all of this session's are removed except `agent-worktrees/handoff-1104`, which holds this note.
- Dispatch README gained rules 24 and 25. The memory gained `two-green-merges-can-make-develop-red`.
