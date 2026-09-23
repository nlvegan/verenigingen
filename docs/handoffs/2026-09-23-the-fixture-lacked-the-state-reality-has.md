# 2026-09-23 — the fixture lacked the state reality has

Eighteen issue dispatches to sonnet agents. #1258 went first, then **seventeen** went through a
rolling pool of four. That is one more than the sixteen (four batches of four) that were asked
for: I lost count mid-session, and a recount against the ledger caught it. Each author had its
own test site, and an independent `skeptical-code-reviewer` ran on a second site. Seventeen of
the dispatches produced a PR, and all seventeen merged, along with #1263 and #1275 carried over
from 2026-09-22b. That is nineteen merges in total. One dispatch (#1267) stopped correctly on a
design question, and 25 issues were filed.

The previous three handoffs all recorded the same shape: every blocking finding was in a test
or an instrument. **This session broke that.** Blocking findings landed in production diffs.
Most of them share one mechanism, which is the headline. The tests passed because the fixture
lacked a piece of state that real data always has, or had a piece that real data lacks.

## What shipped

All merged, each pinned with `--match-head-commit` to the commit the independent review
approved, after full green CI.

| PR | Issue(s) | What it does | Review rounds |
|---|---|---|---|
| #1275 | #1272 | run-scoped chapter board roles (carried over from 2026-09-22b) | 1 |
| #1263 | #1251, #1252 | (carried over) DD batch child-table handlers; `cc3910c6d` (the round-4 answer) got its own narrow review | 5 |
| #1278 | #1258 | amount+reference matcher: `sepa_file_generated` + LIKE-escaped bank reference | 1 |
| #1280 | #1242 | `mark_batch_invoices_as_paid` requires a generated SEPA file | 1 |
| #1281 | #1092 | `get_donation_status` checks Donation read permission | 1 |
| #1283 | #1240, #1241 | Weekly/Semi-Annual in the frequency lists, each checked against the DocType options | 1 |
| #1285 | #1200 | three Payment Entry builders get company + correct accounts (payment-plan paid_from/paid_to were also **swapped**) | 2 |
| #1289 | #1218, #1219 | the unpaid-invoice loader requires EUR + a member/schedule link; "Loaded N of M" via `total_eligible` | 1 |
| #1292 | #1208 | "View Board History" repointed at the whitelisted twin | 1 |
| #1295 | #1195 | an additive role grant survives the role-profile re-derive, at 16 sites including `add_roles()` | 2 |
| #1298 | #1273, #1274 | `ensure_chapter_role` is a real shared fixture; "Test Chair" run-scoped | 2 |
| #1301 | #1173, #1165 | one Error Log row per failure on two retry paths | 1 |
| #1302 | #1268 | reconciliation test teardown actually deletes; random `reference_number` | 1 |
| #1303 | #1229 | the Chapter Role skipped-propagation is visible and names the real recovery button | 2 |
| #1308 | #1177 | `FinancialErrorHandler.error_log` bounded | 1 |
| #1312 | #1304 | `MolliePerformanceMonitor.metrics` bounded | 1 |
| #1316 | #1284 | the donation-status existence oracle closed, including for share recipients | 2 |
| #1317 | #1256, #1261 | a dead JS handler removed; the SEPA Mandate Connections tab no longer crashes | 1 |
| #1290 | #1264 | all 5 live dues-schedule delete paths respect the invoice link, inside a savepoint | 3 |

Closing-keyword accidents, in both directions:
- **#1251** was fixed by #1263 but not auto-closed ("Fixes #1252 first, then #1251" bound only
  the first number). Closed by hand.
- **#1236** was auto-closed by #1280 although it was **not** fixed. #1280's body said "Did not
  fix #1236", and GitHub matched `fix #1236` inside the negation. The handoff fact-check caught
  it, and #1236 was reopened. Every author brief warned about this exact trap, and one author
  wrote it anyway. A sweep of all 19 merged PRs' `closingIssuesReferences` found no other
  spurious close.
- **#1051** was fixed by #1202 and never closed. A comment recommends closure.

**Stopped, no PR:**

