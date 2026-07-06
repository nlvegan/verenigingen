# Critical Operation Rules: density lens + named-profiles option

**Date:** 2026-07-06
**Status:** report shipped (prototype); log reframe + dead-field/decorative-field cleanups
DONE (branch `refactor/cor-log-reframe-dead-field-cleanup`); named-profiles = proposal for
a future decision
**Context:** ~2,597 enabled `Critical Operation Rule` (COR) rows — one per whitelisted
endpoint — feel unwieldy and carry a high learning curve. The rows are seeded and
functionally correct, so nobody is blocked; this is a *comprehensibility* debt, not a
correctness one.

## What COR actually is (two layers)

1. **Presets** = decorators (`@critical_api`, `@high_security_api`, `@standard_api`,
   `@utility_api`, `@public_api`) → 5 `SecurityProfile`s. A dev adds a decorator and
   gets sane request-handling defaults (audit, input validation, IP, size, methods).
2. **COR rows** = per-endpoint DB records that carry **rate limits** (the dominant
   payload) plus optional overrides (business rules, restrictions, escalation, audit).
   Matched to a function by name at call time; a `_generic_api_fallback` row catches
   anything unmatched.

## Measured reality (live veg11, 2,597 enabled rows)

Source: `Critical Operation Rule Config Density` report (below).

| Signal | Value | Reading |
|---|---|---|
| Distinct config payloads | **211** | 2,597 rows collapse ~12:1 |
| Top-3 configs cover | **51%** | a handful dominate |
| Top-12 configs cover | **68%** | |
| Escalation used (`allow_system_user`/`bypass_validations`) | **0** | dead capability |
| Business validation used | **0** | dead capability |
| IP / time restrictions used | **0** | dead capability |
| Elevated audit / alert | 524 | real, but tracks level+type |
| `required_roles` set | **2,545** | **decorative** — authz flows from level via `ROLE_PROFILE_SECURITY_MAPPING`, not this field |

### Root cause of the proliferation

`api_security_framework.py:699` logs — at `.info()` — *"Critical Operation Rule lookup
failed… indicates missing fixture data or incorrect naming conventions"* on any miss.
It is informational in severity but accusatory in wording, which trained everyone to
add a row per endpoint. **The rows are load-bearing for log-silence, not for behavior:**
the rate-limit engine already falls back to `_generic_api_fallback` silently and
correctly. Reframing that log to a debug-level *"no override for X; using preset
<level>"* is the keystone that makes sparse rows sustainable — without it, the count
grows with every new endpoint regardless of any cleanup.

## Shipped: the discoverability report (option b)

`verenigingen/verenigingen/report/critical_operation_rule_config_density/` — a Script
Report that collapses the rows to their 211 distinct configs, sorted by endpoint count,
with cumulative coverage, example endpoints, and summary cards (distinct configs,
top-3 coverage, dead-field usage, decorative-roles count). Filters by operation type /
security level to zoom into a bucket. Read-only; zero data/schema change.

This is the low-risk win: you learn ~12 profiles, not 2,597 rows. It also *measures*
whether the bigger refactor below is worth doing.

## Proposal (future): named profiles + reference

The 211-config number says the natural unit is **not** "a row per endpoint" — it is
"~N named rate-limit/audit profiles, referenced by endpoints."

**Shape:** define a small set of named presets (a `Security Rate Profile` doctype, or a
code table) — e.g. `reporting-low-standard`, `financial-high-oauth`, `webhook-public`.
Each endpoint references one profile (by decorator argument or a thin
endpoint→profile map). A COR row is materialized **only** when an endpoint genuinely
deviates from its profile.

**Benefits:**
- 2,597 rows → ~211 profile defs + a lookup (and likely far fewer once near-duplicate
  configs are merged: top-12 already cover 68%).
