# Customer-naming fragility — investigation & fix proposal

**Date:** 2026-06-07  **Status:** APPROVED — "E now + A later" (Foppe). Option E implemented
(`insert_customer_with_duplicate_retry` applied to the canonical path + 3 Mollie insert sites,
tests in `tests/member/test_customer_creation_duplicate_name.py`); Option A tracked as follow-up.
**Origin:** surfaced while root-causing test-suite order-dependence; Foppe flagged that
real members can share a name, so the mechanism isn't test-only.

## The mechanism

`create_customer_for_member` (`services/member/approval/application_payments.py:144`)
creates a Customer with `customer_name = member.full_name` and a link `member = member.name`.
Its only dedup is **keyed by the member link** (line 147) — it does nothing about two
*different* members sharing a name.

The live site has `Selling Settings.cust_master_name = "Customer Name"`, so ERPNext's
`Customer.autoname()` sets `Customer.name = get_customer_name()`
(`erpnext/.../customer.py:109`). `get_customer_name()` (line 118) checks
`frappe.db.get_value("Customer", customer_name)` and, if it exists, appends `" - N"`.

So **two members named "Jan de Vries"** →
`Jan de Vries`, then `Jan de Vries - 1`, `- 2`, … No hard crash in normal *sequential*
flow. The failure modes are:

1. **Concurrency / TOCTOU.** `get_customer_name` does `get_value` then `insert` with no
   lock. Two same-named Customers created near-simultaneously (or a delete-then-recreate)
   both pass the check, both try to insert the same name → hard `DuplicateEntryError`,
   `create_customer_for_member` rolls back its savepoint and `raise`s → the member's
   invoice/approval fails. This is exactly what the test suite hits constantly, because
   ~47 test files share the hardcoded identity `Test Verenigingen Volunteer`.
2. **Cosmetic sprawl + orphans.** The `" - N"` counter grows; rolled-back/merged member
   creations leave Customers with `member = NULL`.

## Honest severity (don't overclaim)

The live numbers are **inflated by load-test pollution** on veg11 (bulk "Load Tester",
"ValidatorNN TestMember" members), so they are an upper bound, not a clean signal:

| Metric (veg11, read-only) | Count | Caveat |
|---|---|---|
| Customers total | 16,261 | |
| Orphan Customers (`member` NULL) | 2,329 (~14%) | mostly eBoekhouden imports / donors / merges — **not** all this bug |
| …of those, carry Sales Invoices | 1,119 | not safely deletable |
| Suffixed Customers (`Name - N`) | 5,174 | heavily test-inflated |
| Active members with NO Customer | 128 | **likely benign** — creation is semi-lazy (fires at first invoice in `create_membership_invoice_with_amount`), so un-invoiced members legitimately have none |

**Net:** in production today this is a *latent concurrency race + cosmetic sprawl*, not an
active fire (ERPNext's suffixing prevents hard failures in the common sequential path).
It is, as flagged, "not optimal" — worth fixing proportionately.

## Risk audit for a naming change

- **No production code uses `full_name` as the Customer PK** — grep for
  `get_doc/get_value/exists("Customer", <name-like>)` outside tests returned zero hits.
- **eBoekhouden resolves parties by the `customer_name` *field*** (`party_resolver.py:15`
  `"name_field": "customer_name"`) and `eboekhouden_relation_code`, not by PK → robust to
  a naming change. (Final check of eBoekhouden's own create path still TODO.)

## Options

**E — Bounded retry on DuplicateEntryError (RECOMMENDED, proportionate).**
Wrap the `customer.insert()` in `create_customer_for_member` (and the two Mollie/payment
`_create_customer_for_member` equivalents) in a small retry: on `DuplicateEntryError`,
roll back the savepoint and retry (≤3×). On retry, `get_customer_name` sees the now-present
Customer and appends `" - N"`, so it succeeds. Eliminates the hard-crash race for both
production and the test suite. Keeps current naming (sprawl remains, cosmetic).
*Blast radius: tiny, reversible, member-customer path only.*

**A — Switch Customer naming to a series (`cust_master_name = "Naming Series"`).**
`Customer.name` becomes `CUST-.YYYY.-`; `customer_name` keeps the readable full name.
Removes the entire collision class, the TOCTOU race, AND the sprawl — and kills the
Customer-collision driver of test order-dependence at the root. *Blast radius: global —
affects ALL Customer creation incl. eBoekhouden/donors; mixed naming with existing
records (acceptable); needs the eBoekhouden create-path check. Overkill for current
severity but the clean structural fix.*

**Cleanup (separate, optional).** Backfill/triage the orphan Customers + customerless
members. Deferred — most are test-pollution or legitimately member-less; needs its own
scoping and is not on the critical path.

## Recommendation

Ship **E** now (small, safe, fixes the real race + de-flakes the test collisions), and
keep **A** on the table as a follow-up if we want to retire name-based Customer PKs
entirely. Do **cleanup** only after scoping how many orphans are genuinely this bug vs
eBoekhouden/merges.

## Test-suite tie-in

**Important:** Option E does NOT fix the Customer-collision *tests*. `EnhancedTestCase.setUp`
sets `frappe.flags.in_import = True` (to skip user-creation throttling), and ERPNext's
`get_customer_name` disables its `" - N"` suffixing when `in_import` is set
(`... and not frappe.flags.in_import`). So in tests, same-name Customers collide *hard*
(no suffix to retry toward) — production never sees this (it runs with `in_import` False).
The Customer-collision test subset must therefore be fixed with **unique test identities**,
not the retry. Remaining test order-dependence — `get_all(DT, limit=1)` reuse and
under-seeding — is separate. See [[test-order-dependence-2026-06-07]].
