# Test-Isolation Cache-Guard Campaign — Design Spec

**Date:** 2026-07-25
**Status:** Draft for review
**Author:** foppe (with Claude Code)

## 1. Problem

Twice, CI failures on parallel "Server Tests" shards have traced to the same latent
test-isolation anti-pattern: a test **reads permission/role/cache state through a
request-local cache that has become stale**, and the read is only correct by accident
of shard composition.

Canonical instance (`verenigingen/tests/services/test_payment_entry_creation_service.py`,
fixed in `5caed9e8`): a test asserted
`frappe.has_permission("Payment Entry", "create", user=restricted_user)` as a **pre-check
guard** *before* `frappe.set_user(restricted_user)`. That guard resolves the permission
through the request-local `role_permissions`/meta cache of the **current (Administrator)**
context. In a shared-process parallel shard, that cache layer can hold a stale answer for a
freshly-granted Custom DocPerm, so the guard flakes deterministically on certain shard
compositions — while the grant is correct in the DB and the actual behavior-under-test
(after `set_user` clears the caches) resolves fine.

### 1.1 Mechanism (the sharp edge)

`frappe.set_user(username)` (`frappe/__init__.py`) clears `local.role_permissions={}`,
`local.cache={}`, `local.user_perms=None`, `local.session.data`. Therefore **any read of
permission/role/cache state that runs against a cache populated before a grant/switch, and
that is not preceded by a full reset of the specific cache layer it consults, is
shard-order-fragile.**

Critically (per our own history, MEMORY.md): `clear_cache(doctype=...)` and
`get_meta(cached=False)` do **not** bust the `frappe.local.role_permissions` memo — only
clearing `role_permissions` itself (or a full `set_user`/`clear_cache()`) does. The analyzer
must not treat every `clear_cache(...)` call as a sufficient reset.

### 1.2 The true anchor: grant-without-reset → stale read

`set_user` is the token present in the *fixed* shape, not the *buggy* shape. The buggy shape
is **a cache-reading permission/role call reachable after a same-process grant
(`add_permission` / `update_permission_property` / role assignment) without an intervening
reset of the consulted cache layer.** The dominant real shape is cross-function:
`setUp` performs the grant/switch; a `test_*` method performs the stale read. A per-function
analyzer cannot see this.

## 2. Scope

**Medium** (chosen): the exact pre-`set_user`-guard pattern **plus** any test read of
framework cache/global state (`role_permissions`, `local.cache`, `user_perms`, meta cache,
session) that a later same-test (or setUp→method) operation invalidates. Not the full
"all shard-order fragility" audit (shared fixtures, ordering of unrelated setup).

## 3. Measured surface

Re-derived with the **broadened** invalidator/reader/grant idiom sets (the initial narrow
`frappe.set_user` + `frappe.has_permission` heuristic undercounted by ~50%):

| Idiom class | Dominant forms (files / sites) |
|---|---|
| Invalidator (switch) | `as_user(` **114 / 732**, `frappe.set_user(` 182 / 655, `self.set_user(` 30 / 197, `as_role(` 19 / 145, `mock_roles(` 2 / 5 |
| Reader | `.has_permission(` 19 / 64, `get_roles(` 21 / 52, `has_donor_permission` 6 / 97, `get_donor_permission_query` 6 / 50, `frappe.has_permission(` 16 / 35, `check_permission(` 7 / 18 |
| Grant | `add_permission(` 3, `update_permission_property(` 3, `add_roles(` 9, `_ensure_board_member_role` 1 (plus grants hidden in `as_role`, `create_test_user(roles=...)`) |

**Audit surface: 54 test files** pair an invalidator/grant with a reader (vs. 36 under the
narrow heuristic).

Key facts that reshaped the design (from skeptical review, verified):
- `EnhancedTestCase.as_user` (`enhanced_test_factory.py:4921`) is a context manager that calls
  `frappe.set_user` on **entry** and again in `finally` on **exit** — so the *close* of a
  `with self.as_user(x):` block is also a cache-invalidation point.
- `as_user` / `as_role` / `set_user` context managers are **redefined per-file** in several
  places — an import-name allowlist will not catch method calls on `self`.
- App-wrapper readers (`has_donor_permission`, `get_donor_permission_query`) and doc-bound
  `.has_permission` dominate over raw `frappe.has_permission`; a fixed name list keyed on
  `frappe.*` misses the majority.

## 4. Approach: two artifacts, opposite precision/recall targets

Rather than one perfectly-sound cross-function grant-tracking analyzer (which would itself be
flaky and is over-engineered for a gate), split the work:

### 4.1 Audit detector (recall-favoring, human-triaged)

- Python `ast`-based, **spans `setUp` + `test_*` methods of each `TestCase` class** (not
  per-function).
