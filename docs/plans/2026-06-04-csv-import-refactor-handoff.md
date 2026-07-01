# BaseCSVImport Extraction & Hardening — Handoff

**Date:** 2026-06-04
**Branch:** `develop` (all four PRs merged; no open feature branches)
**Status:** Shipped. 83 tests across four affected suites, zero regressions.

Companion handoff to `docs/plans/2026-06-03-procurios-mandate-import-handoff.md` (which originally flagged the work this refactor closes). If you're picking up CSV importer work for the first time, read that doc first for the Procurios Mandate Import feature itself — this doc covers what changed in the importer scaffolding around it.

---

## 1. What this refactor shipped

Originally seeded by handoff §8 (TD-3: "BaseCSVImport extraction") and skeptical-reviewer follow-ups across four merged PRs:

| PR | Squash commit | Theme |
|---|---|---|
| [#122](https://github.com/nlvegan/verenigingen/pull/122) | `3319b2d9` | Extract shared scaffolding; thin out both Procurios importers |
| [#123](https://github.com/nlvegan/verenigingen/pull/123) | `3a78377c` | Close reviewer findings on #122 (unused import, cache-slot pin, dead flag set, docstring polish) |
| [#124](https://github.com/nlvegan/verenigingen/pull/124) | `dfbe2b60` | Close skeptical reviewer's deferred items on #123 + handoff §8 gaps (NULL error_log, guard-in-before_submit, relativedelta cutoff, sibling e2e) |
| [#125](https://github.com/nlvegan/verenigingen/pull/125) | `3b1d70a7` | DRY: shared CSV file-attachment fixture; harden `@patch.object` over inline try/finally |

Net effect on the codebase: the two Procurios concrete controllers shrank by ~180 LOC combined, share a 200-LOC base + 4 module-level helpers in `verenigingen/utils/csv/base_csv_import.py`, and have a 5x stronger test net than before.

---

## 2. Architecture today

```
verenigingen/utils/csv/
├── base_csv_import.py            ← shared scaffolding (introduced PR #122, hardened in #123-125)
├── procurios_mandate_validator.py  ← unchanged pure validator
├── procurios_data_validator.py     ← unchanged pure validator
└── secure_csv_parser.py            ← unchanged

verenigingen/verenigingen_payments/doctype/procurios_mandate_import/
└── procurios_mandate_import.py   ← inherits BaseCSVImport (PR #122)

verenigingen/verenigingen/doctype/procurios_csv_import/
└── procurios_csv_import.py       ← inherits BaseCSVImport (PR #122)

verenigingen/verenigingen/doctype/mijnrood_csv_import/
└── mijnrood_csv_import.py        ← deliberately does NOT inherit (header docstring explains why)

verenigingen/tests/fixtures/
└── procurios_csv_fixtures.py     ← shared e2e test fixtures (PR #125)
```

### `BaseCSVImport(Document)` provides

| Member | Purpose |
|---|---|
| `_parser` property | Cached `SecureCSVParser` instance. Cache slot is single-underscore `_parser_instance` (name-mangling-safe — see §3 below). |
| `validate()` | Sets `import_date = today()` if unset. |
| `_read_csv_file()` | Returns `self._parser.read_csv_file(self.csv_file)`. |
| `before_submit()` | Validates `_BACKGROUND_METHOD` class attribute. Throws BEFORE Frappe writes `docstatus=1` — a misconfigured subclass keeps the doc in Draft. |
| `on_submit()` | Sets `import_status = "Queued"` + `frappe.enqueue` with the subclass's `_BACKGROUND_METHOD`. |

### Module-level helpers

| Helper | Used by |
|---|---|
| `ADMIN_ROLES: list[str]` | The two helpers below for `frappe.only_for` |
| `format_truncated_error_log(error_log, max_lines=50)` | Both concrete `_validate_and_preview_csv` + `_finalize_import_results` |
| `run_csv_validation(doctype, import_doc_name)` | Body of every concrete `validate_import_file` whitelisted entry point |
| `prepare_background_import(doctype, import_doc_name, test_mode)` | Entry-prologue of every concrete `process_import_background` (gates `only_for` BEFORE flag side-effects; coerces test_mode; sets `in_background_job` + `ignore_version_changes`) |
| `mark_import_failed(doc, error_message)` | Every Failed-path in `_validate_and_preview_csv` and `process_import_background` (reloads, sanitises, writes Failed + commit; substitutes "Unknown error" fallback if sanitisation returns None/empty) |

### Subclass contract

A subclass MUST define:
- `_BACKGROUND_METHOD: str` — dotted path to its module-level `process_import_background` (Frappe's enqueue resolves jobs by dotted path).
- `_validator` property — subclass-specific validator type, cache slot `_validator_instance`.
- `_validate_and_preview_csv()` — different validators yield different return shapes; only the failure-path skeleton is shared via `mark_import_failed`.
- Per-row processor (`_process_single_row` / `_process_single_member`) and `_finalize_import_results` — domain logic.

---

## 3. Things that will break if you touch them

These invariants are load-bearing across the refactor; preserve them when modifying anything in this area.

### Cache slots use single underscore (`_parser_instance` / `_validator_instance`)

The two Procurios controllers historically used `self.__parser` / `self.__validator` with `hasattr(self, "__parser")` checks. Python name-mangling rewrites `__parser` to `_<ClassName>__parser`, but `hasattr` checks the unmangled name → cache never hit. Fixed in PR #122 by switching to single-underscore slot names. Two regression tests pin this:

- `TestPropertyCacheHits.test_mandate_import_{parser,validator}_is_cached` (in `tests/payment/test_procurios_mandate_import.py`)
- `TestProcuriosCSVImportPropertyCache.test_{parser,validator}_is_cached` (in `tests/member/test_procurios_csv_import.py`)

Both now do **`assertIn("_<x>_instance", doc.__dict__)`** in addition to `assertIs(...)` — pinning the actual cache slot name. PR #123 added this; without it, a future refactor to `functools.cached_property` would silently break the name-mangling fix while passing the identity check.

`mijnrood_csv_import.py` uses a DIFFERENT pattern: explicit mangled-name `hasattr(self, "_MijnroodCSVImport__validator")` + `self.__validator = ...`. Both are correct; they are NOT interchangeable. The mijnrood class docstring (PR #122) spells this out — do not "clean up" the underscores there.

### `frappe.only_for` MUST run BEFORE any `frappe.flags` mutation

The original PR #122 review (round 2) caught this as a security regression: an unauthorised caller could flip `frappe.flags.in_background_job` for their own session before the `only_for` exception fired. The helper `prepare_background_import` now enforces the ordering (only_for is the first statement); the regression test `TestPrepareBackgroundImport.test_non_admin_caller_is_rejected_before_flags_set` asserts the flag stays `False` after the rejection.

### `_BACKGROUND_METHOD` guard lives in `before_submit`, NOT `on_submit`

Frappe's submit lifecycle is `validate → before_submit → write docstatus=1 → on_submit`. Putting the guard in `before_submit` (PR #124) means a misconfigured subclass never gets the doc submitted — it stays in Draft. The integration test `TestBeforeSubmitGuardIntegration.test_guard_prevents_docstatus_write` monkey-patches `_BACKGROUND_METHOD = ""` on `ProcuriosMandateImport`, attempts `doc.submit()`, and asserts `doc.docstatus == 0` after reload (proving the guard fires BEFORE Frappe's docstatus write).

The integration test uses `@patch.object(...)` as a class decorator (PR #125) rather than inline try/finally — `unittest.mock`'s `__exit__` semantics survive `KeyboardInterrupt` between assignment and cleanup, which the try/finally form would not.

### `bulk_member_operations` lifecycle is owned by the context manager

The sibling `process_import_background` (`procurios_csv_import.py`) is the only place that needs `frappe.flags.bulk_member_operations`. The flag is set/cleared by the `bulk_member_operations(import_doc_name)` context manager from `csv_import_processor.py` — NOT manually. PR #124 removed the pre-CM `frappe.flags.bulk_member_operations = True` AND the outer `finally`'s reset because they were redundant. Do not re-add either: the CM owns the flag.

### `mark_import_failed` never writes NULL to `error_log`

`sanitize_error_for_audit("")` returns `None`. PR #124 added a substitution (`sanitize_error_for_audit(error_message) or "Unknown error (no diagnostic available)"`) so a Failed import always has a visible diagnostic, never SQL NULL. The fallback string is admin-facing (not currently translated). Regression test: `TestMarkImportFailed.test_empty_string_writes_fallback_diagnostic_not_null`.

### `progress_field_map` on the processor

`CSVImportBackgroundProcessor.process_import` defaults to `members_*` progress fields. The mandate importer uses `mandates_*` and passes its own map — without that, the live progress fields silently stay at zero. Both refactored controllers preserve this verbatim. From the original handoff §9: "adding more field-name keys is harmless" — true.

---

## 4. Test inventory

| Test module | Count | Time | What it covers |
|---|---|---|---|
| `tests.utils.csv.test_base_csv_import` (NEW) | 17 | 1.2s | All 4 helpers + BaseCSVImport class invariants (security ordering, before_submit guard, on_submit enqueue kwargs, name-mangling cache-slot, NULL-error_log fallback) |
| `tests.payment.test_procurios_mandate_validator` | 14 | <0.01s | Pure validator logic (incl. relativedelta boundary + invalid-Opzegdatum, both added PR #124) |
| `tests.payment.test_procurios_mandate_import` | 24 | ~125s | Full mandate flow (validate, build_caches, per-row decisions, e2e, permissions, scale 500-row) |
| `tests.member.test_procurios_csv_import` | 28 | ~4s | Full sibling flow (validator unit + permission + cache + e2e [NEW in #124]) |

**Total: 83 tests.**

Two regression-guard test classes that explicitly protect the name-mangling fix:
- `TestPropertyCacheHits` (mandate, `tests/payment/test_procurios_mandate_import.py`)
- `TestProcuriosCSVImportPropertyCache` (sibling, `tests/member/test_procurios_csv_import.py`)

### How to run

```bash
cd ~/frappe-bench
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.utils.csv.test_base_csv_import
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_validator
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.payment.test_procurios_mandate_import
bench --site veg11.veganisme.org run-tests --app verenigingen \
  --module verenigingen.tests.member.test_procurios_csv_import
```

Last verified green: 2026-06-04 against `develop` at `3b1d70a7`.

---

## 5. Review history

The four PRs went through 8 reviewer rounds total (senior + skeptical, in parallel, per the project convention from memory `feedback_double_review_pattern`).

| PR | Reviewer findings landed | Verdict |
|---|---|---|
| #122 | Cross-importer style note (defer); `ADMIN_ROLES` orphan import (caught skeptical TD-3 follow-up) | Both: Ready to merge |
| #123 | `_BACKGROUND_METHOD` guard (senior); cache-slot pin + `bulk_member_operations` removal (skeptical) | Both: Merge as-is |
| #124 | Tautological assertion (senior); empty-`str(e)` fallback + guard-in-`before_submit` + integration test (skeptical) | Both: Merge as-is with fix |
| #125 | Temp-file leak + SIGKILL docstring (senior); enforcer-rationale docstring + controller-cache comment (skeptical) | Both: Merge as-is |

Key pattern learned: the skeptical reviewer consistently catches things the senior misses around state lifecycle (flag ordering, docstatus timing, fixture leakage). Worth keeping the parallel-review pattern for any future PR that touches submit lifecycle, background jobs, or test fixtures.

---

## 6. Intentionally deferred (open items for next session)

Listed for the next person who touches this code. None block production use.

### Documentation / accuracy
- **Translate the "Unknown error (no diagnostic available)" fallback** in `mark_import_failed`, OR add a docstring note explaining it stays English (the Frappe Desk UI is conventionally English in this app, so the current state is defensible). Skeptical reviewer #2 on PR #124.

### Test gaps
- **Leap-year edge test for the `relativedelta` cutoff math** (skeptical D on PR #124). With `today=2025-02-28`, a cancellation date of `2024-02-29` should be kept (`relativedelta(months=12)` gives `2024-02-28`; `2024-02-29 < 2024-02-28` is False). Trivia, but a one-row test would pin the leap-day semantics.
- **Standalone unit tests for the shared fixture itself** (skeptical follow-up on PR #125). `create_csv_file_attachment` and `create_raw_csv_attachment` are now load-bearing for two test modules. A 5-line round-trip test (write → read back → assert content equal) would catch fixture regressions in seconds instead of letting them surface as confusing mandate/sibling-test failures.
- **Integration test for `_BACKGROUND_METHOD = None`** (vs `""`) at the submit-lifecycle level. Unit coverage exists in `TestBeforeSubmitBackgroundMethodGuard.test_missing_attribute_throws`; the integration variant exists only for the empty-string case. Predates the refactor.
- **No standalone test that `BaseCSVImport.on_submit`'s enqueue actually runs against a real worker.** PR #124 added `TestOnSubmitEnqueueKwargs` which mocks `frappe.enqueue` and asserts the call shape. A test that confirms a real RQ worker picks up the enqueued job would catch any future regression in the dotted-path resolution. Heavyweight.

### Style / robustness
- **`Iterable[Mapping[str, str]]` → `Sequence[Mapping[str, str]]`** in `create_csv_file_attachment` (skeptical #3 on PR #125). Prevents a hypothetical future generator footgun. No current caller passes a generator; stylistic.
- **`mkstemp + os.close + open`** could be `os.fdopen(fd, ...)` (skeptical #5 on PR #125). Stylistic; no TOCTOU risk under standard Linux semantics.
- **The fixtures directory mixes `typing.List` (deprecated alias) with built-in generics.** Both Procurios fixture modules use the deprecated form to be consistent with neighbours. Could be modernised across the whole `tests/fixtures/` directory in a single sweep.

### From the original Procurios handoff §8 that this refactor sequence did NOT close
- `_Caches` as a state class with `record_create()` / `record_cancel()` methods (TD-2 in original handoff)
- `error_log` mixes skip reasons with errors — admin UX consistency
- Client poll has no max-attempts cap (matches sibling pattern; 30-min cap would be friendlier)
- Scale-test ceiling of 180s is generous
- Drive a real Procurios CSV through it in a non-production site

---

## 7. Quick reference: commit map

```
# PR #122 — refactor extraction
b8c8c7fb  feat(csv): add BaseCSVImport scaffolding + helpers
31bf2b65  refactor(csv): migrate procurios_mandate_import to BaseCSVImport
d1de0ffb  refactor(csv): migrate procurios_csv_import to BaseCSVImport
e2da5410  docs(csv): note why mijnrood_csv_import does NOT inherit BaseCSVImport
5577a145  test(csv): add positive-path regression guards for base helpers
3319b2d9  ← squash-merged into develop

# PR #123 — close PR #122 reviewer findings
a4160f3c  chore(csv): post-merge follow-ups on BaseCSVImport (mark_import_failed docstring + _BACKGROUND_METHOD guard in on_submit)
9a3e9f88  test(csv): pin cache-slot name on property-cache regression guards
8adffe97  refactor(csv): remove redundant bulk_member_operations flag writes
4ed6133e  ← amend with the senior+skeptical minor folds
3a78377c  ← squash-merged into develop

# PR #124 — close PR #123 deferred + handoff §8 gaps
82d5b76f  fix(csv): mark_import_failed never writes NULL error_log
ba029632  refactor(csv): move _BACKGROUND_METHOD guard to before_submit
307c5856  test(csv): integration test for _BACKGROUND_METHOD guard
968f7823  fix(csv): use dateutil.relativedelta for the 12-month cutoff
d9dc5a23  test(csv): pin invalid-Opzegdatum behaviour
814fbf01  test(csv): end-to-end integration for sibling member-importer
3295f7ad  ← amend: fix tautological assertion, add enqueue-kwargs tests, doc ignore_validate bypass
dfbe2b60  ← squash-merged into develop

# PR #125 — DRY fixture + harden monkey-patch
ad81673d  test(csv): extract shared CSV file-attachment fixture
2ceca130  test(csv): use @patch.object for the _BACKGROUND_METHOD monkey-patch
fc727d06  ← amend: fold in temp-file unlink, SIGKILL docstring, enforcer-rationale, controller-cache comment
3b1d70a7  ← squash-merged into develop
```

All four PRs are merged; no open branches in `chore/*` or `refactor/*` namespaces touching this area.

---

## 8. Context for the next person

- `develop` is the integration target. `gh pr merge --squash --delete-branch` is the project pattern (confirmed via 5 prior PRs in this sequence).
- Pre-commit on the CSV-importer files: `SKIP=whitelist-type-safety,jest-testing` is the canonical skip list (project memory `feedback_pre_existing_hook_failures`).
- The "Verenigingen CI / API Security Audit" workflow has been failing pre-existing on develop for 5+ consecutive commits at the 85.5% protection-rate baseline. Not a blocker for new PRs.
- 4-shard Server Tests have a v11 baseline of ~573 errors / 88.1% pass; the merge gate is "no regression beyond baseline" not "all green."
- The test infrastructure note from `tests/member/test_procurios_csv_import.py`'s e2e test: the Member→Customer sync commits independently of the EnhancedTestCase rollback, so any Member name that produces a derived Customer name MUST be suffix-bound for test idempotency.

---

## Contact / context

Active sessions: this refactor sequence ran 2026-06-03 → 2026-06-04. Same user (foppe@veganisme.org), same site (veg11.veganisme.org).
