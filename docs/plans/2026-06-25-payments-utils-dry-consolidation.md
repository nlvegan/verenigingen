# Payments Utils DRY Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicated logic across `verenigingen/verenigingen_payments/utils/` by extracting a small set of tested shared helpers and rewiring every duplicate call site to use them, with zero behavior change and zero whitelisted-signature change.

**Architecture:** Two waves. **Wave 0** builds new, independently-tested helper modules (pure functions where possible — no DB, fast unit tests). **Wave 1** rewires existing files to delegate to those helpers; the rewiring tasks are partitioned into **7 disjoint file clusters** so they can run fully in parallel without edit collisions. **Wave 2** is review + full-suite verification.

**Tech Stack:** Python 3.14, Frappe v16, pytest via `bench run-tests`, `EnhancedTestCase`, ruff/black (line-length 110).

## Global Constraints

- **Behavior parity, not behavior change.** Every rewiring must preserve current outputs. This is refactor-only. No bug "fixes" mixed in — if you find a bug, note it in the task summary, do NOT fix it here.
- **Never change a `@frappe.whitelist()` function's name, parameter names, or return shape.** Internals may change; the public contract may not. Whitelisted endpoints are inventoried per task.
- **Do NOT merge `payment_retry.py`'s retry logic with the exponential-backoff helpers.** `payment_retry` schedules *business* retries at day intervals `[3, 7, 14]`; that is a different concept from in-process exponential backoff. They are unrelated despite the shared word "retry."
- **Test quality enforcer rules (pre-commit):** no business-logic mocks; permission bypass only in helpers named `_make_*`/`_ensure_*`/`_persist_*`/`_insert_*`/`create_*`/`cleanup`/`setUp`; use `self.as_user()` not `set_user("Administrator")`. Pure-function helper tests need no DB.
- **black excludes `verenigingen/tests/`** — do not rely on standalone `black --check` agreeing with CI for files under that path.
- **Commit per task.** Conventional Commits. Footer: `Claude-Session: https://claude.ai/code/session_01LprG2Es4HL76bmrpCL2P4V`.
- **Run before committing:** the task's own tests, then `ruff check <changed files>` and `black <changed files>` (outside `verenigingen/tests/`).
- **Paths are relative to** `/home/frappeuser/frappe-bench/apps/verenigingen/`. Module root for imports: `verenigingen.verenigingen_payments.utils.*`.
- **Test run command template:** `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module <dotted.module.path>`

---

## File Structure

New shared helper modules (Wave 0):

| File | Responsibility |
|---|---|
| `verenigingen/verenigingen_payments/utils/shared/__init__.py` | Package marker for the new shared helpers. |
| `verenigingen/verenigingen_payments/utils/shared/backoff.py` | Pure backoff-delay calculation (exponential/linear/fixed/fibonacci + jitter). |
| `verenigingen/verenigingen_payments/utils/shared/error_classification.py` | One error→category taxonomy + classifier function. |
| `verenigingen/verenigingen_payments/utils/shared/sliding_window.py` | `SlidingWindowCounter` deque-based time-window counter. |
| `verenigingen/verenigingen_payments/utils/shared/recipient_resolver.py` | Role-based notification recipient resolution (`Has Role` queries). |
| `verenigingen/verenigingen_payments/utils/shared/db_helpers.py` | `ensure_table_exists`, `update_row_status`, `insert_audit_row`. |
| `verenigingen/verenigingen_payments/utils/shared/responses.py` | `ResponseBuilder.error/success` + `compute_hmac_signature`. |
| `verenigingen/verenigingen_payments/utils/shared/money.py` | `safe_decimal`, `quantize_amount`. |
| `verenigingen/verenigingen_payments/utils/shared/xml_helpers.py` | `extract_xml_namespace`, `get_element_text`, `build_postal_address`. |

Existing file edited additively in Wave 0:

| File | Edit |
|---|---|
| `verenigingen/utils/validation/iban_validator.py` | ADD `validate_bic(bic)` + `BIC_REGEX` constant (additive only). |

Test files (new): mirror each helper under `verenigingen/verenigingen_payments/tests/utils_shared/test_<name>.py`.

---

## WAVE 0 — Build tested shared helpers (all tasks parallel; no shared files)

