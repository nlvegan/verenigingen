# v16 Baseline Error Triage — 2026-05-31

Triage of the **1,981 errors** (+ 396 failures) from the first full local v16 baseline
run (frappe v16.19 / erpnext v16.20 / Python 3.14, 3 fresh CI-mirror sites).

- Source logs: `/tmp/baseline_v1620_shard{1,2,3}.txt` (8,699 tests · 6,322 pass · 396 fail · 1,981 err)
- Parser: `/tmp/triage.py` → `/tmp/triage_records.pkl` (all 2,377 ERROR+FAIL blocks, exception type + message)

## Headline finding

The handoff guessed "mostly v15→v16 API drift." **The data says otherwise.** The dominant
root causes are **our own test-infrastructure decay** (removed factory methods, a newly-mandatory
field a factory doesn't set, a changed helper signature, result-shape assumptions) plus **one
Python-3.14 test-runner artifact that isn't a real failure at all**. Genuine framework/business
drift is the minority.

## Errors by exception type

| Count | Exception |
|------:|-----------|
| 421 | MandatoryError |
| 335 | AttributeError |
| 321 | ValidationError |
| 179 | LinkValidationError |
| 176 | DuplicateEntryError |
| 155 | TypeError |
| 43 | FieldValidationError |
| 41 | OperationalError |
| 40 | KeyError |
| 37 | NotImplementedError |
| 31 | UniqueValidationError |
| 29 | DoesNotExistError |
| 28 | ServiceError |
| 24 | MollieValidationError |
| … | (long tail) |

## Root-cause buckets, ranked by leverage

Each bucket below is **one fix** that clears the listed count. The top 13 named causes
account for **~768 errors (≈39%)**.

### Tier 1 — single mechanical fix, large payoff (test infrastructure)

| Errors | Root cause | Fix |
|------:|------------|-----|
| **136** | `Membership Type … : role_profile` is **`reqd: 1`** (verenigingen schema, not v16) but the test factory `create_test_membership_type()` never sets it. | Have the factory create/attach a Role Profile (or make the field non-mandatory if it was unintentional). One edit in `tests/fixtures/enhanced_test_factory.py` + `test_data_factory.py`. |
| **128** | Tests call **factory methods that no longer exist** after the factory consolidation: `TestDataFactory.create_test_volunteer`, `SEPATestDataFactory.create_test_member`, `CoreTestDataFactory.create_test_sales_invoice`, `EnhancedTestDataFactory.create_test_chapter` / `create_test_member` / `_get_enhanced_member_defaults`, `track_doc`/`track_document`, `create_test_donor_with_sync`, etc. | Re-add the missing methods as thin shims on the consolidated factory, or update callers. Several are per-class helpers (`TestOverduePaymentsReportReal.test_id`, `TestDonorCustomerSyncUtils.create_test_donor_with_sync`). |
| **86** | `status` MandatoryError on **Membership Termination Request** (36), **Chapter** (14), **Chapter Join Request** (13), etc. Memory says Chapter status auto-set was fixed in PR #71 — appears regressed on v16 *or* these are raw-dict inserts. | Verify controller `autoname`/`before_insert` still sets `status` on v16; have factory pass `status` for the doctypes whose controller doesn't. |
| **62** | Result-shape drift: code/tests do `result.success` / `result.message` where `result` is now a **`dict`** (34) or **`bool`** (28). | Reconcile callers with the current return idiom (dict access vs attribute). Likely one or two service return-type changes. |
| **47** | `Item … : stock_uom` mandatory — a test helper creates an Item without `stock_uom`. | Set `stock_uom="Nos"` (or unit) in the Item-creating helper. |
| **37** | `EnhancedTestCase.create_test_membership()` signature changed to require positional `member_name, membership_type_name`, but ~30 callers pass `member=…, status=…, start_date=…`. Same for `create_test_member()` (7). | Accept the legacy kwargs (`member`/aliases) on the helper, or update callers. |

**Tier 1 subtotal: ~496 errors** — all in `tests/fixtures/` + a handful of per-file helpers. Low risk, high payoff.

### Tier 2 — Python-3.14 artifact (NOT real failures)

| Errors | Root cause | Action |
|------:|------------|--------|
| **48** | `'_io.TextIOWrapper' object has no attribute 'writeln'`. Python 3.14's `unittest.runner.TextTestResult._write_status()` calls `stream.writeln()` when reporting a **subTest** result; 3.14 dropped `writeln` from plain streams and Frappe's `TestResult` doesn't provide it. The *real* result is the `AssertionError` inside the `subTest()` — the writeln error just masks it and double-counts. | Framework-level (`frappe.testing.result`). Don't fix in-app. Either (a) report upstream / patch the bench's frappe, or (b) stop using `self.subTest()` in the affected tests. These inflate the error count but represent ~13 underlying assertion failures, not 48. |

### Tier 3 — missing test data / fixtures (LinkValidationError)

| Errors | Root cause | Fix |
|------:|------------|-----|
| **59** | `Could not find Membership Type: Monthly Standard / Regular / Daglid` — tests reference membership types that aren't created in setUp (no shared fixture). | Create the referenced types in setUp, or add a fixture. |
| **33** | `Could not find Row #: Team Role: Team Member / Team Leader` — **Team Role** master records absent on fresh sites. | Add Team Role fixtures (or create in setUp). |
| ~14 | `Could not find Region / Parent Chapter: Test …` | Same pattern — create prerequisites in setUp. |

### Tier 4 — deprecated-API tests (NotImplementedError, 37)

Tests still exercise functions that now **raise `NotImplementedError` on purpose**:
`submit_membership_application` (22), `parse_volunteer_data_from_notes` (6),
`add_skills_to_volunteer`, `create_volunteer_application_data`, `get_proficiency_label` (3 each).
Modules: `test_membership_application_skills{,_enhanced,_secure}`. **Action: delete or rewrite**
against the current API (these are testing intentionally-removed code paths).

### Tier 5 — genuine business-logic / environment drift (the "real" bucket)

| Errors | Root cause | Notes |
|------:|------------|-------|
| **52** | ERPNext company/account setup: `Please select a Company`, `Company Account is mandatory`, `root account … must be a group`. | Test-site company/CoA bootstrap incomplete on the fresh CI-mirror sites. Fix in site setup, not per-test. |
| **46** | `Member … does not have an active membership` | Tests acting on members before a membership is activated — setUp ordering. |
| **21** | `Contribution Mode cannot be "Calculator"` — this is the **B5 branch topic**. Commits ddd93ea0/d0cb9002 mapped Calculator→Income-Based, but **21 callers still create with "Calculator".** | Finish the B5 migration (this branch). |
| **19** | `IBAN is required for SEPA Direct Debit` | SEPA tests not providing IBAN in setUp. |
| **13** | `Mollie Backend API is not enabled` | Mollie Settings not enabled on test sites — Mollie tests need a settings fixture or skip guard. |

### Long tail (~600 errors)

DuplicateEntryError (176 — mostly setUp/teardown isolation within a module, far below the
1,538 of the old polluted run), OperationalError (41 — DB/lock), KeyError (40),
FieldValidationError (43), Mollie/ServiceError cluster (~60), plus singletons. Lower leverage;
revisit after Tiers 1–4 since many will disappear once factories/fixtures are repaired.

## Recommended order of attack

1. **Tier 1 factory fixes** (~496 errors) — `role_profile`, missing factory methods,
   `create_test_membership`/`create_test_member` signatures, `stock_uom`, result-shape.
   Highest payoff, lowest risk, all in `tests/fixtures/`.
2. **Tier 3 fixtures** (~106) — Membership Type / Team Role / Region masters in setUp.
3. **Tier 5 environment** (company/CoA bootstrap ~52, Mollie settings ~13) — fix in test-site setup.
4. **Tier 4 deprecated tests** (37) — delete/rewrite.
5. **B5 Contribution Mode** (21) — finish on this branch.
6. **Tier 2 writeln** — upstream/framework; document, don't chase the count.
7. Re-run baseline, then triage the residual long tail (much of it should evaporate).

A realistic projection: Tiers 1+3+4+5 are ~700 directly-named errors, and clearing the
factory/fixture root causes typically cascades into the long tail (DuplicateEntry, KeyError,
DoesNotExist that were downstream of a broken setUp). Expect the error count to drop well
below 1,000 after Tier 1 alone.
