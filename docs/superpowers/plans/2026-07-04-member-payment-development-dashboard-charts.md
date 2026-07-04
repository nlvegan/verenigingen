# Member Payment Development Dashboard Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 5 Dashboard Charts that the "Member payment development" dashboard references but which were never defined, eliminating the production `DoesNotExistError`.

**Architecture:** Ship the charts as folder-based standard Dashboard Charts under the Verenigingen Payments module. Frappe's `bench migrate` syncs them (`frappe/model/sync.py:93`), so they self-repair existing databases with no data patch. Rename the 4 Sales-Invoice charts to dues-scoped names and keep every reference (both dashboard definitions, fixtures filter, docs) in sync so the dangling-link bug cannot recur.

**Tech Stack:** Frappe Framework v16, Dashboard Chart doctype (JSON config), Python (`bench`, pytest via `run-tests`).

## Global Constraints

- Target site for verification: `veg11.veganisme.org`. All bench commands use `--site veg11.veganisme.org`.
- Chart delivery is **folder-based standard charts only** (`is_standard=1`, `is_public=1`), NOT fixtures. Do not add these charts to `verenigingen/fixtures/dashboard_chart.json`.
- Module for all 5 charts: `Verenigingen Payments`. Folder path: `verenigingen/verenigingen_payments/dashboard_chart/<slug>/<slug>.json`.
- The 4 Sales Invoice charts filter `is_membership_invoice = 1` AND `docstatus = 1`.
- A Dashboard Chart's docname equals its `chart_name`. Chart names MUST match the dashboard link references exactly.
- Final chart names: `SEPA Payment Status` (unchanged), `Monthly Dues Revenue`, `Dues Revenue by Quarter`, `Outstanding Dues Invoices by Month`, `Dues Revenue by Payment Status`.

---

### Task 1: Create the 5 folder-based Dashboard Charts

**Files:**
- Create: `verenigingen/verenigingen_payments/dashboard_chart/sepa_payment_status/sepa_payment_status.json`
- Create: `verenigingen/verenigingen_payments/dashboard_chart/monthly_dues_revenue/monthly_dues_revenue.json`
- Create: `verenigingen/verenigingen_payments/dashboard_chart/dues_revenue_by_quarter/dues_revenue_by_quarter.json`
- Create: `verenigingen/verenigingen_payments/dashboard_chart/outstanding_dues_invoices_by_month/outstanding_dues_invoices_by_month.json`
- Create: `verenigingen/verenigingen_payments/dashboard_chart/dues_revenue_by_payment_status/dues_revenue_by_payment_status.json`

**Interfaces:**
- Produces: 5 Dashboard Chart records with docnames `SEPA Payment Status`, `Monthly Dues Revenue`, `Dues Revenue by Quarter`, `Outstanding Dues Invoices by Month`, `Dues Revenue by Payment Status`. Task 2's dashboard links depend on these exact names.

- [ ] **Step 1: Create the SEPA Payment Status chart**

`verenigingen/verenigingen_payments/dashboard_chart/sepa_payment_status/sepa_payment_status.json`:

```json
{
  "chart_name": "SEPA Payment Status",
  "chart_type": "Group By",
  "color": "#6554C0",
  "creation": "2026-07-04 00:00:00.000000",
  "custom_options": "{\"truncateLegends\": 1, \"maxSlices\": 8}",
  "docstatus": 0,
  "doctype": "Dashboard Chart",
  "document_type": "Direct Debit Batch",
  "dynamic_filters_json": "[]",
  "filters_json": "[]",
  "group_by_based_on": "status",
  "group_by_type": "Count",
  "idx": 0,
  "is_public": 1,
  "is_standard": 1,
  "modified": "2026-07-04 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen Payments",
  "name": "SEPA Payment Status",
  "number_of_groups": 0,
  "owner": "Administrator",
  "parent_document_type": "Direct Debit Batch",
  "timeseries": 0,
  "type": "Donut",
  "use_report_chart": 0,
  "y_axis": []
}
```

- [ ] **Step 2: Create the Monthly Dues Revenue chart**

