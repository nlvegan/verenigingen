# Root-cause analysis: CI fallout from the `in_import` harness removal

Date: 2026-07-31
Supersedes the failure taxonomy in `2026-07-31-in-import-harness-fallout-handoff.md` §2.
Evidence: CI run `30579228391` (12 shards, branch `test/coverage-sweep-agent-suites`, which
carries the same harness commit as `test/harness-production-fidelity`).

---

## 0. Correction to the handoff

The handoff reports **169 failures**. The actual count is **236 failure blocks** across
235 distinct tests. The undercount came from the log-grep trap the handoff itself documents:
the runner emits `\x1b[41m ERROR \x1b[0m test_name (...)`, not `ERROR: test_name`, so a
`(ERROR|FAIL):`-anchored match misses most blocks.

Parser used: `scratchpad/parse.py` — strips ANSI + timestamps, anchors on
`^\s*(ERROR|FAIL)\s+(test_\S+)\s+\(([^)]*)\)`.

---

## 1. Root causes, by volume

| # | Root cause | Blocks | % | Modules | Kind |
|---|---|---:|---:|---:|---|
| RC2 | `_validate_selects()` restored — invalid Select values written | 98 | 41.5% | 30 | mostly test data; **1 production bug** |
| RC1 | `set_posting_time` unset — ERPNext overwrites `posting_date` | 65 | 27.5% | 8 | test-only; **fix incomplete** |
| RC8 | Behavioural assertion failures | 30 | 12.7% | 16 | **not yet triaged** |
| RC5 | Coverage period `start == end` at period boundary | 16 | 6.8% | 4 | **production bug** |
| RC3 | Autoname regeneration restored — hardcoded `name` no longer honored | 12 | 5.1% | 3 | test-only |
| RC4 | Isolation cascade from RC2 | 11 | 4.7% | 1 | test-only |
| RC6 | `_set_defaults()` restored — `currency` defaults to INR | 3 | 1.3% | 1 | test-only (probable) |
| RC7 | TimestampMismatch | 1 | 0.4% | 1 | untriaged |

Four mechanisms account for 87% of the fallout, and each is a *single* framework behavior
that `in_import` had been suppressing.

---

## 2. RC1 — `set_posting_time` (65 blocks) — **the handoff's "FIXED" is incomplete**

Mechanism (verified, `erpnext/utilities/transaction_base.py:29-35`): `validate_posting_time()`
sets `set_posting_time = 1` implicitly when `frappe.flags.in_import` is on. Without it, any
document that does not set `set_posting_time` has its explicit `posting_date` **silently
replaced with `now()`**.

`f57e1e86` added `set_posting_time: 1` to the two builders in `enhanced_test_factory.py`.
That covers **45 of 65 blocks**. The remaining **20 blocks in 3 modules build Sales Invoices
directly with `frappe.new_doc("Sales Invoice")` and never touch the factory**:

- `tests/backend/components/test_payment_processing_api` (7)
- `tests/backend/integration/test_payment_report_integration` (7)
- `tests/backend/components/test_payment_processing_api_real` (6)

These are the *worst* cases, not incidental ones — they deliberately backdate:

```python
# test_payment_processing_api_real.py:111-118
invoice = frappe.new_doc("Sales Invoice")
if status == "Overdue":
    invoice.posting_date = add_days(today(), -45)
    invoice.due_date    = add_days(today(), -15)
```

Without `set_posting_time`, the 45-day-old invoice posts today, so the "overdue" fixture is
not overdue and the report assertions under test are meaningless.

**Production impact: none found.** The only production writers of `posting_date` on
`TransactionBase` documents use `today()` (`invoice_generator.py:655`,
`approval/application_payments.py:98`). The one genuinely backdated write —
`expense_submission_service.py:504`, `posting_date=request.expense_date` — targets
**Expense Claim**, which extends `AccountsController` but never calls `validate_posting_time()`,
so it is unaffected.

**Fix:** add `set_posting_time = 1` to the three direct builders.

---

## 3. RC2 — invalid Select values (98 blocks)

Mechanism (verified, `frappe/model/base_document.py:1093-1094`): `_validate_selects()` is
gated on `frappe.flags.in_import` **alone**. Nothing else disables it — not `in_test`, not
`in_patch`.