### Task 0a: Backoff calculator

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/__init__.py` (empty)
- Create: `verenigingen/verenigingen_payments/utils/shared/backoff.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_backoff.py`

**Interfaces:**
- Produces:
  ```python
  def calculate_backoff_delay(
      attempt: int,                 # 1-based attempt number
      *,
      base_delay: float = 1.0,
      max_delay: float = 60.0,
      strategy: str = "exponential",  # "exponential" | "linear" | "fixed" | "fibonacci"
      exponential_base: float = 2.0,
      jitter_factor: float = 0.0,   # 0 disables jitter; else adds [0, delay*jitter_factor)
      rng: "callable | None" = None,  # injectable random() for deterministic tests
  ) -> float
  ```
  Semantics that MUST match the existing code being replaced:
  - exponential: `base_delay * (exponential_base ** (attempt - 1))`
  - linear: `base_delay * attempt`
  - fixed: `base_delay`
  - fibonacci: `base_delay * fib(attempt)` with `fib(1)=1, fib(2)=1`
  - cap at `max_delay` BEFORE jitter
  - jitter added as `delay * jitter_factor * rng()` (default `rng=random.random`)
  - return `max(0.0, delay)`

- [ ] **Step 1: Write failing tests** in `test_backoff.py` (plain `unittest.TestCase`, no DB):
  - `test_exponential_no_jitter`: attempt 1→1.0, attempt 2→2.0, attempt 3→4.0 (base=1, base=2.0).
  - `test_caps_at_max_delay`: attempt 10 with base=1,max=60 → 60.0.
  - `test_linear`, `test_fixed`, `test_fibonacci` (attempts 1..5 → 1,1,2,3,5 × base).
  - `test_jitter_uses_injected_rng`: `rng=lambda: 0.5`, jitter_factor=0.1, exponential attempt 1 → `1.0 + 1.0*0.1*0.5 = 1.05`.
- [ ] **Step 2: Run, verify fail** (`ModuleNotFoundError`/`AttributeError`).
- [ ] **Step 3: Implement** `backoff.py` per the semantics above (`import random`; `rng = rng or random.random`).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add shared backoff-delay calculator`.

---

### Task 0b: Error classifier

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/error_classification.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_error_classification.py`

**Interfaces:**
- Produces:
  ```python
  class FailureCategory(str, Enum):
      TRANSIENT = "transient"
      RESOURCE = "resource"
      VALIDATION = "validation"
      AUTHORIZATION = "authorization"
      BUSINESS = "business"
      DATA = "data"
      SYSTEM = "system"

  def classify_error(error: Exception) -> FailureCategory: ...
  ```
  Build the keyword map as the UNION of the two existing taxonomies (see `sepa_error_handler.categorize_error` and `sepa_retry_manager._classify_failure`):
  - TRANSIENT: connection, timeout, temporary, server, network, busy, unavailable, overload, deadlock, lock wait
  - RESOURCE: resource, limit exceeded
  - VALIDATION: validation, invalid, missing, format, required, constraint, duplicate; also `isinstance(error,(ValueError,TypeError))`
  - AUTHORIZATION: permission, unauthorized, access, forbidden, authentication; also `frappe.PermissionError`
  - DATA: not found, does not exist, empty, null
  - default: SYSTEM
  - Note: there is no canonical `SEPAError` import here; the BUSINESS mapping (currently `isinstance(error, SEPAError)`) is handled by the CALLER, not this generic helper (see Task R1).

- [ ] **Step 1: Write failing tests:** assert `classify_error(Exception("connection reset"))==TRANSIENT`, `Exception("invalid IBAN")==VALIDATION`, `ValueError("x")==VALIDATION`, `Exception("permission denied")==AUTHORIZATION`, `Exception("record not found")==DATA`, `Exception("weird")==SYSTEM`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.** Lowercase `str(error)`; check categories in the order above (TRANSIENT, RESOURCE, VALIDATION, AUTHORIZATION, DATA → else SYSTEM); apply isinstance checks.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add shared error classifier`.

> Note for R1: the legacy string categories (`"temporary"/"authorization"/"data"/"unknown"`) used by `sepa_error_handler` must remain stable for its callers. R1 maps `FailureCategory` → those legacy strings inside `sepa_error_handler` rather than changing this enum.

---

### Task 0c: Canonical BIC validator (additive to iban_validator)

**Files:**
- Modify: `verenigingen/utils/validation/iban_validator.py` (additive — append new function + constant; do not touch existing functions)
- Test: `verenigingen/tests/sepa/test_iban_validator.py` (append cases; this file already exists)