`verenigingen/verenigingen_payments/dashboard_chart/monthly_dues_revenue/monthly_dues_revenue.json`:

```json
{
  "chart_name": "Monthly Dues Revenue",
  "chart_type": "Sum",
  "based_on": "posting_date",
  "color": "#36B37E",
  "creation": "2026-07-04 00:00:00.000000",
  "custom_options": "{}",
  "docstatus": 0,
  "doctype": "Dashboard Chart",
  "document_type": "Sales Invoice",
  "dynamic_filters_json": "[]",
  "filters_json": "[[\"Sales Invoice\",\"is_membership_invoice\",\"=\",1],[\"Sales Invoice\",\"docstatus\",\"=\",1]]",
  "idx": 0,
  "is_public": 1,
  "is_standard": 1,
  "modified": "2026-07-04 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen Payments",
  "name": "Monthly Dues Revenue",
  "number_of_groups": 0,
  "owner": "Administrator",
  "time_interval": "Monthly",
  "timeseries": 1,
  "timespan": "Last Year",
  "type": "Line",
  "use_report_chart": 0,
  "value_based_on": "grand_total",
  "y_axis": []
}
```

- [ ] **Step 3: Create the Dues Revenue by Quarter chart**

`verenigingen/verenigingen_payments/dashboard_chart/dues_revenue_by_quarter/dues_revenue_by_quarter.json`:

```json
{
  "chart_name": "Dues Revenue by Quarter",
  "chart_type": "Sum",
  "based_on": "posting_date",
  "color": "#FFAB00",
  "creation": "2026-07-04 00:00:00.000000",
  "custom_options": "{}",
  "docstatus": 0,
  "doctype": "Dashboard Chart",
  "document_type": "Sales Invoice",
  "dynamic_filters_json": "[]",
  "filters_json": "[[\"Sales Invoice\",\"is_membership_invoice\",\"=\",1],[\"Sales Invoice\",\"docstatus\",\"=\",1]]",
  "idx": 0,
  "is_public": 1,
  "is_standard": 1,
  "modified": "2026-07-04 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen Payments",
  "name": "Dues Revenue by Quarter",
  "number_of_groups": 0,
  "owner": "Administrator",
  "time_interval": "Quarterly",
  "timeseries": 1,
  "timespan": "Last Year",
  "type": "Bar",
  "use_report_chart": 0,
  "value_based_on": "grand_total",
  "y_axis": []
}
```

- [ ] **Step 4: Create the Outstanding Dues Invoices by Month chart**

`verenigingen/verenigingen_payments/dashboard_chart/outstanding_dues_invoices_by_month/outstanding_dues_invoices_by_month.json`:

```json
{
  "chart_name": "Outstanding Dues Invoices by Month",
  "chart_type": "Sum",
  "based_on": "posting_date",
  "color": "#FF5630",
  "creation": "2026-07-04 00:00:00.000000",
  "custom_options": "{}",
  "docstatus": 0,
  "doctype": "Dashboard Chart",
  "document_type": "Sales Invoice",
  "dynamic_filters_json": "[]",
  "filters_json": "[[\"Sales Invoice\",\"is_membership_invoice\",\"=\",1],[\"Sales Invoice\",\"docstatus\",\"=\",1],[\"Sales Invoice\",\"status\",\"in\",[\"Unpaid\",\"Overdue\",\"Partly Paid\"]]]",
  "idx": 0,
  "is_public": 1,
  "is_standard": 1,
  "modified": "2026-07-04 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen Payments",
  "name": "Outstanding Dues Invoices by Month",
  "number_of_groups": 0,
  "owner": "Administrator",
  "time_interval": "Monthly",
  "timeseries": 1,
  "timespan": "Last Year",
  "type": "Bar",
  "use_report_chart": 0,
  "value_based_on": "outstanding_amount",
  "y_axis": []
}
```

- [ ] **Step 5: Create the Dues Revenue by Payment Status chart**

`verenigingen/verenigingen_payments/dashboard_chart/dues_revenue_by_payment_status/dues_revenue_by_payment_status.json`:

