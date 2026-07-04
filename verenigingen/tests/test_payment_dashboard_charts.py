import frappe
from frappe.desk.doctype.dashboard.dashboard import get_permitted_charts
from frappe.tests.utils import FrappeTestCase

# The dashboard whose chart links caused the production DoesNotExistError.
PAYMENT_DASHBOARD = "Member payment development"


class TestPaymentDashboardCharts(FrappeTestCase):
    """Guards against dashboards referencing Dashboard Charts that do not exist.

    Regression for the production DoesNotExistError where the 'Member payment
    development' dashboard linked 4 charts (of its 5) that were never defined.
    """

    def test_verenigingen_dashboard_chart_links_resolve(self):
        # The payment dashboard ships as a fixture; its absence means the
        # fixtures failed to install -- fail loudly rather than skip silently.
        self.assertTrue(
            frappe.db.exists("Dashboard", PAYMENT_DASHBOARD),
            f"Fixture dashboard '{PAYMENT_DASHBOARD}' is not installed",
        )
        for dashboard_name in (PAYMENT_DASHBOARD, "Member Analytics"):
            if not frappe.db.exists("Dashboard", dashboard_name):
                continue
            dashboard = frappe.get_doc("Dashboard", dashboard_name)
            for link in dashboard.charts:
                self.assertTrue(
                    frappe.db.exists("Dashboard Chart", link.chart),
                    f"Dashboard '{dashboard_name}' references missing chart '{link.chart}'",
                )

    def test_get_permitted_charts_all_resolve(self):
        # get_permitted_charts is the exact function that raised in production.
        # Under the Administrator test session has_permission short-circuits to
        # True without loading the chart, so assert each returned chart actually
        # exists rather than merely counting the links (which never changed).
        charts = get_permitted_charts(PAYMENT_DASHBOARD)
        self.assertTrue(charts, "no permitted charts returned")
        for chart in charts:
            self.assertTrue(
                frappe.db.exists("Dashboard Chart", chart.chart),
                f"get_permitted_charts returned missing chart '{chart.chart}'",
            )