| Field | Bad value | DocType allows | Blocks |
|---|---|---|---:|
| `contribution_mode` | `Tier` | `Fixed`, `Income-Based`, `Flexible` | 42 |
| `contribution_mode` | `Custom` | ″ | 8 |
| `permissions_level` | `Membership` | `Basic`, `Financial`, `Admin` | 8 |
| `campaign_type` | `General` | `Annual Giving`, `Capital Campaign`, … | 6 |
| `status` (SEPA DD Batch) | `Pending` | `Pending Upload`, `Uploaded`, … | 5 |
| `payment_type` | `One-off` | `One-Time` | 5 |
| `status` (SEPA Mandate) | `Inactive` | `Draft`, `Active`, `Cancelled`, `Expired`, `Suspended` | 2 |
| … 12 more, 1–2 each | | | 22 |

### The dominant case is a schema rename never propagated to tests

`Membership Dues Schedule.contribution_mode` was renamed to `Fixed / Income-Based / Flexible`.
The old vocabulary (`Tier`, `Calculator`, `Custom`) survives only in test code — including a
stale comment asserting the opposite:

```python
# tests/fixtures/sepa_test_factory.py:182
"contribution_mode": kwargs.get("contribution_mode", "Tier"),  # Valid options: Tier, Calculator, Custom
```

**Production code is clean** — every service writes `Fixed`, `Income-Based` or `Flexible`
(`contribution_amendment_approval_service.py:533`, `dues_schedule_auto_creator.py:703,1078`,
`template_creation_service.py:99`, `dues_schedule_health_manager.py:243`). With one exception:

### 🐞 Production bug P1 — a live patch writes invalid Select values

`verenigingen/patches/v2_0/migrate_membership_type_billing_to_dues_schedule.py:71-79`,
registered in the active `verenigingen/patches.txt:17`:

```python
contribution_mode = membership_type.contribution_mode
if contribution_mode == "Tiers":
    contribution_mode = "Tier"          # not a valid option
elif contribution_mode == "Both":
    contribution_mode = "Calculator"    # not a valid option
template.contribution_mode = contribution_mode
else:
    template.contribution_mode = "Calculator"   # not a valid option
```

All three write-paths produce values the DocType rejects. Patches run under `in_patch`, which
does **not** disable `_validate_selects()`, so this throws on any site where the patch still
has to run against legacy data.

### Not a bug: the public application form

`templates/pages/membership_application.html` posts `contribution_mode` as
`calculator` / `quick` / `custom` (lowercase, all invalid). Traced the full submit path —
the value reaches only `validate_contribution_amount()`, a read-only validation endpoint, and
is never persisted to a `Membership Dues Schedule`. Cosmetic inconsistency, not a defect.

---

## 4. RC5 — 🐞 Production bug P2: first invoice fails at a period boundary (16 blocks)

`services/billing/coverage_calculator.py:144-151` — first-invoice branch:

```python
period_start, coverage_end = self.calculate_billing_period(self.billing_frequency, reference_date, ...)
membership_start = self._get_membership_start_date()
if membership_start and getdate(membership_start) > getdate(period_start):
    coverage_start = getdate(membership_start)
```

and `coverage_calculator.py:184-189` rejects the result:

```python
if getdate(coverage_start) == getdate(coverage_end) and self.billing_frequency != "Daily":
    return OperationResult.fail(f"Invalid coverage period: start date ... must be before end date ...")
```

When a member's `Membership.start_date` is **the last day of their billing period**,
`coverage_start` is set to that date, `coverage_end` is already that date, and the equality
check throws. Verified against the real `calculate_billing_period` on `veg11`:

| Frequency | `start_date` | Period | Result |
|---|---|---|---|
| Monthly | 2026-07-31 | (2026-07-01, 2026-07-31) | `start == end` → **throws** |
| Monthly | 2026-06-30 | (2026-06-01, 2026-06-30) | **throws** |
| Quarterly | 2026-06-30 | (2026-04-01, 2026-06-30) | **throws** |
| Annual | 2026-12-31 | (2026-01-01, 2026-12-31) | **throws** |

**Impact:** a real member who joins on the last day of a month cannot have their first invoice
generated — 12 days a year on Monthly billing, 4 on Quarterly, Dec 31 on Annual.