```json
{
  "chart_name": "Dues Revenue by Payment Status",
  "chart_type": "Group By",
  "aggregate_function_based_on": "grand_total",
  "color": "#00B8D9",
  "creation": "2026-07-04 00:00:00.000000",
  "custom_options": "{\"truncateLegends\": 1, \"maxSlices\": 8}",
  "docstatus": 0,
  "doctype": "Dashboard Chart",
  "document_type": "Sales Invoice",
  "dynamic_filters_json": "[]",
  "filters_json": "[[\"Sales Invoice\",\"is_membership_invoice\",\"=\",1],[\"Sales Invoice\",\"docstatus\",\"=\",1]]",
  "group_by_based_on": "status",
  "group_by_type": "Sum",
  "idx": 0,
  "is_public": 1,
  "is_standard": 1,
  "modified": "2026-07-04 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "Verenigingen Payments",
  "name": "Dues Revenue by Payment Status",
  "number_of_groups": 0,
  "owner": "Administrator",
  "parent_document_type": "Sales Invoice",
  "timeseries": 0,
  "type": "Donut",
  "use_report_chart": 0,
  "y_axis": []
}
```

- [ ] **Step 6: Sync the charts into the database**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org migrate`
Expected: completes without error (this syncs the 5 new folder charts).

- [ ] **Step 7: Verify all 5 chart records now exist with correct config**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org mariadb -N -e "
SELECT name, chart_type, document_type FROM \`tabDashboard Chart\`
WHERE name IN ('SEPA Payment Status','Monthly Dues Revenue','Dues Revenue by Quarter','Outstanding Dues Invoices by Month','Dues Revenue by Payment Status')
ORDER BY name;"
```
Expected: 5 rows returned:
- `Dues Revenue by Payment Status | Group By | Sales Invoice`
- `Dues Revenue by Quarter | Sum | Sales Invoice`
- `Monthly Dues Revenue | Sum | Sales Invoice`
- `Outstanding Dues Invoices by Month | Sum | Sales Invoice`
- `SEPA Payment Status | Group By | Direct Debit Batch`

- [ ] **Step 8: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/verenigingen_payments/dashboard_chart/
git commit -m "feat(dashboard): add 5 Member payment development dashboard charts"
```

---

### Task 2: Rewire dashboard/fixtures/doc references to the new names + regression test

**Files:**
- Modify: `verenigingen/fixtures/dashboard.json` (chart link names)
- Modify: `verenigingen/verenigingen_payments/verenigingen_payments_dashboard/member_payment_development/member_payment_development.json` (chart link names)
- Modify: `verenigingen/hooks/fixtures.py:162-181` (Dashboard Chart export filter list)
- Modify: `docs/ADMIN_GUIDE.md` (lines ~234 and ~344-347, chart names)
- Create: `verenigingen/tests/test_payment_dashboard_charts.py` (regression test)

**Interfaces:**
- Consumes: the 5 chart docnames produced by Task 1.
- Produces: `get_permitted_charts("Member payment development")` returns 5 charts without raising.

- [ ] **Step 1: Write the failing regression test**

`verenigingen/tests/test_payment_dashboard_charts.py`:

```python
import frappe
from frappe.desk.doctype.dashboard.dashboard import get_permitted_charts
from frappe.tests.utils import FrappeTestCase