- The learning curve becomes "know the ~12 common profiles."
- Rate limits gain a real, named baseline — so "deviation" becomes well-defined (it
  isn't today; rate limits live *only* in COR rows).

**Migration path (incremental, reversible):**
1. Reframe the missing-COR log (keystone; do first).
2. Cluster the 211 configs → propose a canonical named set (report already does the
   clustering).
3. Introduce profiles alongside COR; endpoints opt in; COR row only for true overrides.
4. Stop seeding boilerplate rows; let the fallback + profile carry the common case.

**Risks:** touches the security-critical path; needs the fallback proven solid under
sparse rows; the long tail (211 configs, 50% of rows are non-modal within their coarse
bucket) means "merge to N presets" requires judgement, not a mechanical squash.

**Decision input:** run the density report. If the effective config set is genuinely
~12–20 after merging near-duplicates, the refactor pays off; if the tail is genuinely
irreducible, keep the report (b) and skip the refactor.

## Keystone + cleanups — DONE (branch `refactor/cor-log-reframe-dead-field-cleanup`)

1. **Keystone: missing-COR log reframed.** `api_security_framework.py` (`.info` "lookup
   failed… missing fixture data") → `.debug` "no per-operation rule; using preset
   defaults", and the same in `critical_operation_rule.py:get_rule_config`. Absence is
   now treated as the normal state, removing the pressure that seeds a row per endpoint.
2. **Dead capability fields hidden** (form-only `hidden: 1`, fully reversible; code +
   columns untouched): `allow_system_user`, `bypass_validations`, and the entire
   Business Rules group (`enable_business_validation`, `amount_threshold`,
   `time_restrictions`, `ip_restrictions`). Verified 0 live usage; the config values
   these produce are written by `get_rule_config` but consumed by nothing (the enforced
   `allow_system_user`/`bypass_validations` mechanism is the `secure_document_operation`
   parameter, independent of the COR row).
3. **Decorative authz fields marked read-only** with honest descriptions:
   `required_roles`, `required_permissions`. They are written into config but never
   enforced (authz flows from Security Level). Not wired up (risky — 2,545 rows would
   suddenly enforce) and not dropped (destructive); read-only + description kills the
   footgun reversibly.

Verified: 69 tests green (COR doctype ×27, api-security-framework ×42) on `test_site_2`;
field meta + lookup behavior confirmed on veg11.

### Safety-net audit (from skeptical review) — done, with a method correction

Declaring `required_roles` decorative is only safe if no endpoint was actually
*relying* on it for a restriction its gate doesn't already provide. A first pass
compared the 2,545 role-bearing rows against the COR-row `security_level` and flagged
**0** `public`, **5** `low`, **27** `medium` rows as "role intent stricter than level".

**That method was wrong** and the 5 flags are false positives. Runtime *authorization*
is driven by the **decorator** on the function (`get_endpoint_security_level` reads the
decorator's `custom_level`/`operation_type`), **not** the COR row's `security_level`
(which drives rate-limiting and is emitted into config but is not the auth gate).
Spot-checking all 5:

- `generate_api_documentation`, `get_api_endpoints_summary` (+ `admin_tools_` aliases):
  `@high_security_api(operation_type=ADMIN)` → enforced at **HIGH** (role-profile-only).
  Correctly admin-gated. Their COR-row `security_level=low` is a stale artifact.
- `get_metrics_for_zabbix`: `@frappe.whitelist(allow_guest=True)` with its own
  `_require_zabbix_auth()` token/IP gate. Guest-by-design, protected separately.

**Corrected conclusions:**
1. No under-gating found; the "decorative" label for `required_roles` holds — the real
   gate (decorator) is *stricter* than the COR row in every flagged case.
2. New insight: the COR-row `security_level` can **drift** from the decorator's enforced
   level (here `low` vs `high`). Another reason COR rows are not a source of truth — but
   it is a data-hygiene issue, not a security hole.
3. A fully rigorous check would compare `required_roles` against each endpoint's
   *decorator* level (resolve operation_name → function → decorator for all 2,545). That
   is a larger separate task; the spot-check plus the decorator-is-stricter pattern make
   it low-priority.

### Not done here (larger, separate decisions)
- Actually deleting boilerplate rows / going sparse (needs the keystone to have soaked).
- The named-profiles refactor above.
- Dropping the now-hidden columns (destructive; only after confirming no revival plan).

## Reproduce

Desk → Reports → *Critical Operation Rule Config Density*. Or headless:
`execute()` in
`verenigingen.verenigingen.report.critical_operation_rule_config_density.critical_operation_rule_config_density`.
