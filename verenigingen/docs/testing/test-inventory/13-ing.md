# Domain P2 — ING Checkout Payment App (Pay.nl) Test Inventory

READ-ONLY classification of every `def test_*` method across the 14 files under
`verenigingen/verenigingen_payments/ing_checkout/tests/`. Each method is assigned
one primary type by dominant intent: HAPPY (nominal success), UNHAPPY (expects
error/throw/HTTP-error/auth-or-signature-failure/rejection returning an error
result), EDGE (boundary/empty/null/zero/duplicate/replay/idempotency/malformed/
alternate-shape/fallback/cache-TTL/truncation/sanitization), OTHER (factory/
setup/smoke/tautological completeness).

The underlying integration wraps Pay.nl's REST v2/v3 API (Order, Mandate/Direct
Debit GMS, webhooks). One file (`test_client_live.py`) hits the REAL Pay.nl
sandbox and is skip-gated on `paynl_test_*` site-config credentials.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_api.py | 10 | 5 | 4 | 1 | 0 |
| test_client_branches.py | 12 | 4 | 3 | 3 | 2 |
| test_client_live.py | 3 | 1 | 1 | 0 | 1 |
| test_client.py | 14 | 7 | 7 | 0 | 0 |
| test_mandate_api.py | 20 | 4 | 15 | 1 | 0 |
| test_mandate_payload_spec_unit.py | 11 | 9 | 1 | 1 | 0 |
| test_mandate_service_unit.py | 15 | 5 | 6 | 2 | 2 |
| test_models.py | 44 | 26 | 0 | 18 | 0 |
| test_transaction.py | 18 | 13 | 1 | 3 | 1 |
| test_transaction_service.py | 16 | 4 | 9 | 2 | 1 |
| test_webhook_endpoints.py | 23 | 3 | 8 | 12 | 0 |
| test_webhook_handlers_unit.py | 18 | 9 | 0 | 9 | 0 |
| test_webhook_security_branches.py | 9 | 3 | 1 | 5 | 0 |
| test_webhook_security.py | 25 | 10 | 8 | 7 | 0 |
| **DOMAIN TOTALS** | **238** | **103** | **64** | **64** | **7** |

## Per-method notes (non-obvious calls)

**test_api.py** — `test_create_payment_description_truncated` = EDGE (30-char
truncation boundary). `invalid_amount`(=0), `missing_reference`, `missing_id`,
`connection_failure` = UNHAPPY (error result). `get_status_cancelled` = HAPPY
(API call succeeds, returns cancelled state).

**test_client_branches.py** — `non_json_body`, `empty_body`,
`list_mandates_no_filters` = EDGE. `generic_request_exception`, `400_with_error`,
`connection_generic_failure` = UNHAPPY. `log_request_runs_in_developer_mode` =
OTHER (exercises dev-mode logging path; asserts logger called). `get_client_
returns_client` = OTHER (factory).

**test_client_live.py** — LIVE/skip-gated against real Pay.nl sandbox.
`test_connection_succeeds` = HAPPY; `invalid_credentials_rejected` = UNHAPPY
(real auth failure); `get_client_uses_configured...credentials` = OTHER (config
verification).

**test_client.py** — auth-header/session-header = HAPPY (nominal setup). 401/403/
500/timeout/connection/validation(422)/auth_failure = UNHAPPY (7). No edge/other.

**test_mandate_api.py** — dominated by validation-guard UNHAPPY (15: missing arg,
member/mandate/invoice not found across all endpoints). `delegates_with_none_
amount` = EDGE (null amount). Only 4 HAPPY (delegation forwarding + field reads).

**test_mandate_payload_spec_unit.py** — spec-compliance payload-builder asserts
(HTTP mocked). Assert real transformed values (UPPERCASE type, cents, customer.
bankAccount) — NOT tautological. `omits_bic_when_absent` = EDGE; `missing_amount_
returns_error` = UNHAPPY.

**test_mandate_service_unit.py** — heavy MagicMock. `zero_outstanding` = EDGE
(zero), `no_mandates` = EDGE (empty). `no_sepa`/`inactive`/`api_error` (x2) =
UNHAPPY. Two factory OTHER. Note: mocks `frappe.get_doc` + client so assertions
ride on the mock's canned dict — real controller not exercised (unit isolation).

**test_models.py** — pure dataclass tests, no mocking, real objects. 18 EDGE =
fallback/alternate-shape/absent/unknown-default/bad-date parsing branches; 26
HAPPY = primary parse + predicate + serialization. Zero unhappy (no throwing
paths in models).

**test_transaction.py** — STATUS_MAP mapping asserts = HAPPY (8); `status_map_
coverage` = OTHER (tautological completeness loop). `get_existing_transaction` =
EDGE (idempotent dedupe), `zero_amount_allowed` = EDGE, `unknown_status_defaults`
= EDGE. `negative_amount_throws` = UNHAPPY.