**Interfaces:**
- Produces:
  ```python
  BIC_REGEX = r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"

  @frappe.whitelist()
  def validate_bic(bic: str) -> dict:
      """Return {"valid": bool, "message": str, "cleaned_bic": str}."""
  ```
  Semantics: strip + upper; empty → `{"valid": False, ...}`; match `BIC_REGEX` (8 or 11 chars). This must accept exactly what the two existing regex checks accept (same regex string).

- [ ] **Step 1: Write failing tests:** `validate_bic("ABNANL2A")["valid"] is True`, `validate_bic("ABNANL2AXXX")["valid"] is True`, `validate_bic("abnanl2a")["valid"] is True` (lowercased), `validate_bic("SHORT")["valid"] is False`, `validate_bic("")["valid"] is False`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the additive function + constant.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(validation): add canonical validate_bic to iban_validator`.

---

### Task 0d: SlidingWindowCounter

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/sliding_window.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_sliding_window.py`

**Interfaces:**
- Produces:
  ```python
  class SlidingWindowCounter:
      def __init__(self, window_seconds: float): ...
      def add(self, timestamp: float) -> None: ...        # append + prune
      def count(self, now: float) -> int: ...             # prune older than now-window, return len
      def prune(self, now: float) -> None: ...
      def clear(self) -> None: ...
  ```
  Internally a `collections.deque` of timestamps; `count`/`prune` `popleft()` while `front <= now - window_seconds`. Time is passed in (never call `Date.now`-equivalents internally — keeps it testable and resume-safe).

- [ ] **Step 1: Write failing tests:** add timestamps 0,1,2 with window=2; `count(2)` → 3; `count(3)` → 2 (t=0 pruned, boundary `<= now-window` i.e. `<=1`); `count(5)` → 0; `clear()` then `count(5)`→0.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add SlidingWindowCounter helper`.

> Boundary semantics MUST match `webhook_rate_limiter` (prune entries strictly older than the window). Verify the existing `popleft` condition in `webhook_rate_limiter.py:113` and replicate it exactly; if it uses `<` rather than `<=`, match that and adjust the test.

---

### Task 0e: RecipientResolver

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/recipient_resolver.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_recipient_resolver.py` (DB test — uses `EnhancedTestCase`)

**Interfaces:**
- Produces:
  ```python
  def get_recipients_by_roles(role_names: list[str]) -> list[str]:
      """Return deduplicated, enabled User emails holding any of role_names."""
  ```
  Implementation: single query over `Has Role` joined to `tabUser` where `role in role_names AND tabUser.enabled = 1 AND email != ''`; return sorted unique emails. This replaces the per-role loops in `sepa_notification_manager._get_rule_recipients`, `sepa_rollback_manager._get_notification_recipients`, and the role lookup in `payment_retry.send_escalation_notification`.

- [ ] **Step 1: Write failing test** (`EnhancedTestCase`): create a User via `_make_*` helper, assign a known role (e.g. "System Manager") using a `_make_*`/`_ensure_*` helper, assert the user's email is in `get_recipients_by_roles(["System Manager"])`; assert a disabled user is excluded.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** with one parameterized SQL or `frappe.get_all("Has Role", ...)` + a `frappe.get_all("User", filters={"name": ["in", ...], "enabled": 1})`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add role-based RecipientResolver`.

---

### Task 0f: DB helpers (table creation / status update / audit insert)

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/db_helpers.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_db_helpers.py` (DB test)

**Interfaces:**
- Produces:
  ```python
  def ensure_table_exists(create_sql: str, *, table_name: str) -> None:
      """Run CREATE TABLE IF NOT EXISTS; log+swallow on race; commit."""

  def update_row_status(table_name: str, pk_value: str, status: str,
                        *, pk_column: str = "name", error_message: str | None = None,
                        completed_at=None) -> None:
      """Parameterized UPDATE of status (+ optional error_message/completed_at); commit."""

  def insert_audit_row(table_name: str, row: dict) -> str:
      """Parameterized INSERT from a dict of column->value; return inserted name; commit."""
  ```
  These abstract the repeated raw-SQL blocks in `sepa_rollback_manager`, `sepa_notification_manager`, `sepa_race_condition_manager`. **Use parameterized SQL (`%s`/dict params) — never f-string interpolation of values.** Column names come from the caller (trusted, not user input) but validate `table_name`/columns against `^[A-Za-z0-9_]+$` to satisfy the SQL-field validators.

- [ ] **Step 1: Write failing tests:** create a temp table via `ensure_table_exists`, insert a row via `insert_audit_row`, update it via `update_row_status`, read it back and assert; assert calling `ensure_table_exists` twice does not raise. Drop the temp table in `tearDown`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** with `frappe.db.sql`, identifier-regex guard, parameterized values, `frappe.db.commit()`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add shared DB table/status/audit helpers`.

