# 2026-11-04: the lock held, but the check read the past

Session "1102b" (verenigingen, 2026-11-02 into 11-04). It started from the two 2026-11-02 handoffs
(`2026-11-02-the-test-never-reached-the-branch.md`, `2026-11-02-a-test-edit-repacked-the-shards-onto-develops-pollution.md`).
The 1103 and 1103b sessions shared the bench, the ledger and the test sites. Session 6f reported a develop red.

The maintainer's instructions, in order:

1. Read the latest handoffs and list the open issues.
2. Put one agent each on: the Mollie/ING return pages, alerts/notifications, the fresh-install issues, and the
   Ponto/payments issues.
3. Rulings: #1996 yes; seed alert keys on migrate too; #1900 send without a link; #1984 create-only plus a reset action.
4. Rulings: a #1900 failed invoice waits until the invoice exists; #2038 uses a signed return token.
5. Rulings: #1900's held mail goes out through a staff retry action, and the retry is scoped by a persisted marker.
6. "generate a handoff while we wait".

## The one lesson to carry forward

**A row lock does not make a plain read see the newest data.** #1900's retry endpoint took `FOR UPDATE` on the
Member row before creating the invoice, so it looked serialised. Two real connections still created **two invoices
and sent two mails**.

- T2 had already taken its REPEATABLE-READ snapshot (the permission check and the application read) before it blocked
  on the lock.
- Once T1 committed and T2 got the lock, T2's "already has an invoice" check was a plain `frappe.db.exists`, a snapshot
  read. It could not see T1's invoice.
- The author's lock test only checked that a `FOR UPDATE` string came before the INSERT. That passes with the race
  fully present.
- What catches it is two threads, each with its own `frappe.init` and connection, T1 slowed inside the critical
  section. Use that shape for any "this lock prevents doubles" claim.
- The fix is the app's own pattern: `approve_application`'s `advisory_lock` (GET_LOCK) per application, then
  re-read state with a locking read after acquiring it.

A second lesson, again: **a reviewer "fixing" a test site with a Custom DocPerm pollutes it.**
- The #1900 reviewer added a System Manager read row on Item to get invoices created on test_site_10. Any Custom
  DocPerm row makes Frappe ignore the doctype's standard perms. I reset s10 from the snapshot.
- Item on these sites already carries 10 app-written Custom DocPerm rows, from migrate, including Verenigingen
  Administrator read. That is why **System Manager alone cannot read Item here, and invoice creation fails for a
  System-Manager-only test user.**
- Reviewer briefs now say "never add a Custom DocPerm".

## Merged this session

| PR | Closes | What |
|---|---|---|
| #1998 | #1959 | after_install seeds a Verenigingen Email Configuration row for every notification registry key; a fresh install no longer silently skips alerts. A real install-app gave 80/80 rows. |
| #2001 | #1956 (refs #1957, #1981) | Settings count as saved only when they have a company (and a company-less row is completed, not overwritten: review F1). Default membership types are created in an `after_sync` hook after fixtures load. The setup-created approval template is null-safe. The CI shard install log went from 3 failing after_install steps to 1 (the expected webhook user). |

## Open, in flight

| PR / item | State |
|---|---|
| **#2049** (#1996) | Mollie and ING Checkout returns go to our `/payment_success`. `make_payment` mints a return token from the verified `doc.name`. Reviewed, fix round coordinator-checked. Develop merged in (`2c9b06afe`) after #2047 fixed develop. The CI "Check Permission Bypasses" job failed on an artifact upload ECONNRESET (the validator itself PASSED). **I re-ran only that job.** Queue it in `approved_prs.txt` when CI is fully green. |
| **#2042** (#1900) | **Do NOT queue.** The pushed head `b1904cdd2` is superseded by local work in `~/agent-worktrees/fix-1900`. Local `69b9aa6a9`: a failed invoice holds the mail (reviewed, APPROVE). Local `da80529b5`/`b7f805d20`: the staff retry action, review **NEEDS CHANGES** (B1 above). **Round 4 is with the author on test_site_3** (brief in the ledger and below). After round 4: an independent re-review, then push (fast-forward) to #2042, then CI. |
| **#1838 / #1896** (Ponto callbacks) | Updated, independently reviewed, pushed (`23b0cc819`, `ee872b86a`). **Still HELD by the maintainer** until someone runs the Ponto sandbox signing and decline check with real credentials. The checklist is on PR #1838. Release-note items are on #1896. |
| **#2038** (ING guest return status) | Ruled: a signed return token in the ING return URL via `guest_return_tokens`. **Not started.** It waits for #2049 to merge, because it edits the same file (`ing_checkout/api/payment.py`). |
| **#2037** (seed registry rows on migrate too) | Ruled yes, filed. **Not started.** It waits for 1103's #2012 (PR #2048, v15 cooldowns into the registry plus a patch for seeded rows), which touches the same rows. |
| **#1984** (templates: create-only plus an explicit reset) | Ruled. **Not started.** It waits for 1103's PR #2035, which edits the same setup template code. |

### #1900 round 4 brief (as sent; check it against the author's report)

1. A new field on Membership Application Submission marks "invoice failed, approval email held". It is set at
   approval only on a failed invoice. The list and the retry cover only marked applications. A successful retry clears
   it. `create_invoice=False` never gets a retry.
