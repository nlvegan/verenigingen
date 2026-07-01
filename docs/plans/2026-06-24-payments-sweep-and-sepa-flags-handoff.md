# Handoff — payments/services sweep + money-path remediations + SEPA flag cleanup (2026-06-24)

## TL;DR
Started from "open follow-ups?". Closed the entire backlog (items 1–6), ran a
`verenigingen_payments/services` coverage sweep, fixed the money-path bugs it (and a
`FAIL_ON_ERROR_LOG` audit) surfaced, removed a dead orchestration cluster, and fixed
all remaining SEPA flags including a real FRST/RCUR pain.008 compliance bug.
**Everything is committed AND pushed to `develop`. Final gate is GREEN
(run 28127340609 @ `50a48152`). Nothing open that blocks.**

## Final state
- Branch `develop`, fully pushed (local == origin), `50a48152` is HEAD.
- **GATE GREEN: Server Tests run `28127340609` @ `50a48152`** (after a `gh run rerun
  --failed` cleared a transient shard-6 flake — see Gotchas).
- All new tests verified green on **veg11** (canonical), not just writer test sites.

## Commits this session (all pushed, newest first)
| SHA | Type | Summary |
|-----|------|---------|
| `50a48152` | fix(sepa) | pain.002 return parser: delegate to canonical `utils/sepa_return_parser` (was a stub); `find_invoice_in_batch` matches the `INV-`prefixed EndToEndId. |
| `5aff995e` | fix(email) | donation_confirmation/donation_payment_confirmation templates used `{{ doc.* }}` but senders pass a flat-key context (no `doc`) → UndefinedError → email silently dropped. Aligned to flat keys. |
| `b863d59a` | fix(sepa) | FRST/RCUR pain.008 compliance: one `PmtInf` per sequence type; advance mandate usage to Collected on confirmed collection (option B). |
| `39bb273e` | fix(sepa) | Deleted dead module-level `update_membership_payment_status` (phantom Membership fields, zero callers). |
| `1f476d06` | fix(payments) | Two live money-path bug fixes + deleted the dead `BusinessLogicOrchestrationService` cluster (−1,283 LOC). |
| `f55e393d` | test(payments) | 124-test coverage sweep on payments/services money-path modules. |
| `86c26315` | fix(sepa) | `validate_batch_creation` now actually rejects invalid batches (was letting bad SEPA batches through the creation gate). |
| `e3cae791` | fix(mollie) | refund_handler happy-path breadcrumbs no longer pollute the Error Log doctype. |
| `d56daaaa`, `d1df7bef`, `a0f1e99f` | test/fix | Earlier follow-ups 3/4/5 (volunteer activation coverage, drop moot ACR guards, un-baseline 3 order-dependent stragglers). |

## Bugs fixed (highest-value first)
1. **`mark_batch_invoices_as_paid` was 100% broken** (`1f476d06`): the LIVE "Process
   Payments" UI flow created+submitted Payment Entries, then `save()`d a submitted
   batch while writing non-`allow_on_submit` fields → always raised
   UpdateAfterSubmitError. Fixed with `db_set(update_modified=False)`, no commit
   (stays atomic with the PEs).
2. **Donation JE silently never created** (`1f476d06`): `donation_journal_entry_creator`
   set `cheque_date` but blank `cheque_no` when `create_from_dict` had no reference →
   ERPNext rejected the submit → `secure_document_operation` swallowed it. Found by the
   `FAIL_ON_ERROR_LOG=1` audit (a normal green run hid it). Fixed by guarding the
   cheque pair.
3. **SEPA batch-creation gate inert** (`86c26315`): `validate_batch_creation` collected
   errors but never set `is_valid=False`, so the orchestration gate admitted invalid
   batches. Verified the fix has no false-positive risk (does not call the phantom
   mandate path).
