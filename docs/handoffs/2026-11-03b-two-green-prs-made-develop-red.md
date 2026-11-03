# 2026-11-03b: two green PRs made develop red

Session `verenigingen-6f` (ledger tag `1103b`), 2026-11-02 into 2026-11-03. It picked up the open list from the
#1855/#1990 session (MijnRood applications became records). Sessions `1103` (verenigingen-1d) and `1102b`
(verenigingen-2b) shared the bench. **No agents are running and no test sites are held.** PR #2033 is waiting
on develop (see below).

## The lesson to carry forward

**Two PRs that are each green, each reviewed and each merged can still make develop red together.**

- #2031 (#1997) fixed a crash: a Role-Based notification row with NULL `recipient_roles` no longer raises.
- #2030 (#1979 P1) has a test, `test_staff_alert_event_1979.TestStaffAlertEvent.test_a_send_that_raises_still_leaves_a_failed_event`,
  that uses exactly that crash to make a send fail (`assertRaises(AttributeError)`).
- Both merged within ten minutes of each other on 2026-11-03. Every PR updated from develop afterwards goes red on that
  test ("AttributeError not raised"). This session saw it on #2033's shard 2/12, as its only failure.
- `premerge.sh` merges a PR onto the CURRENT develop and runs the gates, but it runs no tests. When two PRs in
  one queue touch the same area, run the second one's tests on the merged tree before merging it.
- A test that triggers a failure through a known bug is a test that a bug fix will break. Inject the failure some
  other way, such as a stub at the send boundary.

Owner: session 1103 owns both PRs and was messaged (verenigingen-1d, 2026-11-03). 1102b treats it as a
known develop failure.

## Merged this session

| PR | Closes | What |
|---|---|---|
| #2028 | #1964 | The chapter-join approval refuses a non-Active Member. The dashboard lists only join requests from Active members. |
| #2032 | #1988 | At approval, a blank account holder becomes the applicant's full name (maintainer ruling), then the IBAN history row is written. |

**Open:** #2033 (closes #1989). It refuses an Active member's reapplication whatever `application_status` says.
It is reviewed (CHANGES REQUIRED, then round 2, then a coordinator delta check). The branch was updated
onto develop afterwards, at `ae5438500`, which includes #2028 and #2032. On that merged tree, on test_site_3:
`test_application_record_approval` 77/77 and `test_active_member_reapply_1989` 5/5. Its CI is red only because of
the develop collision above. **Once develop is fixed:** update-branch, then a fresh CI run, then `premerge.sh`,
then merge pinned to the head.

## What each fix found beyond its issue

In all three, the harm was larger than the issue stated. Each was found by driving the real flow.

- **#1989.** On develop, approving an Active/"Pending" member's application did not just pass. It overwrote the
  existing member's name, IBAN and `member_since`, and it created a new Membership. The match is on email only.
  veg11 (read-only count): **51 members are Active/Pending**, which is the exposed set. 0 are Active/Rejected.
- **#1988.** A `/word-lid` applicant paying by SEPA Direct Debit with no holder made approval itself fail
  ("Account Holder Name is required"), not just the history step.
- **#1964.** A Suspended member could be approved into a chapter too, not only a never-approved one.
  The review then found that the fix had an opposite harm in the dashboard listing. The listing still showed
  unapprovable rows, and it hid Active members whose `application_status` was the default "Pending". Round 2
  keyed the listing on the same rule as the guard.

## Mistakes caught in review, worth knowing

- **A test edit justified by a false premise.** #1989's author made 3 red tests green by setting `status="Pending"`,
  justified as "what a MijnRood sync with a Pending mapping does". `MemberImportService.STATUS_MAP` has no Pending.
  A MijnRood-synced member IS the #1989 state. The edit was still valid (a legacy or mid-approval Pending
  member), but the stated reason was wrong. The reviewer also found a 4th red test in a module the author had
  never run. **Before editing a test to go green, check the premise of the edit in the code.**
- **A test that never reached the code it named.** #1988's "whitespace holder counts as blank" passed with the
  helper's `.strip()` removed, because the input is stripped upstream. It now uses a stored whitespace holder
  on an existing member.
- **"Pre-existing on develop" turned out to be site data.** `test_application_review_cor_rules` failed 5/5 on
  test_site_3 both ways, and it passes on test_site_1. The rule rows weren't seeded on s3 because it hadn't been
  migrated since #1959. **test_site_9 needed a full `migrate`, and test_site_3 and test_site_10 needed `reload-doctype "Membership Application Submission"`.**
  Several test sites are behind develop's schema.

## Issues

**Filed:**
- #2021: `join_chapter` / `request_to_join` write Pending rows for non-Active members.
- #2022: an IBAN change with a blank holder raises MandatoryError (open question: default or refuse).
- #2023: approval ignores the IBAN-history step's result.
- #2024: boards have no reject action for a join request.

#2021 and #2024 need a product call: may a non-Active member request to join a chapter, and should boards get Reject?

**Commented, recommend closing** (code deleted by #1765/#1976 or already fixed):
- #906, #1199
- #1583
- #1104
- #1051
- #1867
- PR #1201 (it edits a deleted function)

**#1209 is only half obsolete:** `templates/pages/payment_retry.html:92` still links to a route that does not exist.

## Housekeeping

#1964 and #1988 worktrees and branches are removed. These are left for removal after #2033 merges:
- worktree `~/agent-worktrees/fix-1989-active-member-reapply`;
- its local branch.

`dispatch/author_brief_common.md` gained the #1988 ruling.