2. **B1:** `advisory_lock` per application plus a locking re-read of the marker. Add a real two-connection test, red
   on `b7f805d20` first.
3. The list queries the marker directly. The old version took the newest 300 BEFORE filtering, which hid old failures.
4. **Late-retry coverage:** `create_membership_invoice_with_amount` uses `period_start=today()`, so a retry N days
   late double-covers N days against the schedule's `next_invoice_date`. The first invoice must start at the
   schedule's anchor (the running-period model). A test needs a backdated anchor.
5. The "already invoiced" predicate (if kept): Customer + `is_membership_invoice=1` + submitted, never "any
   non-cancelled invoice". Do not key on `member` alone; most real invoices have member NULL.
6. Refuse a retry for a member who has since terminated or quit.
7. JS: guard `escape_html(error.message)` in the catch.
8. A flaky test: `test_an_invoiced_approval_cannot_be_retried` failed 2 of 3 full-module runs on s10 with "Access
   denied. Required: high" right after an approve as the same user. It passes alone.
9. Fix the stale docstring.

## Maintainer rulings this session (all recorded on the issues and in `dispatch/author_brief_common.md`)

- **#1996:** Mollie and ING returns go to `/payment_success`, the same interim as Ponto, until frappe/payments#192.
  This supersedes #1875's "Mollie/ING stay".
- **#2037:** seed missing notification registry rows on migrate as well as on install.
- **#1900:** `create_invoice=False` sends the approval mail without a payment link. A FAILED invoice holds the mail
  until the invoice exists. The held mail is sent by an explicit staff RETRY action (no automatic hook). The retry is
  scoped by a persisted marker.
- **#1984:** setup only creates missing stock Email Templates. A separate, explicit reset action restores stock content.
- **#2038:** the ING guest return is authorised by a signed return token in the return URL (option B).

## Filed this session

| # | What |
|---|---|
| #1996 | Mollie payers land on the payments app's `/payment-success`, which says "accepted" for any outcome; ING returns 500 |
| #1997 | Sync Registry wrote Role-Based rows with no roles, so recipient lookup crashed (fixed by 1103 in #2031) |
| #2037 | Seed missing registry rows on migrate too (#1959 follow-up) |
| #2038 | ING guest return page always "Status Unknown": `handle_ing_checkout_return` calls an authenticated `@standard_api` (filed by the #1996 author). A comment adds that each Guest return writes an Error Log row. |
| #2041 | The approval mail may be sent twice: at approval, and again at Account Creation Request completion |
| #2045 | `mollie_checkout.make_payment` is an existence oracle for Guests (`_server_messages` and query count differ, unknown vs not-owned) |

Comments: #1875 (the return-page investigation table), #1957 (install failure fixed; `creation_user` still unwired on
a fresh install), #1981 (welcome template left as is, no sender), #1984, #1900 (the evidence plus four rulings), #1931
and PR #1838 (sandbox not measured, human checklist).

## What you need to know

- **Agent concurrency.** The maintainer asked for 4 agents at once, overriding the 2-agent cap for that batch. After
  that I kept to 2.
- **`bench new-site` is not possible for agents.** It needs the MariaDB root password, so a real fresh-install check
  is CI's job. One reviewer instead uninstalled and reinstalled the app on test_site_11; that site was reset after.
  The fresh-install facts that only CI could settle were read from the shard 4 install log of #2001's run.
- **Something on the bench wipes Email Configuration `notification_types` rows on test sites.** test_site_3 lost them
  twice in one session. It is not isolated; possibly #2029 (singleton_backup and child tables). Restore with
  `verenigingen.setup.notification_registry_setup.ensure_notification_registry_rows` in a console. #1900's tests now
  fail with a clear message naming the missing row instead of an opaque assert.
- **Item permissions on test sites:** see the second lesson. Do not "fix" it with a Custom DocPerm.
- **Develop red, 2026-11-03.** 1103's #2031 removed a crash that #2030's `test_staff_alert_event_1979` relied on. It
  was fixed by #2047 (`99ecedaa3`). A PR red only on that test before #2047 is not the PR's fault.
- **CI infra flake:** a job can fail at "Failed to FinalizeArtifact: ECONNRESET" after its validator passed. Read the
  log, then re-run only that job, and only on the run whose `headSha` is the PR head (README rule 23).

## veg11

- Not migrated this session. #1998 and #2001 are code-only: #1998's seeding runs only on install, and #2001 changes
  setup logic. veg11 still needs a **restart** to serve them, plus #1977/#1980 from the earlier handoff.
- #2037, once built, will seed the missing registry rows on veg11 at the next migrate.

## Final state

- **Agents:** the #1900 author (round 4, test_site_3) is running.
- **Sites held:** test_site_3 (the #1900 author). Everything else this session claimed is released. s10 and s11 were
  reset from the snapshot and migrated on develop.
- **Worktrees:**
  - `~/agent-worktrees/fix-1900` (live).
  - `~/agent-worktrees/fix-1996` (PR #2049; remove after merge).
  - `~/frappe-bench/apps/.wt-1815` and `.wt-1833` (held Ponto PRs).
  - `~/agent-worktrees/handoff-1104` (this note).
  - Removed: the alerts-1959-1900, fresh-install and investigate-return-pages worktrees.
- **Watching:** #2049 CI. No automerge loop is running, and `approved_prs.txt` is empty.