- Resolves the broadened idiom sets:
  - **Invalidators/resets:** `frappe.set_user`, `frappe.clear_cache` (full only), and the
    `as_user` / `as_role` / `set_user` context managers (modeling enter / body / exit scope).
  - **Grants:** `add_permission`, `update_permission_property`, `add_roles`, `as_role`, and
    known role-granting helpers (`_ensure_board_member_role`, `create_test_user(roles=...)`).
  - **Readers:** `has_permission` (bare and doc-bound `.has_permission`), `get_roles`,
    `get_doc_permissions`, `has_perm`, `get_all_perms`, `check_permission`, and project
    wrappers (`has_donor_permission`, `get_donor_permission_query`) — configurable list.
  - Flags **load-bearing non-assert reads** (result bound to a variable / drives a branch),
    not only `assert*` subtrees.
- **Output:** a triage report — one row per candidate `(file, line, class, function, reader,
  nearest preceding grant/switch, whether a reset intervenes)`. FPs are expected and fine;
  every row is triaged by a human/subagent.

### 4.2 Standing gate (precision-favoring, advisory-first)

- `scripts/validation/test_isolation_cache_guard_validator.py`, styled like the existing
  `ast-field-analyzer` / `doctype-field-validator` hooks.
- Deliberately **narrow** to the soundly-detectable shape: a cache-reading **assertion**
  that precedes the first invalidator **within a single function** (or reads the closing-scope
  of a `with as_user` block). It does **not** claim to catch the cross-function
  setUp→method shape — that is the one-time audit's job. This limitation is stated in the
  hook's own docstring so nobody mistakes a green gate for a clean suite.
- **Suppression:** trailing `# cache-guard-ok: <reason>` where `<reason>` is a fixed
  taxonomy — `baseline-intentional` | `false-positive` | `relocated-elsewhere`. This lets us
  grep suppressions by class and periodically re-audit `false-positive` (analyzer bugs) and
  `baseline-intentional` (still arguably fragile) separately.
- Ships with fixture unit tests: one offender, one suppressed, one legitimate-baseline, one
  clean, one `with as_user` closing-scope case.

## 5. Triage + fix strategy

Each candidate is classified into exactly one bucket:

1. **Delete-redundant** — permitted **only** when a post-switch assertion re-proves the
   guarded fact **and its failure is uniquely attributable** to that fact (message-pinned via
   `assertIn(<specific message>, str(ctx.exception))`, or the assertion is satisfiable by
   exactly one perm state). The audit template requires recording *which* post-switch
   assertion provides the re-proof. If none exists → this is **not** bucket 1.
   - Guardrail rationale: a bare `assertRaises(frappe.PermissionError)` with no message pinning
     is satisfiable by more than one perm state; deleting a positive-capability guard there can
     convert a real regression (grant silently not applied) into a passing test.
2. **Relocate** — the read is meaningful but belongs *after* the switch (fresh resolution).
   Move it down. This is the default when bucket-1's re-proof condition is not met.
3. **Legitimate baseline** — genuinely testing the pre-switch context on purpose. Keep, add
   `# cache-guard-ok: baseline-intentional`. (Note: a baseline read is itself somewhat
   fragile; the suppression documents intent, it does not make it robust.)

**Message-pinning pass:** in any PR that removes a positive-capability guard, add message
pinning to the corresponding post-switch `assertRaises` where it is missing — so we never
trade a flaky-but-meaningful test for a stable-but-hollow one. (Several flagged files —
e.g. `test_chapter_permissions.py` — already use bare `assertRaises` with no message.)

Triage is driven by `skeptical-code-reviewer` subagents that read the production code under
test, so load-bearing assertions are not mechanically deleted.

## 6. Sequencing (gate never blocks the cleanup)

1. **Spec** (this doc) → user review.
2. **Audit detector + report** — quantify the true surface across the 54 files.
3. **Triage** the report into the three buckets.
4. **Batched per-directory fix PRs** (`sepa/`, `donor/`, `chapter/`, `security/`,
   `services/`, …), each independently green in CI, message-pinning folded in.
5. **Standing gate** wired **advisory/warn first**; collect FP/FN against the ~110-file
   `as_user` corpus.
6. **Flip gate to pre-push blocking** only after the report is empty **and** the FP rate is
   measured near-zero.

## 7. Testing

- Audit detector: validated against the known-good fixed file (`5caed9e8`) — must not flag it
  — and the known offender shape (must flag a reconstructed pre-fix version).
- Standing gate: fixture-based unit tests (§4.2).
- Each fix batch: the touched modules run green locally; CI green on the batch PR (including,
  where feasible, an adversarial-order run to confirm the fragility is gone).

## 8. Non-goals / explicit limitations

- The standing gate does **not** soundly detect the cross-function setUp→method shape. That is
  covered by the one-time audit, not the recurring gate. A future v2 may add cross-function
  grant-tracking once the narrow gate's FP rate is validated.
- Not addressing non-permission shard-order fragility (shared fixtures, unrelated setup
  ordering) — out of scope for this campaign.
- The "54 files" surface may still grow as helper-resolution improves during the audit; PR
  sizing is re-derived from the detector's report, not from this static count.