This is **pre-existing production logic, not caused by the harness change.** CI surfaced it
because the run crossed into 2026-07-31, a month end. Whether these 16 tests would also fail
on `develop` today is being checked by baseline run `30583855229` (see §7).

**Reproducible without calendar dependence:** pass `force_date` inside the period and set
`Membership.start_date` to that period's last day — e.g. `force_date=2026-06-15`,
`start_date=2026-06-30`.

---

## 5. RC3 — autoname regeneration (12 blocks)

Mechanism (verified, `frappe/model/naming.py:158`):

```python
if autoname.lower() not in ("prompt", "uuid") and not frappe.flags.in_import:
```

Under `in_import` an explicitly-assigned `name` survives insert. Without it, `Member` gets its
naming series (`Assoc-Member-YYYY-MM-####`) and any hardcoded cross-reference breaks:

```python
# tests/chapter/test_role_profile_managers.py:250-267
test_member = frappe.get_doc({"doctype": "Member", "name": "Test Member", ...})
test_member.insert()
test_volunteer = frappe.get_doc({"doctype": "Volunteer", "member": "Test Member"})  # LinkValidationError
```

Same shape in `tests/backend/components/test_chapter_assignment_edge_cases.py`
(`TEST-MEMBER-33838b-001`, `PERF-ROSTER-MEMBER-000…`). Test-only; fix by using the inserted
document's actual `.name`. Consistent with the standing note that `Member.name` is *always*
`Assoc-Member-…`.

---

## 6. RC4 — isolation cascade (11 blocks), one module

`tests/integration/test_sepa_mandate_authentication_security.py` fails 11 times with
`UniqueValidationError: Duplicate entry 'ACTIVE-Assoc-Me' for key 'mandate_id'`.

Two latent test defects combine:

1. `mandate_id = f"ACTIVE-{active_member.name[:8]}"` (line 231). Every Member name starts
   `Assoc-Me…`, so **the id is a constant** — and `SEPA Mandate.mandate_id` is `unique: 1`.
2. The same `setUp` then inserts a mandate with `status="Inactive"` (line 254) and another
   with `status="Pending"` (line 273) — neither is a valid option (RC2).

The RC2 throw aborts `setUp` *after* the first mandate is inserted; `tearDown` does not run
when `setUp` raises, so the row survives and every later test collides on it.

Inference on ordering is strong but not directly instrumented. **It is also cheap to falsify:**
fixing only the two Select values should clear all 11 duplicates. Do that before touching
`mandate_id`, then make the id unique anyway — a constant unique key is a landmine regardless.

---

## 7. Baseline run — separating harness-caused from calendar-caused

`gh run 30583855229` — `server-tests.yml` dispatched on **`develop`** on 2026-07-31, a month
end, with no harness change. This is the control the previous session lacked.

- Failures appearing in **both** runs → pre-existing or calendar-driven; **out of scope** for
  the harness PR (RC5 is the expected occupant).
- Failures appearing **only** in run `30579228391` → genuinely caused by the harness change
  (RC1–RC4, RC6 expected here).

The `known_test_failures.txt` baseline is empty (`matched baseline (allowed): 0`), so the CI
gate cannot make this distinction on its own.

---

## 8. Recommended order of work

1. **RC1 remainder** (20 blocks, 3 modules) — mechanical, mechanism already proven.
2. **RC3** (12) — mechanical.
3. **RC2 test data** (97 of 98) — bulk, but each is a lookup against the DocType `options`
   list. Start with `contribution_mode` (50) and the `sepa_test_factory` default.
4. **RC4** (11) — should fall out of step 3; verify, then fix the constant `mandate_id`.
5. **P1** (patch writing invalid Select values) — separate commit, arguably its own PR;
   independent of the harness work.
6. **P2** (coverage period at boundary) — **separate PR.** Real production defect, pre-existing,
   with a deterministic regression test. Not a harness concern.
7. **RC8** (30) — individual triage, do last; these are the ones most likely to hide further
   real bugs, since a behavioural assertion changing means production *behavior* changed, not
   just data validity.
8. **RC6, RC7** (4) — trivial tail.

## 9. Standing method note

RC1 and RC5 both surfaced *only* because the run crossed a date boundary. Both are silent on
any other day. When fixing anything in this fallout, **assert the value directly** rather than
letting a downstream validation notice — and prefer `force_date`-style injection over
dependence on `today()`.