class TestPaymentDashboardCharts(FrappeTestCase):
    """Guards against dashboards referencing Dashboard Charts that do not exist.

    Regression for the production DoesNotExistError where the 'Member payment
    development' dashboard linked 5 charts that were never defined.
    """

    def test_verenigingen_dashboard_chart_links_resolve(self):
        for dashboard_name in ("Member payment development", "Member Analytics"):
            if not frappe.db.exists("Dashboard", dashboard_name):
                continue
            dashboard = frappe.get_doc("Dashboard", dashboard_name)
            for link in dashboard.charts:
                self.assertTrue(
                    frappe.db.exists("Dashboard Chart", link.chart),
                    f"Dashboard '{dashboard_name}' references missing chart '{link.chart}'",
                )

    def test_get_permitted_charts_does_not_raise(self):
        if not frappe.db.exists("Dashboard", "Member payment development"):
            self.skipTest("dashboard not installed on this site")
        charts = get_permitted_charts("Member payment development")
        self.assertEqual(len(charts), 5)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.test_payment_dashboard_charts`
Expected: FAIL — the dashboards still link the OLD names (`Monthly Revenue Trends`, etc.), so `test_verenigingen_dashboard_chart_links_resolve` fails on the missing old-named charts and `test_get_permitted_charts_does_not_raise` raises `DoesNotExistError`.

- [ ] **Step 3: Update the fixture dashboard chart links**

In `verenigingen/fixtures/dashboard.json`, replace the four old chart names inside the `charts` array (leave `SEPA Payment Status` and the `width` values unchanged):

```
"Monthly Revenue Trends"       -> "Monthly Dues Revenue"
"Outstanding Invoices by Month" -> "Outstanding Dues Invoices by Month"
"Revenue by Payment Status"    -> "Dues Revenue by Payment Status"
"Revenue by Quarter"           -> "Dues Revenue by Quarter"
```

- [ ] **Step 4: Update the standard dashboard chart links**

In `verenigingen/verenigingen_payments/verenigingen_payments_dashboard/member_payment_development/member_payment_development.json`, apply the identical four replacements inside its `charts` array.

- [ ] **Step 5: Update the fixtures export filter**

In `verenigingen/hooks/fixtures.py`, inside the `Dashboard Chart` filter list (the `"name","in",[...]` block around lines 162-181), apply the identical four replacements. Leave the other 7 chart names unchanged.

- [ ] **Step 6: Update ADMIN_GUIDE.md**

In `docs/ADMIN_GUIDE.md`:
- Line ~234: change `Monthly Revenue Trends, Outstanding Invoices by Month, Revenue by Payment Status` to `Monthly Dues Revenue, Outstanding Dues Invoices by Month, Dues Revenue by Payment Status`.
- Lines ~344-347: apply the identical four replacements in the bulleted chart list.

- [ ] **Step 7: Re-sync and run the test to verify it passes**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.test_payment_dashboard_charts
```
Expected: PASS — both tests green. `migrate` re-imports the fixture dashboard and re-syncs the standard dashboard with the new link names, so all links resolve and `get_permitted_charts` returns 5 charts.

- [ ] **Step 8: Confirm no dangling links remain in the DB**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org mariadb -N -e "
SELECT link.parent, link.chart
FROM \`tabDashboard Chart Link\` link
LEFT JOIN \`tabDashboard Chart\` c ON c.name = link.chart
WHERE c.name IS NULL;"
```
Expected: no rows (every chart link resolves to an existing chart).

- [ ] **Step 9: Commit**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/fixtures/dashboard.json \
        verenigingen/verenigingen_payments/verenigingen_payments_dashboard/member_payment_development/member_payment_development.json \
        verenigingen/hooks/fixtures.py \
        docs/ADMIN_GUIDE.md \
        verenigingen/tests/test_payment_dashboard_charts.py
git commit -m "fix(dashboard): rename dues charts + wire up Member payment development links

Renames the 4 Sales-Invoice charts to dues-scoped names and updates both
dashboard definitions, the fixtures export filter, and the admin guide so
every chart link resolves. Adds a regression test guarding against
dashboards referencing non-existent Dashboard Charts."
```

---

## Notes for the implementer

- **Production rollout:** deploying this branch + running `bench migrate` on production creates the 5 chart records and re-syncs the dashboards, resolving the existing dangling links. No manual data patch is needed.
- **Why migrate (not reload-doctype) for verification:** folder charts sync via `sync_all` and the fixture dashboard imports via `sync_fixtures`; both run inside `bench migrate`.
- **Do not** add the 5 charts to `verenigingen/fixtures/dashboard_chart.json` — folder charts are the single source of truth here; duplicating into fixtures re-introduces drift.
```
