# Test Inventory — Domain DT2: Co-located DocType Controller Tests (Part 2)

**Audit complete (24/24 files).** READ-ONLY classification of every class-level `def test_*` method across the co-located Member / Membership / Membership Type DocType controller tests (member/mixins … member_utils_coverage).

Classification key: HAPPY (nominal success) · UNHAPPY (expects error/throw/denial/mandatory-missing) · EDGE (boundary/empty/null/duplicate/idempotency/malformed/ordering/state-transition/naming) · OTHER (smoke/import-safety/setup-only/tautological/mock-into-tautology/skip-dominated).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| member_contact_request/test_member_contact_request_coverage.py | 15 | 7 | 4 | 4 | 0 |
| member/mixins/test_chapter_mixin.py | 8 | 3 | 0 | 5 | 0 |
| member/mixins/test_financial_mixin.py | 10 | 3 | 3 | 2 | 2 |
| member/mixins/test_payment_mixin_coverage.py | 4 | 2 | 0 | 1 | 1 |
| member/mixins/test_payment_mixin.py | 11 | 5 | 3 | 3 | 0 |
| member/mixins/test_termination_mixin_coverage.py | 10 | 5 | 1 | 2 | 2 |
| membership_dues_schedule/test_membership_dues_schedule_coverage.py | 26 | 12 | 6 | 6 | 2 |
| membership_dues_schedule/test_membership_dues_schedule_hooks_coverage.py | 5 | 1 | 0 | 4 | 0 |
| membership_dues_schedule/test_membership_dues_schedule_hooks.py | 6 | 0 | 0 | 6 | 0 |
| membership_dues_schedule/test_membership_dues_schedule.py | 24 | 12 | 0 | 8 | 4 |
| membership_termination_request/test_membership_termination_request_coverage.py | 18 | 9 | 7 | 2 | 0 |
| membership_termination_request/test_membership_termination_request_critical.py | 8 | 0 | 0 | 0 | 8 |
| membership_termination_request/test_membership_termination_request.py | 16 | 2 | 1 | 5 | 8 |
| membership/test_dues_schedule_manager_coverage.py | 4 | 4 | 0 | 0 | 0 |
| membership/test_dues_schedule_manager.py | 15 | 2 | 2 | 10 | 1 |
| membership/test_membership_coverage.py | 42 | 21 | 7 | 14 | 0 |
| membership/test_membership.py | 8 | 4 | 1 | 2 | 1 |
| membership/test_scheduler_coverage.py | 13 | 4 | 0 | 8 | 1 |
| membership_type/test_membership_type.py | 4 | 1 | 2 | 0 | 1 |
| member/test_member_coverage.py | 16 | 7 | 2 | 2 | 5 |
| member/test_member_id_manager_coverage.py | 8 | 1 | 3 | 3 | 1 |
| member/test_member_id_manager.py | 24 | 10 | 5 | 9 | 0 |
| member/test_member.py | 19 | 12 | 1 | 4 | 2 |
| member/test_member_utils_coverage.py | 23 | 6 | 1 | 11 | 5 |
| **DOMAIN TOTALS** | **337** | **133** | **49** | **111** | **44** |

## Observations

- **Type mix is HAPPY/EDGE-dominant, UNHAPPY thin.** Across 24 files / 337 methods: HAPPY 133 (39%), EDGE 111 (33%), UNHAPPY 49 (15%), OTHER 44 (13%). As elsewhere in the app, genuine asserted-failure coverage is even lower than the 15% headline — much rejection is folded into EDGE because the SEPA/donation/postal helpers (`member_utils.py`) return `success`/error **dicts** rather than raising (absence-of-data → EDGE), so `test_member_utils_coverage.py` lands 11/23 EDGE with only one true `assertRaises`.
- **Dead / tautological pockets to flag.** `membership_termination_request/test_membership_termination_request_critical.py` is **8/8 OTHER** — an entire "critical" file that pins nothing that fails on regression — and `membership_termination_request/test_membership_termination_request.py` is 8/16 OTHER; together the termination_request cluster carries most of the domain's dead weight. Smaller offenders: `membership/test_membership.py::test_payment_sync` (db_set-then-read-back roundtrip, tautological → OTHER); `membership_type/test_membership_type.py::test_default_membership_type` (documents *unimplemented* exclusive-default behavior, asserts the flags it just set → OTHER); and the `isinstance(...)`/`assertIn(key,...)` shape assertions that make up most OTHERs in `test_member_coverage.py` (5/16) and `test_member_utils_coverage.py` (5/23).
- **Mock discipline is good; OTHER ≠ mock-tautology here.** Nearly every coverage file's docstring states "No business logic is mocked," and the audit found no patch-the-function-under-test tautologies. The OTHER bucket in this domain is **shape/existence assertions and smoke**, not mock-into-tautology — a healthier failure mode, but the `assertIsInstance(x, bool)` / `assertIsNotNone` guards still can't fail meaningfully.
- **Strongest files.** `member/test_member_id_manager.py` (24 methods, **0 OTHER**) is the exemplar: real atomic-counter behavior (monotonic, persist-to-Singles, self-heal on drift), System-Manager guard rejections, and three genuine `frappe.cache()`-returns-**bytes** regression tripwires tied to the known env gotcha. `membership/test_scheduler_coverage.py` (13, real-DB expiry/renewal/orphan integration) and `membership/test_membership_coverage.py` (42) are also solid. `member/test_member_utils_coverage.py`, despite the OTHER tail, has disciplined empty/first-time/mismatch EDGE coverage of the SEPA-mandate decision paths.
- **PaymentMixin (known god-mixin) stays thin.** The `member/mixins/` tests in this domain cover the god-mixin with only `test_payment_mixin.py` (11) + `test_payment_mixin_coverage.py` (4) = 15 methods, light relative to PaymentMixin's ~602 LOC; `test_financial_mixin.py` reflects its no-op placeholders (2 OTHER of 10). The mixin surface is the domain's most under-tested area by size.
- **Base class is consistent.** Factory-based throughout: `EnhancedTestCase` (`tests/fixtures/enhanced_test_factory`) for the membership/ and member_id_manager files; `VereningingenTestCase` (`tests/utils/base`) for `test_member_coverage.py` and `test_member_utils_coverage.py`. No hand-rolled fixtures or non-factory anti-patterns; `track_doc()` is used for the SEPA-mandate side effects.

## Zero-method / missing files

- None. All 24 files in the table contain at least one class-level `def test_*` method and were audited.
- Effectively non-executing content (counted but flagged above): `test_membership_termination_request_critical.py` (8/8 OTHER) is present and runs but pins no regression-catching assertion; `member/test_member.py::test_chapter_matching` is a bare `pass` TODO stub (counted OTHER). Module-level `def test_*` outside test classes were excluded, and naive `grep -c 'def test_'` overcounts several files with nested helper defs — class-level methods only are tallied here.
