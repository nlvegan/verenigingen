// Custom chart source for Member Age Distribution
frappe.dashboards.chart_sources['Member Age Distribution'] = {
	method: 'verenigingen.api.dashboard_charts.get_member_age_distribution_chart',
	filters: []
};