**test_transaction_service.py** — real ERPNext Payment Entry against `_Test
Company` (happy path submits real PE). 9 UNHAPPY guards. `invalid_amount_zero` +
`overpayment_detected` = EDGE. `invoice_already_paid` = UNHAPPY (business
rejection). Alert-delegation = HAPPY. Factory = OTHER.

**test_webhook_endpoints.py** — EDGE-dominant (12): savepoint-name sanitization
(x3), empty-body(x3), invalid-json(x2), duplicate short-circuit(x3),
missing-object(1). UNHAPPY (8): rate-limited-429(x3), signature-failure-401(x2),
processing-exception-500(x3). HAPPY = 3 success paths. Drives webhook via
`frappe.local.request` injection; inner `_process_*` stubbed.

**test_webhook_handlers_unit.py** — `_parse_reference` not-found/unknown/empty/
None/unmatched = EDGE (graceful None-return, not error). Mandate/txn
`not_found` = EDGE (logged, handled=True). 9 HAPPY = successful parse/process.
Zero unhappy (handlers never raise; degrade gracefully).

**test_webhook_security_branches.py** — IP fallbacks (X-Real-IP, remote_addr) +
cache-fresh/stale-TTL + alt-`data`-shape = EDGE (5). `missing_signature_with_
secret` = UNHAPPY (raises INGCheckoutWebhookError). XFF-first + XFF-precedence +
primary-shape = HAPPY.

**test_webhook_security.py** — signature verification core. UNHAPPY (8):
invalid/missing-secret/missing-sig signature fails, invalid-IP fail-closed raise,
signature-invalid raise, log error-handling, network error. EDGE (7): empty/None
IP boundaries, fail-closed empty list, duplicate detection/idempotency, long-
event-id truncation, log-prevents-duplicate, no-request-context. HAPPY (10):
valid sig/IP, fail-closed pass-when-valid, hash consistency/distinctness.
`test_passes_when_signature_valid` computes a REAL HMAC (not mocked verifier) —
good, tests genuine crypto path.

## Observations

- **Webhook security is the best-covered surface.** `test_webhook_security.py` +
  `_branches.py` + `test_webhook_endpoints.py` = 57 methods spanning HMAC
  signature verify (valid/invalid/missing-secret/missing-sig/case-insensitive),
  fail-closed IP validation, idempotency/duplicate detection, rate-limiting-429,
  and savepoint-name sanitization. Signature-fail correctly UNHAPPY, replay/
  duplicate correctly EDGE. Real HMAC is computed in the pass-when-valid test
  rather than mocking the verifier — the crypto path runs end-to-end.

- **Mandate & transaction coverage is guard-heavy but real where it counts.**
  `test_mandate_api.py` is 15/20 UNHAPPY validation guards (thin — asserts
  error strings). The genuine business logic lives in `test_transaction_service.py`
  (real submitted Sales Invoice → real Payment Entry, overpayment cap, already-
  paid rejection) and `test_mandate_payload_spec_unit.py` (Pay.nl v2 contract:
  UPPERCASE type, customer.bankAccount, integer cents, `code` response field) —
  these assert transformed values, not tautologies.

- **Live coverage is real but minimal and skip-gated.** `test_client_live.py`
  (3 methods) hits Pay.nl's real sandbox; the file header documents the sandbox
  only grants read-only Service:GetConfig (mandate/order create/list return 403),
  so the live lifecycle can't be exercised — those paths stay on the mocked unit
  suites. Every method skips without `paynl_test_*` credentials, so CI stays
  green. It includes a genuine negative test (bogus token → real auth rejection),
  which proves the happy live test isn't a stub.

- **Mock-into-tautology risk is contained to `test_mandate_service_unit.py`.**
  It mocks `frappe.get_doc` + the Pay.nl client, so assertions ride on canned
  dicts and the real ING Checkout Mandate/Transaction controllers aren't
  exercised — acceptable as isolated unit tests, but the meaningful integration
  coverage of the same logic comes from `test_mandate_payload_spec_unit.py` and
  the DocType-level `test_transaction.py`/`test_transaction_service.py`. The
  `_branches.py`/`payload_spec_unit.py` files stub only at the true HTTP boundary
  (`requests.Session.request`) and run request-shaping/parsing for real — not
  tautological.

- **`test_models.py` (44 tests, 18 EDGE, 0 mocks) is the cleanest file** —
  pure dataclass parsing/predicate/serialization on real objects, systematically
  covering cents-conversion, date parsing, debtor/customer fallbacks, unknown-
  status defaults, and null handling.

- **Base class:** every file uses `frappe.tests.utils.FrappeTestCase` (NOT the
  project's Enhanced/Vereniginген factory base). Consistent with pure-unit /
  infrastructure-boundary style; no test-factory usage, no auto-Customer/dues-
  schedule machinery.

## Missing files

None. All 14 assigned files were present and audited. (Directory also contains
`__init__.py` and a `fixtures/` subdir with `ing_checkout_test_helper.py`, which
were not in scope.)