---

### Task 0g: ResponseBuilder + HMAC helper

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/responses.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_responses.py`

**Interfaces:**
- Produces:
  ```python
  class ResponseBuilder:
      @staticmethod
      def error(message: str, *, status: str = "error",
                error_code: str | None = None, details: dict | None = None) -> dict: ...
      @staticmethod
      def success(message: str = "", *, status: str = "success",
                  data: dict | None = None) -> dict: ...

  def compute_hmac_signature(secret: str, payload: str,
                             *, algorithm: str = "sha256") -> str:
      """hex HMAC of payload under secret using hashlib.<algorithm>."""
  ```
  Match the field set currently produced by `webhook_error_handler` and `payment_services/refund_utility` response dicts (inspect both; keep the same keys so callers' consumers don't break). `compute_hmac_signature` replicates `webhook_security.py:129` and `webhook/testing.py:243`.

- [ ] **Step 1: Write failing tests:** `ResponseBuilder.error("x")["status"]=="error"` and `["message"]=="x"`; `success(data={"a":1})["data"]=={"a":1}`; `compute_hmac_signature("k","p")` equals `hmac.new(b"k", b"p", hashlib.sha256).hexdigest()`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add ResponseBuilder and HMAC helper`.

---

### Task 0h: Money helpers

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/money.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_money.py`

**Interfaces:**
- Produces:
  ```python
  def safe_decimal(value, *, default="0") -> Decimal:
      """Coerce str/int/float/Decimal to Decimal; strip currency symbols/commas/spaces;
         return Decimal(default) on InvalidOperation/TypeError."""
  def quantize_amount(value, *, places=2, rounding=ROUND_HALF_UP) -> Decimal: ...
  ```
  Match the behavior of `bank_transaction_reconciliation._safe_decimal` (inspect it for exact symbol-stripping rules) so R3 can delegate without behavior change.

- [ ] **Step 1: Write failing tests:** `safe_decimal("€ 1.234,56")` — match whatever the existing `_safe_decimal` does (inspect first; replicate); `safe_decimal("abc")==Decimal("0")`; `quantize_amount("1.005")==Decimal("1.01")` (HALF_UP).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** copying the existing `_safe_decimal` logic verbatim into the shared function.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add shared decimal/money helpers`.

---

### Task 0i: XML helpers

**Files:**
- Create: `verenigingen/verenigingen_payments/utils/shared/xml_helpers.py`
- Test: `verenigingen/verenigingen_payments/tests/utils_shared/test_xml_helpers.py`

**Interfaces:**
- Produces:
  ```python
  def extract_xml_namespace(root, *, default: str) -> str:
      """Return the URI in root.tag '{uri}local' or `default`."""
  def get_element_text(element, path: str, ns: dict, *, default=None): ...
  def build_postal_address(parent, address: dict) -> None:
      """Append a SEPA PstlAdr block (Ctry, AdrLine x2, PstCd, TwnNm) if any field set."""
  ```
  `extract_xml_namespace` unifies `sepa_return_parser._detect_namespace` + `sepa_rulebook_validator._extract_namespace`. `build_postal_address` unifies the creditor/debtor blocks in `sepa_xml_enhanced_generator` (inspect both blocks; the element tags/order MUST match exactly).

- [ ] **Step 1: Write failing tests:** build an `ElementTree` element with tag `{urn:test}Doc`; `extract_xml_namespace(el, default="x")=="urn:test"`; tag without namespace → `"x"`; `get_element_text` returns child text and `default` when missing; `build_postal_address` produces the expected sub-elements for a sample dict (assert tag names + text).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** copying existing element tags/order verbatim.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** `feat(payments): add shared SEPA XML helpers`.

---

## WAVE 1 — Rewire callers (7 disjoint file clusters; all parallel after their Wave-0 deps land)

> **Each task below owns an exclusive set of files — no two Wave-1 tasks edit the same file, so they parallelize cleanly.** For every rewiring: keep the public/whitelisted signature, replace the duplicated body with a call to the Wave-0 helper, and add a behavior-parity test (or extend the existing test) proving old and new produce the same result. Run that file's existing tests too.