4. **FRST/RCUR pain.008 cannot be emitted** (`b863d59a`): the XML built one `PmtInf`
   with a hardcoded RCUR; a legitimate FRST row crashed XML generation, a first
   collection left RCUR would be bank-rejected. Now one homogeneous `PmtInf` per
   sequence type; mandate usage advances FRST→RCUR on confirmed (non-returned)
   collection (option B — spec-faithful: a returned FRST stays FRST). Single-sequence
   batches stay byte-identical; multi-group `PmtInfId` capped to the SEPA 35 chars.
5. **donation email templates broken** (`5aff995e`) and **pain.002 returns never
   actioned** (`50a48152`) — see commit table.

Plus deleted: the dead `BusinessLogicOrchestrationService` + its phantom-column methods
(`validate_sepa_sequence_types`, `validate_mandate_coverage`, `_check_customer_mandate`,
`_get_eligible_invoices_for_automation`) and two dead phantom-field membership writes.
SEPA Mandate links by `member`, not `customer`; there is no `Membership.payment_status`.

## Process notes
- Every prod change was skeptical-reviewed. Two reviews returned REQUEST CHANGES and
  both were addressed before commit: (a) the `mark_mandate_usage_collected` was guarded
  so a usage-tracking error can never reclassify a paid invoice as Failed (double-debit
  guard) + the `PmtInfId` length cap; (b) the pain.002 parser was rewritten to delegate
  to the existing canonical parser instead of duplicating it.
- Ran `VERENIGINGEN_FAIL_ON_ERROR_LOG=1` audits after each batch of work — they caught
  the masked donation-JE bug and confirmed the rest produce no swallowed Error Logs.

## Open / follow-ups (none blocking)
- `process_batch_returns` is now wired to a real pain.002 parser, but the SUCCESS side
  of returns (marking non-returned collections) still flows only through
  `mark_batch_invoices_as_paid` (option B). Revisit the end-to-end returns flow at SEPA
  go-live, including whether group/payment-info-level pain.002 status should be honored
  (the canonical parser, like the old code, only reads per-transaction TxSts).
- The two CAR auto-approval tests (`test_enhanced_auto_approval_logic`,
  `test_small_adjustment_auto_approval`) are BASELINED and fail in isolation since the
  `640bb8a1` self-service guard (members never auto-approve). They are tolerated, not
  fixed — decide at go-live whether the tests or the guard need reconciling.
- Member self-service fee/type adjustment (`640bb8a1`) is enabled+guarded but exercised
  only by tests; verify end-to-end in a real portal session before relying on it.

## Gotchas learned/reaffirmed
- **Run the pre-implementation checklist (search `utils/` first).** I skipped it and
  hand-rolled a pain.002 parser that already existed; the review caught it.
- **The pre-commit `black` hook EXCLUDES `verenigingen/tests/`** (see the exclude regex
  in `.pre-commit-config.yaml`). Standalone `black --check` will disagree with what CI
  gates on — do NOT amend test files to standalone-black output.
- **Adding test METHODS to existing files shifts the timing-based shard split**, which
  re-exposes pre-existing order-dependent failures (the baseline is coupled to layout).
  Distinguish these (pass in isolation / already baselined / transient framework races
  like `TimestampMismatchError` in `membership_type.after_insert`) from real regressions
  by checking whether your change is logically related. `gh run rerun <id> --failed`
  clears transient races.
- `git stash pop` run from `/home/frappeuser/frappe-bench` (NOT the repo, which is
  `apps/verenigingen`) silently fails after a `bench` command resets cwd — pop again
  from the app dir.
- `frappe.log_error(message, title)` in this Frappe stores message→`method` field,
  title→`error` field (no `title` column). Filter Error Logs accordingly.
- Watch the GitHub API rate limit: use single-shot `gh run view <id>` in a sleep loop,
  not `gh run watch`.

## Memory written (this session)
- `payments-services-sweep-and-remediation-2026-06-24.md`
- `sepa-frst-rcur-and-flag-cleanup-2026-06-24.md`
- `donation-template-and-pain002-2026-06-24.md`
- `followups-3-4-5-isolation-and-ceiling-2026-06-24.md`
