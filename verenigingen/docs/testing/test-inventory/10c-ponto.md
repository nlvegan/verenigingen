# Domain A10c — Ponto Banking Integration Services — Test Inventory

Read-only classification of every `def test_*` method across the 12 Ponto test
files under `verenigingen/tests/sepa/`. Each method assigned ONE primary type
(HAPPY / UNHAPPY / EDGE / OTHER) by dominant intent.

**Summary:** 279 test methods across 12 files. The suite is error/boundary-heavy
(85 UNHAPPY + 87 EDGE = 62% of all tests), reflecting a banking-integration
surface where validation guards, HTTP error mapping, and cryptographic webhook
rejection dominate. Only 10 OTHER (smoke/tautology/placeholder). Webhook
signature verification uses REAL RSA crypto (not mocked). All files present.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_ponto_bank_account_creator.py | 12 | 5 | 1 | 6 | 0 |
| test_ponto_betaalverzoek_client_unit.py | 26 | 7 | 14 | 5 | 0 |
| test_ponto_callbacks.py | 17 | 3 | 6 | 8 | 0 |
| test_ponto_client.py | 29 | 11 | 10 | 4 | 4 |
| test_ponto_oauth2_service.py | 25 | 12 | 5 | 8 | 0 |
| test_ponto_payment_client_unit.py | 16 | 5 | 9 | 1 | 1 |
| test_ponto_payment_initiation_service.py | 13 | 5 | 8 | 0 | 0 |
| test_ponto_sync_client_unit.py | 17 | 3 | 6 | 7 | 1 |
| test_ponto_transaction_pipeline_unit.py | 28 | 12 | 5 | 11 | 0 |
| test_ponto_webhook_entrypoint.py | 19 | 6 | 5 | 8 | 0 |
| test_ponto_webhook_handler.py | 47 | 17 | 3 | 23 | 4 |
| test_ponto_webhook_security_unit.py | 30 | 11 | 13 | 6 | 0 |
| **DOMAIN TOTALS** | **279** | **97** | **85** | **87** | **10** |

## Classification notes (non-obvious calls)

**test_ponto_bank_account_creator.py** — idempotency/reuse tests
(`creates_and_reuses_bank`, `is_idempotent_on_rerun`) → EDGE; unknown/short/empty
IBAN fallbacks → EDGE; `returns_error_dict_on_failure_not_raise` → UNHAPPY.

**test_ponto_betaalverzoek_client_unit.py** — 14 UNHAPPY: 4 amount/IBAN
validation rejects, 3 `from_api_response_*_raises`, error-wrapping pairs,
`periodic_methods_raise_not_implemented`, `verify_pis_disabled_when_mtls_off`
(config error). EDGE: sanitize/empty-passthrough, explicit-status precedence,
top-level-links promotion, IBAN space/case normalization.

**test_ponto_callbacks.py** — missing/unknown-record cases that redirect
gracefully (no throw) → EDGE; `error=access_denied`/`server_error` branches →
UNHAPPY; `payment_page_*_throws` (DoesNotExistError) → UNHAPPY; refresh-failure-
still-redirects (resilience) → EDGE; alternate payment_page states
(already_paid/cancelled) → EDGE.

**test_ponto_client.py** — 429 rate-limit tests assert a RAISE
(PontoRateLimitError) → UNHAPPY; 401-token-refresh-and-retry → EDGE;
non-advancing-cursor loop guard → EDGE. OTHER flags: `mtls_enabled_when_configured`
(no assertion — `_setup_mtls` mocked, comment "Just test that mtls flag would
be set"); `mtls_changes_base_url` (assertion guarded by `if client._use_mtls:`
so may never execute); both factory tests (isinstance/identity smoke).

**test_ponto_payment_client_unit.py** — mostly validation-reject UNHAPPY;
`bad_exec_date_tolerated` → EDGE; `factory_returns_instance` → OTHER (smoke,
inner PontoClient patched).

**test_ponto_payment_initiation_service.py** — 7 `rejects_*` validation guards +
`cancel_executed_payment_throws` → UNHAPPY; create/list/cancel-draft → HAPPY.
No EDGE/OTHER.

**test_ponto_sync_client_unit.py** — error-class→status mapping: 404/500/
resourceNotFound/unexpected-exception → UNHAPPY; in-progress & rate-limited
→pending (concurrency/backoff) → EDGE; empty-list/no-data/missing-account-id →
EDGE; `factory_returns_instance` → OTHER.