### Task R1: Retry/backoff/error-classification (LIVE) — depends on 0a, 0b, 0f
**Owns files:** `sepa_error_handler.py`, `sepa_retry_manager.py`, `sepa_race_condition_manager.py` (all under `verenigingen/verenigingen_payments/utils/`).
**Whitelisted to preserve:** `get_sepa_error_handler_status`, `reset_sepa_circuit_breaker`, `create_retry_batch_from_errors`, `execute_with_retry`, `get_retry_statistics`, `reset_retry_circuit_breaker`, `create_sepa_batch_with_race_protection`, `get_batch_lock_status`, `force_release_batch_lock`.
**Live callers (do not break):** `services/sepa_batch_processor.py:23,42`; `doctype/direct_debit_batch/sepa_processor.py:25,96`; `bank_transaction_reconciliation.py` imports `PaymentRetryManager` (untouched here).

- [ ] **Step 1:** In `sepa_error_handler.calculate_delay` write a parity test capturing current outputs for attempts 0..4 with the default `retry_config` and a fixed RNG (monkeypatch `random.random`), THEN replace the body with `calculate_backoff_delay(attempt+? , base_delay=..., max_delay=..., strategy="exponential", exponential_base=..., jitter_factor=0.1, rng=...)`. Reconcile the 0-based vs 1-based attempt: the existing code uses `multiplier ** attempt` (0-based) — pass `attempt+1` OR call with `exponential_base ** attempt`; the parity test is the gate. Keep the method signature `calculate_delay(self, attempt)`.
- [ ] **Step 2:** Replace `sepa_retry_manager._calculate_delay` body with `calculate_backoff_delay(...)` (it already supports strategy + failure-type modifiers — apply the `TRANSIENT*0.5 / RESOURCE*1.5` modifier in the caller AFTER the helper returns, or extend the call; parity test the four strategies).
- [ ] **Step 3:** Replace the inline backoff in `sepa_race_condition_manager.retry_failed_operation` (lines ~784-788) with `calculate_backoff_delay(attempt, base_delay=..., max_delay=..., strategy="exponential", exponential_base=..., jitter_factor=0)`.
- [ ] **Step 4:** Route `sepa_error_handler.categorize_error` through `classify_error`, then map `FailureCategory` → the legacy strings it currently returns (`temporary/validation/authorization/data/unknown`) so its callers/tests stay green. Route `sepa_retry_manager._classify_failure` through `classify_error`, mapping to its `FailureType` enum; keep the `isinstance(error, SEPAError)→BUSINESS` and `frappe.PermissionError→PERMANENT` special cases in this caller.
- [ ] **Step 5:** Replace `sepa_race_condition_manager._ensure_lock_table` raw SQL with `ensure_table_exists(create_sql, table_name="tabSEPA_Distributed_Lock")`.
- [ ] **Step 6:** Run existing tests: `tests/payment/test_sepa_error_handler.py`, `tests/payment/test_sepa_race_condition_manager.py`, `tests/sepa/test_sepa_week3_features.py`, plus new parity tests. All green.
- [ ] **Step 7:** Commit `refactor(payments): route SEPA retry/backoff/error-classification through shared helpers`.
- [ ] **Optional stretch (separate commit):** also route `core/resilience/retry_policy.py`'s four `_calculate_delay` methods through `calculate_backoff_delay`. Only if `tests/.../test_mollie_retry_policy_coverage_b3.py` stays green.

### Task R2: IBAN/BIC validation sites (LIVE) — depends on 0c, 0h, 0i
**Owns files:** `sepa_input_validation.py`, `sepa_xml_enhanced_generator.py`, `mollie/utils/validators.py`.
**Whitelisted to preserve:** `validate_sepa_batch_params`, `validate_single_sepa_invoice`, `get_sepa_validation_rules`.

