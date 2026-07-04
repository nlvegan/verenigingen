# Member Payment Development Dashboard — Build the 5 Missing Charts

**Date:** 2026-07-04
**Status:** Approved (design)

## Problem

Production logs show repeated `DoesNotExistError` on every load of the **Member
payment development** dashboard:

```
frappe.exceptions.DoesNotExistError: Dashboard Chart Monthly Revenue Trends not found
frappe.exceptions.DoesNotExistError: Dashboard Chart Revenue by Payment Status not found
```

Origin: `frappe/desk/doctype/dashboard/dashboard.py::get_permitted_charts` iterates the
dashboard's chart links and calls `frappe.has_permission("Dashboard Chart", doc=chart.chart)`,
which lazy-loads each chart. Loading a non-existent chart raises.

### Root cause (fixture drift / incomplete export)

The `Member payment development` dashboard is shipped **twice**:
- `verenigingen/fixtures/dashboard.json` (`is_standard=0`)
- `verenigingen/verenigingen_payments/verenigingen_payments_dashboard/member_payment_development/member_payment_development.json` (`is_standard=1`)

Both reference **5 chart links**:
`SEPA Payment Status`, `Monthly Revenue Trends`, `Outstanding Invoices by Month`,
`Revenue by Payment Status`, `Revenue by Quarter`.

**None of these 5 charts are defined anywhere:**
- `verenigingen/fixtures/dashboard_chart.json` contains only 4 *unrelated* charts
  (Member Count by Chapter, Member Count Trends, Members with Outstanding Invoices,
  Member Pronoun Distribution).
- None exist as standard folder charts under `verenigingen/**/dashboard_chart/`.
- `git log -S "Monthly Revenue Trends" -- .../dashboard_chart.json` returns nothing —
  they were **never** in the chart fixture.

`hooks/fixtures.py` *declares* all 11 chart names in the Dashboard Chart export filter and
`docs/ADMIN_GUIDE.md` documents "11 charts", but `bench export-fixtures` silently skips
filter names that match no DB record. So the 5 revenue/SEPA charts dropped out of the export
while the dashboard (which *did* exist as a record) exported with its dangling links intact.

Reproduced on the dev site (`veg11.veganisme.org`): the dashboard has all 5 chart-link rows;
the 5 corresponding Dashboard Chart records do not exist.

## Decision: fix direction

Chosen: **build the 5 charts** (user decision). The charts never existed, so there is no
"correct" prior definition to restore — the definitions below are new work grounded in the
actual data model.

## Design

### Delivery mechanism — folder-based standard Dashboard Charts

Ship all 5 as standard folder charts at
`verenigingen/verenigingen_payments/dashboard_chart/<slug>/<slug>.json`
(`module = "Verenigingen Payments"`, `is_standard=1`, `is_public=1`).

**Why not fixtures:** this bug was *caused by* fixture-export drift. Folder charts are synced
deterministically by `bench migrate` (`frappe/model/sync.py:93` syncs `dashboard_chart`), so
they cannot silently drift. Verified: the existing folder charts (e.g. `Member Status
Distribution`, `Migration Status Chart`) are present in the veg11 DB, proving the mechanism.

**Production self-repair (no data patch):** on the next `bench migrate`, the 5 chart records
are created and the standard dashboard's links are re-synced. The previously dangling
`Dashboard Chart Link` rows now resolve, so `get_permitted_charts` stops raising. No separate
cleanup patch is required.

### Data-scope decision — membership dues only

The 4 Sales Invoice charts filter to `is_membership_invoice = 1` (a populated custom Check
field on Sales Invoice — 677 flagged invoices on veg11, set by the billing/dues code paths).
This scopes them to genuine membership-dues revenue rather than all company invoices. All
Sales Invoice charts also filter `docstatus = 1` (submitted only).

### The 5 charts

| Chart name (docname) | chart_type | document_type | Key fields | Filters | type |
|---|---|---|---|---|---|
| **SEPA Payment Status** | Group By | Direct Debit Batch | group_by_based_on=`status`, group_by_type=Count | — | Donut |
| **Monthly Dues Revenue** | Sum | Sales Invoice | timeseries, based_on=`posting_date`, value_based_on=`grand_total`, time_interval=Monthly, timespan=Last Year | is_membership_invoice=1, docstatus=1 | Line |
| **Dues Revenue by Quarter** | Sum | Sales Invoice | timeseries, based_on=`posting_date`, value_based_on=`grand_total`, time_interval=Quarterly, timespan=Last Year | is_membership_invoice=1, docstatus=1 | Bar |
| **Outstanding Dues Invoices by Month** | Sum | Sales Invoice | timeseries, based_on=`posting_date`, value_based_on=`outstanding_amount`, time_interval=Monthly, timespan=Last Year | is_membership_invoice=1, docstatus=1, status in [Unpaid, Overdue, Partly Paid] | Bar |
| **Dues Revenue by Payment Status** | Group By | Sales Invoice | group_by_based_on=`status`, group_by_type=Sum, aggregate_function_based_on=`grand_total` | is_membership_invoice=1, docstatus=1 | Donut |

`Direct Debit Batch.status` options: Draft / Generated / Submitted / Processed / Failed / Rolled Back.

### Renaming ripple — keep every reference consistent

The 4 revenue/invoice charts are renamed from the original dangling-link names (the generic
"Revenue" wording is misleading now that they are dues-scoped). Because a Dashboard Chart's
docname *is* its `chart_name`, and the dashboard links reference charts by name, the new names
must be applied consistently in **all** of these places, or the dangling-link bug recurs:

1. The 5 folder-chart JSONs (source of truth).
2. `verenigingen/fixtures/dashboard.json` — chart-link names.
3. `verenigingen_payments_dashboard/member_payment_development/member_payment_development.json`
   — chart-link names.
4. `hooks/fixtures.py` — the Dashboard Chart export filter list.
5. `docs/ADMIN_GUIDE.md` — the documented chart list.

Name mapping:

| Original (dangling) | New |
|---|---|
| Monthly Revenue Trends | Monthly Dues Revenue |
| Revenue by Quarter | Dues Revenue by Quarter |
| Revenue by Payment Status | Dues Revenue by Payment Status |
| Outstanding Invoices by Month | Outstanding Dues Invoices by Month |
| SEPA Payment Status | *(unchanged)* |

### Fixtures note

The `dashboard_chart.json` fixture is left as-is (its 4 charts are unrelated to this
dashboard and are separately double-managed as folder charts — a pre-existing pattern, out of
scope here). `hooks/fixtures.py`'s Dashboard Chart filter is updated only to reflect the new
names, so a future `export-fixtures` does not resurrect the old names.

## Verification (failing → passing)

On `veg11.veganisme.org`:

1. **Failing:** `frappe.get_doc("Dashboard","Member payment development").get_permitted_charts()`
   currently raises `DoesNotExistError` (or, as Administrator, confirm the 5 chart records are
   absent).
2. Add the 5 folder charts + rename references.
3. `bench --site veg11.veganisme.org migrate` (syncs folder charts + re-syncs dashboards).
4. **Passing:** the 5 Dashboard Chart records exist under the new names; the dashboard's chart
   links all resolve; `get_permitted_charts()` returns all 5 without error.
5. Spot-check each chart renders data (dues invoices exist on veg11, so revenue charts are
   non-empty; SEPA batches may be sparse but the chart must not error).

## Out of scope

- Consolidating the double-shipped dashboard (fixture + standard module folder) — pre-existing,
  not required to fix the error.
- Reworking the unrelated `dashboard_chart.json` fixture charts.
