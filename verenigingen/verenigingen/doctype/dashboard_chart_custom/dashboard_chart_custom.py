"""Custom Dashboard Chart Extensions for Verenigingen"""

import frappe
from frappe.desk.doctype.dashboard_chart.dashboard_chart import DashboardChart


class DashboardChartCustom(DashboardChart):
    """Extended Dashboard Chart with custom sources"""

    def get_chart_data(self):
        """Override to handle custom chart sources"""
        if self.chart_type == "Custom" and self.source == "Member Age Distribution":
            from verenigingen.config.dashboard_charts import get_member_age_distribution

            return get_member_age_distribution()

        # Fall back to parent implementation for other charts
        return super().get_chart_data()