- [ ] **Step 1:** Replace `SEPAInputValidator.validate_bic` regex body with a call to canonical `validate_bic` (from `verenigingen.utils.validation.iban_validator`), adapting the return to the existing `{"valid","errors","cleaned_bic"}` shape. Parity test both valid (8/11 char) and invalid inputs.
- [ ] **Step 2:** Replace `sepa_xml_enhanced_generator._validate_bic` body with canonical `validate_bic(...)["valid"]` (keep returning `bool`).
- [ ] **Step 3:** In `mollie/utils/validators.py`, change `IBANValidator.validate_iban` (and `_validate_checksum`) internals to delegate to canonical `validate_iban(iban)["valid"]` — **keep the class + method names + bool return** (callers at lines 177, 321, 446 + `payment_processors.py:519` depend on bool). Keep `IBAN_LENGTHS`/`format_iban`/`extract_bank_info` only if still referenced; otherwise delegate `format_iban` to canonical too.
- [ ] **Step 4:** In `sepa_xml_enhanced_generator`, replace the duplicated creditor/debtor address blocks with `build_postal_address(...)` (0i); replace any local decimal coercion with `safe_decimal`/`quantize_amount` (0h) where it matches.
- [ ] **Step 5:** Run `tests/test_sepa_xml_compliance.py`, `tests/sepa/test_iban_validator.py`, mollie validator tests, `test_service_layer_validation.py`. Green.
- [ ] **Step 6:** Commit `refactor(payments): route IBAN/BIC validation through canonical validator`.

### Task R3: Bank / MT940 / reconciliation (LIVE money paths) — depends on 0c, 0h
**Owns files:** `bank_integration.py`, `mt940_import.py`, `mt940_enhanced_fields.py`, `bank_transaction_reconciliation.py`, `batch_performance_optimizer.py`.

- [ ] **Step 1:** Extract the current `_safe_decimal` in `bank_transaction_reconciliation.py` into `shared/money.safe_decimal` was done in 0h by COPYING; now replace the local `_safe_decimal` with a thin delegator (or import) and update its call sites. Parity test a few representative inputs.
- [ ] **Step 2:** Replace raw IBAN regex in `mt940_import.py:672` and the two in `bank_integration.py` with canonical `validate_iban(...)["valid"]` for validation, and keep a single shared extraction regex constant for *extraction* (these are extraction, not validation — keep regex but define `IBAN_EXTRACT_RE` once at module top and reuse).
- [ ] **Step 3:** Delete the legacy `generate_mt940_transaction_hash` and repoint its single call site (`mt940_import.py:~1070`) to `get_enhanced_duplicate_hash`. Add a test asserting the same transaction yields a stable hash and a changed field yields a different hash.
- [ ] **Step 4:** Consolidate the duplicated invoice/reference matching: move the shared `SINV-/ACC-SINV-` pattern matching used by both `bank_integration._find_matching_invoice` and `bank_transaction_reconciliation.match_by_amount_and_reference` into ONE private helper in `bank_transaction_reconciliation.py` (the richer impl) and have `bank_integration` import/call it. Keep behavior identical (parity test on a sample reference string).
- [ ] **Step 5:** Replace `mt940_enhanced_fields.populate_enhanced_mt940_fields` re-parsing with consumption of the already-parsed `sepa_data` dict produced by `extract_sepa_data_enhanced` (the call site already passes it per audit — verify, then drop redundant parsing).
- [ ] **Step 6:** (Optional, low) Introduce module-level constants for confidence thresholds + payment-mode strings; replace magic literals. Only if it doesn't sprawl.
- [ ] **Step 7:** Run all bank/mt940 tests in `tests/` and `verenigingen_payments/tests/` touching these modules. Green.
- [ ] **Step 8:** Commit `refactor(payments): de-duplicate bank/MT940 decimal, IBAN, hashing and matching`.

### Task R4: SEPA parsers (mixed) — depends on 0i, 0h
**Owns files:** `sepa_return_parser.py`, `sepa_rulebook_validator.py`.

- [ ] **Step 1:** Replace `sepa_return_parser._detect_namespace` and `sepa_rulebook_validator._extract_namespace` with calls to `extract_xml_namespace` (0i), each passing its own `DEFAULT_NAMESPACE`. Parity test with a real pain.002 sample (reuse an existing fixture if present).
- [ ] **Step 2:** Replace the inline `element.find(...).text if ... else None` patterns in `sepa_rulebook_validator` with `get_element_text` (0i).
- [ ] **Step 3:** Replace the locally-redefined SEPA char pattern in `sepa_rulebook_validator.py:~707` with an import of `SEPA_CHAR_PATTERN` from `sepa_constants`.
- [ ] **Step 4:** Where `sepa_rulebook_validator.validate_transaction_amount` duplicates decimal coercion, delegate to `safe_decimal`/`quantize_amount` (0h) if it matches behavior.
- [ ] **Step 5:** Run the SEPA parser/rulebook tests. Green.
- [ ] **Step 6:** Commit `refactor(payments): share SEPA XML namespace/text/char-pattern helpers`.