- **#1267.** The obvious fix is a global UNIQUE index on `Bank Transaction.reference_number`.
  That contradicts the app's own design. `bank_transaction_creator._find_matching_bank_transaction`
  (#383) deliberately scopes idempotency by `(reference_number, bank_account, company)`, and its
  recovery branch would mis-handle the DuplicateEntryError that a global index raises. The only
  duplicate group on veg11 is the `REF123` test leak that #1302 fixes. **The index scope needs a
  human decision**, recorded on #1267.
- **#1088, #1093.** Never dispatched. Both are ownership checks on member-money endpoints, and
  both depend on **#1101**: may an admin act on a member's behalf? 5 endpoints refuse and 1
  allows. A treasurer creating a mandate for a member is a real flow, so an agent would have to
  guess.

## The pattern: the fixture did not have the state that breaks the fix

| PR | what the fixture lacked or carried | what it hid |
|---|---|---|
| #1290 r1 | the author's fixture edits **cleared** the Member's own `current_dues_schedule` back-link, which a production hook sets for every real schedule | a plain `delete_doc` was refused for **every** ordinary schedule, not only invoice-referenced ones. Every Membership delete would have stranded its schedule. CI caught it in 2 shards |
| #1290 r2 | `setUp` took `frappe.db.get_value("Membership Type", {}, "name")` (an arbitrary row) with a site-measured `dues_rate = 150` | green on test_site_3, ValidationError on test_site_8 |
| #1316 r1 | no test user had a Donation **shared** with them | a doc-less `has_permission` falls through to `false_if_not_shared()`, which returns True if *any* Donation is shared. The oracle the PR closed reopened for every share recipient |
| #1285 r1 | test_site_2 carried a leftover `Ponto Settings.sandbox_client_id` | two new tests ERRORed on any clean site. The same file already set that value in a sibling test, with a comment explaining why |
| #1303 r1 | the test never re-saved the role after the deferred save | the new user-facing message said "save this role again", and a re-save is a no-op (`on_update` is gated on `has_value_changed("is_chair")`). The real recovery is the "Update Affected Chapters" button |

**The rule this suggests:** when a fix is a *guard* (a refusal, a permission check, an
exclusion), the review question is not "does the test fail without the fix" but "**what state
does production always have that this fixture does not**". A fixture edit that clears a field
to isolate a scenario is the tell. #1290's edit was well-intentioned, and it was exactly what
hid the regression. The briefs asked every reviewer to hunt the opposite harm, and that is
what found #1290, #1316 and #1303. Keep that item in the brief.

## The second pattern: a sweep grepped one spelling

| PR | the sweep grepped | the live sibling it missed |
|---|---|---|
| #1295 | `append("roles"` | `User.add_roles()` in `volunteer_sync_service.py:185`, 30 lines below a comment calling `add_roles()` "futile" for exactly this reason |
| #1290 | the 3 sites the issue named | `member_merge_service.py:402`, a `force=True` schedule delete on the whitelisted `execute_merge` |
| #1303 (the reviewer's own AST sweep) | calls by function name | the reverse error: 2 hits that were same-name collisions (`self.update_webhook_urls()` vs a decorated module-level `update_webhook_urls`), which it ruled out. A name-based sweep both over- and under-counts |

Same lesson as #394 and #1210. The explanation beside one instance **is** the search query:
`add_roles` was named in the file's own comment.

## Gates: a push-only ratchet was missing from the brief

- **The order-dependence ratchet reddened #1290 in CI** with `COMMIT
  services/billing/test_invoice_management.py::4 -> ::5`, from one bare `frappe.db.commit()` in a
  fixture. The step is "Baseline is in sync with the tree", and a PR may not grow that baseline.
  Neither the author brief nor the reviewer brief mentioned it. Both were patched mid-session,
  and every later author ran `scan_order_dependence.py` before pushing. **Put it in future briefs
  from the start.**
- **The scanner has two blind spots, filed as #1311.** It walks only `test_*.py`, so a commit in
  `tests/utils/*.py` is invisible. #1290 r2 did exactly that, and its PR body said so *as a
  reason* while also claiming "no bare commit added". Its REUSE check also misses
  `frappe.db.get_value`, which is the #1290 r2 fixture shape.
- **The COMMIT exemption is keyed on the function-name prefix (#825).** #1298 renamed
  `_delete_class_chair_role` → `_cleanup_class_chair_role`. The reviewer judged that honest: it
  really is an `addClassCleanup` helper, its commit is load-bearing, the baseline diff is one
  `COMMIT_EXEMPT` line, and the gated total is unchanged at 1004. It is recorded on #825 because
  the honesty rests on review, not on the tool.

## Things that are true now and were not assumed before

- **Frappe controller `has_permission` hooks can only deny.** `has_donation_permission`'s
  member/board branches are dead for doc-level checks, which #258 already documents. Every
  "owner may read their own X" argument in this app has to be checked against DocPerm, not the
  hook.
- **`frappe.has_permission(doctype, ptype)` with no doc returns True if ANY document of that
  doctype is shared with the user.** Pass `ignore_share_permissions=True` when the question is
  "does this user have role-level access".
- **`@high_security_api` hardcodes HIGH regardless of `operation_type`.** HIGH is
  role-profile-only. Board members get "Verenigingen Chapter Board Member" through
  `get_board_member_profiles()`'s hardcoded fallback when no chapter configures one, and on veg11
  no chapter does. The only bare-role System Manager or Verenigingen Administrator on veg11 is
  `Administrator`, and Rule 0 exempts it.
- **`update_password()` → `reset_user_data()` does a full `User.save()`**, which re-runs
  `populate_role_profile_roles()` and strips any role outside the profile. Login and the
  reset-email path do not (they use `db_set`). The durability gap is tracked as #1293.
- **One Mollie payment webhook records one `record_operation_performance` call.** The "10 call
  sites" are mutually exclusive branches.
- **`SEPA Mandate.mandate_id != name`** on real data (e.g. `38hh8emqjf` vs
  `40123603-V004040-00003`), so nothing keyed on `mandate_reference` can link by docname.

## Process notes

- **Quota death, handled.** The org's monthly spend limit killed 4 agents at about 04:10. All
  three authors held uncommitted work and no commit for their round. Their diffs, untracked files
  included, were saved to patches **before** resuming. `git stash` was not used, because it is
  shared across worktrees. All four resumed cleanly from their transcripts.
- **The round that answers a review was reviewed every time.** Six PRs needed a second round and
  one needed a third. #1290's third round found real atomicity corruption, which a savepoint now
  fixes. #1263's answering commit got its own narrow review before merge, which turned up a
  docstring miscount (17 vs 20, filed as #1279).
- **Closing keywords.** #1263's body read "Fixes #1252 first, then #1251", and GitHub bound only
  the first number, so #1251 had to be closed by hand. #1051 had been fixed by #1202 and never
  closed; there is now a comment recommending closure.

## Decisions waiting on a human

1. **#1101**: may an admin act on a member's behalf at the six `validate_member_ownership`
   endpoints? This blocks #1088 and #1093.
2. **#1267**: what scope should a Bank Transaction reference-number uniqueness constraint have
   (per account, per account and company, a derived key as in #809, or none)?
3. **#1288**: a payment-plan installment is saved as Paid *before* its Payment Entry is created,
   and `create_payment_entry` swallows its own exceptions. Which should change?
4. **#1306**: should deleting a Member proceed when its schedule could not be deleted because an
   invoice still references it?

## Filed this session

#1277, #1279, #1282, #1284 (fixed by #1316), #1286, #1287, #1288, #1291, #1293, #1294, #1296,
#1297, #1299, #1300, #1304 (fixed by #1312), #1305, #1306, #1307, #1309, #1310, #1311, #1313,
#1314, #1315, #1318.

The highest-value open ones:
- **#1288**: silent "Paid, no Payment Entry".
- **#1277**: 8 unescaped LIKEs on bank/Mollie identifiers in dedup paths.
- **#1314**: 5 more `get_doc`-before-permission existence oracles.
- **#1311**: the scanner blind spots.
- **#1307**: 3 test classes that skip `super()` and get no rollback.