**test_ponto_transaction_pipeline_unit.py** — 11 EDGE: client-side date filter,
empty/absent results, IBAN normalization, party-matching-error-swallowed,
description dedup/empty-fallback(regression)/partial, disabled-account-skip,
zero-imported no-increment, import_all skips None mapping. UNHAPPY = empty-id
raises + orchestration error results.

**test_ponto_webhook_entrypoint.py** — signature-fail→401 & missing-sig→401 →
UNHAPPY; sync-failed callback tests → UNHAPPY; invalid-JSON/unknown-format→400
(malformed payload) → EDGE; rate-limited→429 → EDGE; webhooks-disabled → EDGE;
savepoint-name sanitizer (hyphen bug regression) → EDGE.

**test_ponto_webhook_handler.py** — 23 EDGE: alternate-format extraction,
missing-id/not-found graceful reason-dicts (no throw), None-event defaults,
duplicate-detection, long-error truncation, no-mapping→False, no-member skip,
nonexistent-invoice→None. OTHER flags: `test_status_mapping` (TAUTOLOGY — builds
a local dict then asserts `dict.get(k) == same dict's value`; never touches
production code); `routes_all_event_types` (completeness smoke over 14 types
with minimal payloads); two `TestPontoWebhookSignatureVerification` methods with
`pass` bodies (placeholders, deferred to security_unit).

**test_ponto_webhook_security_unit.py** — REAL RS512 crypto (RSA keypair
generated in-test, real JWTs signed, only JWKS-fetch boundary stubbed). 13
UNHAPPY: missing/empty/wrong-key/expired/wrong-aud/wrong-iss/wrong-alg/missing-
claim rejections, kid-not-found, error-wrap, cert-setup-failure & permanent-
error raises, no-application-id. EDGE: tampered-digest-mismatch, iat-tolerance
boundary, malformed-token, mTLS cache-fallback pairs, jwks-client caching.

## Observations

- **Webhook-security coverage is strong and genuine.** `test_ponto_webhook_security_unit.py`
  (30 tests) performs real cryptographic verification — generates an RSA-2048
  keypair, signs real RS512 JWTs, and stubs ONLY the JWKS-fetch boundary. It
  covers the full rejection matrix: wrong-key, expired, wrong-aud/iss/alg,
  missing-digest-claim, tampered-payload digest mismatch, and iat-tolerance.
  This is the opposite of a mock tautology.
- **OAuth2 token-refresh/lifecycle is well covered** (test_ponto_oauth2_service.py):
  PKCE pair generation + uniqueness, S256 challenge derivation, state
  CSRF-verify + one-time-use clearing + expiry, expired-token→refresh, 5-minute
  proactive-refresh buffer, cache↔DB fallback, and code_verifier one-time
  clearing. The 401-triggers-refresh path is also exercised at the HTTP-client
  layer (test_ponto_client.py) as EDGE.
- **Mock-tautology / weak-test flags (10 OTHER, plus 3 notable weak assertions):**
  `test_status_mapping` (webhook_handler) asserts a locally-built dict against
  itself — zero production coverage. Two `TestPontoWebhookSignatureVerification`
  methods are `pass` stubs. `mtls_enabled_when_configured` (client) has NO
  assertion. `mtls_changes_base_url` hides its only assert behind
  `if client._use_mtls:` which may never fire. `routes_all_event_types` is a
  broad completeness smoke.
- **Validation-guard density is high** (85 UNHAPPY): amount zero/excess/three-
  decimal, non-EUR, invalid-IBAN, and missing-field rejections are repeated
  across betaalverzoek, payment, and initiation-service layers — good
  defense-in-depth but with substantial cross-layer duplication.
- **Error-to-status mapping (graceful, no-throw) is consistently EDGE, not
  UNHAPPY:** sync-client maps 404→skipped / in-progress→pending, and webhook
  handlers return `{reason: not_found}` dicts. Only paths that actually raise
  (or assert HTTP 401/429/400 envelopes) were counted UNHAPPY.
- **Base class:** every file uses `frappe.tests.utils.FrappeTestCase` directly
  (NOT the project's Enhanced/Verenigingen factory base). Unit-tier files
  (`*_unit.py`) stub only the HTTP boundary; integration files use real DocType
  writes (Ponto Payment Request/Link, Bank Account) and `SingletonBackup`/
  `singleton_backup` to protect the `Ponto Settings` single.

## Missing files

None. All 12 assigned files were present and classified.