### Task R5: Week 4 monitoring/notification cluster (DEAD-but-kept) — depends on 0d, 0e, 0f
**Owns files:** `sepa_notification_manager.py`, `sepa_alerting_system.py`, `sepa_rollback_manager.py`, `sepa_notifications.py`.
**This is the main "shrink Week 4" task.** These modules are dead in production (only Week-4 monitoring tests reference them) but keep their `@frappe.whitelist()` signatures intact for go-live.

- [ ] **Step 1:** Replace `sepa_notification_manager._get_rule_recipients` role loops and `sepa_rollback_manager._get_notification_recipients` with `get_recipients_by_roles([...])` (0e), preserving the rule's direct-email merge. Parity test against a seeded role.
- [ ] **Step 2:** Replace the three `_ensure_*_tables` blocks (`sepa_notification_manager`, `sepa_rollback_manager`) with `ensure_table_exists(...)` per table (0f). Replace `_update_delivery_status`/`_update_operation_status` with `update_row_status` (0f) and `_create_audit_entry`/`_log_notification` inserts with `insert_audit_row` (0f).
- [ ] **Step 3:** Standardize email dispatch: `sepa_alerting_system._send_email_notification` currently uses `frappe.core.doctype.communication.email.make()`; the other modules use `get_email_service().send_simple_email()`. Route alerting through `get_email_service()` too (confirm the EmailService API covers the alerting use). Parity: assert an email is queued (do not assert delivery).
- [ ] **Step 4:** Replace `sepa_alerting_system`'s deque metric-buffer (`check_metric`/`_evaluate_threshold` window pruning) with `SlidingWindowCounter` (0d) where it maps cleanly (the time-window pruning; keep value buffering if values are needed for threshold math — only the window bookkeeping moves).
- [ ] **Step 5:** Unify the severity enums: define one `Severity`/`PriorityLevel` (place in `shared/` or `sepa_constants`) and have `AlertSeverity`/`NotificationPriority`/`ConflictSeverity` reference it. (Note `ConflictSeverity` lives in `sepa_conflict_detector.py`, which is NOT in this task's file set — leave that one and just note it; do not edit cross-cluster files here.)
- [ ] **Step 6:** Run `tests/sepa/test_sepa_week4_monitoring.py`, `tests/sepa/test_sepa_week3_features.py`, `tests/payment/test_sepa_rollback_manager.py`, notification tests. Green.
- [ ] **Step 7:** Commit `refactor(payments): consolidate Week-4 monitoring recipients/DB/email/window helpers`.

### Task R6: Webhook cluster (LIVE) — depends on 0d, 0g
**Owns files:** `webhook_rate_limiter.py`, `webhook_security.py`, `webhook_error_handler.py`, `webhook/testing.py`, `webhook/logging.py`, `payment_services/refund_utility.py`.
**Whitelisted to preserve:** `get_webhook_rate_limit_stats`.
**Live callers:** `ing_checkout/api/webhook.py`, `ponto/api/webhook.py`, `mollie/utils/webhook_security.py`.

- [ ] **Step 1:** Replace the deque windows in `webhook_rate_limiter` (`_check_global_limit`/`_check_ip_limit`/`_check_webhook_id_limit`/`_cleanup_old_entries`) with `SlidingWindowCounter` (0d), one counter per key. **Preserve the progressive-penalty multiplier logic** (that's not part of the window helper). Parity test: same allow/deny decisions for a scripted sequence of timestamps.
- [ ] **Step 2:** Replace HMAC computation in `webhook_security.py:129` and `webhook/testing.py:243` with `compute_hmac_signature` (0g).
- [ ] **Step 3:** Replace the 5 response-dict builders in `webhook_error_handler.py` and the 2 in `payment_services/refund_utility.py` with `ResponseBuilder.error/success` (0g), preserving existing keys.
- [ ] **Step 4:** Hoist the duplicated duplicate-detection-response block in `webhook/testing.py` (Mollie/Ponto/ING `simulate_webhook_call`) into a base `WebhookTestHelper._handle_duplicate(...)` method called by each subclass.
- [ ] **Step 5:** Remove the redundant `_validate_mollie_payment_id` wrapper in `refund_utility.py`; call `is_valid_mollie_payment_id` directly (already done at line 323 — make it consistent).
- [ ] **Step 6:** Run webhook tests + any rate-limiter tests. Green.
- [ ] **Step 7:** Commit `refactor(payments): share webhook HMAC/response/window/dedup helpers`.

### Task R7: Payment notifications (LIVE) — depends on 0e
**Owns files:** `payment_retry.py`, `payment_alert_service.py`, `payment_notifications.py`.
**Whitelisted to preserve:** `schedule_retry`, `execute_payment_retry`, `check_payment_retry_status`.
**Live callers:** `hooks/scheduler.py`, `api/payment_dashboard.py`, `bank_transaction_reconciliation.py` (uses `PaymentRetryManager`).

- [ ] **Step 1:** Replace the `Has Role` lookup in `payment_retry.send_escalation_notification` (line ~214) with `get_recipients_by_roles(["Verenigingen Staff"])` (0e). **Do NOT touch the day-interval retry scheduling logic.** Parity test recipients only.
- [ ] **Step 2:** Confirm `payment_alert_service` and `payment_notifications` already use `get_email_service()`; if any role lookup duplicates the resolver, route it through 0e too. Otherwise leave dispatch as-is (already unified).
- [ ] **Step 3:** Run `tests/.../test_payment_retry.py` (both copies), payment alert/notification tests. Green.
- [ ] **Step 4:** Commit `refactor(payments): use shared recipient resolver in payment notifications`.

---

## WAVE 2 — Review & verify

### Task V1: Skeptical review
- [ ] Dispatch the `skeptical-code-reviewer` agent over the full diff (`git diff develop`). Focus: (a) any behavior change vs parity claims, (b) any whitelisted signature changed, (c) tests that are tautological / characterization-without-assertion, (d) helpers that diverge subtly from the code they replaced (esp. backoff attempt indexing, window prune boundary, BIC/IBAN edge cases). Fix findings; re-run affected tests.

### Task V2: Full suite + Error-Log audit
- [ ] Run the payments-related modules in full; then run the broader suite the gate uses. Confirm green. Optionally re-run the touched modules under `VERENIGINGEN_FAIL_ON_ERROR_LOG=1` to confirm no new masked errors.
- [ ] `pre-commit run --all-files` (or at least ruff/black/whitelist-type-safety/sql-field-validator on changed files).
- [ ] Push and confirm the Server Tests gate goes green (re-run failed shards once to clear known transient MySQL-deadlock/timestamp flakes; only investigate failures that reference touched files).

---

## Dispatch matrix (for the orchestrator)

| Wave | Tasks | Parallel? | Depends on |
|---|---|---|---|
| 0 | 0a,0b,0c,0d,0e,0f,0g,0h,0i | Yes (9 in parallel) | — |
| 1 | R1,R2,R3,R4,R5,R6,R7 | Yes (7 in parallel; file sets disjoint) | R1→0a,0b,0f · R2→0c,0h,0i · R3→0c,0h · R4→0i,0h · R5→0d,0e,0f · R6→0d,0g · R7→0e |
| 2 | V1 then V2 | Sequential | all of Wave 1 |

**Collision guarantee:** the seven Wave-1 file sets share no file, so they can run concurrently in the same working tree. Wave 0 only creates new files plus an additive edit to `iban_validator.py` (touched by no other Wave-0 task), so it is also collision-free.

## Expected impact
- LOC reduction concentrated in R5 (Week-4 cluster: recipients + DB boilerplate + window) and R1/R3 (backoff + decimal + dup-hash). Rough estimate ~1,000–1,500 LOC net, but the retry/error-classifier and IBAN/BIC items matter more for *correctness convergence* (single source of truth) than line count.
- **Out of scope (flag, don't do here):** deleting genuinely-redundant dead modules (e.g. whether both `sepa_notifications` and `sepa_notification_manager` need to exist) — that's a delete decision, not a DRY consolidation, and should be a separate reviewed change.

## Self-review notes
- Spec coverage: every cross-cutting + within-cluster finding from the audit maps to a Wave-0 helper + a Wave-1 rewiring task. The two "keep separate" items (mandate vs batch notification *domains*; `payment_retry` business-retry vs backoff) are explicitly fenced off.
- Type consistency: helper signatures defined in Wave 0 are referenced verbatim in Wave 1.
- Known risk: backoff attempt indexing (0-based in `sepa_error_handler`, 1-based elsewhere) — gated by per-call parity tests in R1.
