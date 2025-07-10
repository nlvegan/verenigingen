frappe.pages['system-health-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'System Health Dashboard',
		single_column: true
	});

	// Add refresh button
	page.set_primary_action('Refresh', () => {
		frappe.system_health.load_dashboard();
	}, 'octicon octicon-sync');

	// Create dashboard
	frappe.system_health = new SystemHealthDashboard(page);
	frappe.system_health.load_dashboard();
};

class SystemHealthDashboard {
	constructor(page) {
		this.page = page;
		this.setup_page();
	}

	setup_page() {
		this.$container = $(`
			<div class="system-health-dashboard">
				<div class="row">
					<div class="col-md-12">
						<div class="health-status-section"></div>
					</div>
				</div>
				<div class="row mt-4">
					<div class="col-md-6">
						<div class="performance-metrics-section"></div>
					</div>
					<div class="col-md-6">
						<div class="optimization-suggestions-section"></div>
					</div>
				</div>
				<div class="row mt-4">
					<div class="col-md-12">
						<div class="database-stats-section"></div>
					</div>
				</div>
				<div class="row mt-4">
					<div class="col-md-12">
						<div class="api-performance-section"></div>
					</div>
				</div>
			</div>
		`).appendTo(this.page.main);
	}

	load_dashboard() {
		// Show loading
		frappe.show_progress('Loading', 0, 100, 'Please wait...');

		// Load all sections
		Promise.all([
			this.load_health_status(),
			this.load_performance_metrics(),
			this.load_optimization_suggestions(),
			this.load_database_stats(),
			this.load_api_performance()
		]).then(() => {
			frappe.hide_progress();
		}).catch(err => {
			frappe.hide_progress();
			frappe.msgprint({
				title: __('Error'),
				indicator: 'red',
				message: __('Failed to load dashboard data')
			});
		});
	}

	load_health_status() {
		return frappe.call({
			method: 'verenigingen.utils.performance_dashboard.get_system_health',
			callback: (r) => {
				if (r.message) {
					this.render_health_status(r.message);
				}
			}
		});
	}

	render_health_status(data) {
		const status_color = data.status === 'healthy' ? 'green' :
						   data.status === 'degraded' ? 'orange' : 'red';

		const status_icon = data.status === 'healthy' ? 'fa-check-circle' :
						   data.status === 'degraded' ? 'fa-exclamation-triangle' : 'fa-times-circle';

		let checks_html = '';
		for (let [check, result] of Object.entries(data.checks || {})) {
			const check_color = result.status === 'ok' ? 'green' :
							   result.status === 'slow' ? 'orange' : 'red';
			checks_html += `
				<div class="col-md-4 mb-3">
					<div class="card">
						<div class="card-body">
							<h6>${frappe.utils.to_title_case(check.replace('_', ' '))}</h6>
							<div class="text-${check_color}">
								<i class="fa fa-circle"></i> ${result.status.toUpperCase()}
								${result.response_time_ms !== undefined ?
		`<br><small>${result.response_time_ms.toFixed(2)}ms</small>` : ''}
							</div>
						</div>
					</div>
				</div>
			`;
		}

		this.$container.find('.health-status-section').html(`
			<div class="card">
				<div class="card-header">
					<h4>
						<i class="fa ${status_icon} text-${status_color}"></i>
						System Health: ${data.status.toUpperCase()}
					</h4>
					<small class="text-muted">Last checked: ${moment(data.timestamp).format('YYYY-MM-DD HH:mm:ss')}</small>
				</div>
				<div class="card-body">
					<div class="row">
						${checks_html}
					</div>
				</div>
			</div>
		`);
	}

	load_performance_metrics() {
		return frappe.call({
			method: 'verenigingen.utils.performance_dashboard.get_performance_dashboard',
			callback: (r) => {
				if (r.message) {
					this.render_performance_metrics(r.message);
				}
			}
		});
	}

	render_performance_metrics(data) {
		let metrics_html = '';

		// API Performance Summary
		if (data.api_performance && data.api_performance.endpoints) {
			for (let [endpoint, stats] of Object.entries(data.api_performance.endpoints)) {
				const perf_color = stats.avg_time_ms < 500 ? 'green' :
								  stats.avg_time_ms < 1000 ? 'orange' : 'red';
				metrics_html += `
					<tr>
						<td>${endpoint}</td>
						<td>${stats.call_count}</td>
						<td class="text-${perf_color}">${stats.avg_time_ms.toFixed(2)}ms</td>
						<td>${stats.success_rate.toFixed(1)}%</td>
					</tr>
				`;
			}
		}

		this.$container.find('.performance-metrics-section').html(`
			<div class="card">
				<div class="card-header">
					<h5>Performance Metrics (Last 24 Hours)</h5>
				</div>
				<div class="card-body">
					${metrics_html ? `
						<table class="table table-sm">
							<thead>
								<tr>
									<th>Endpoint</th>
									<th>Calls</th>
									<th>Avg Time</th>
									<th>Success Rate</th>
								</tr>
							</thead>
							<tbody>
								${metrics_html}
							</tbody>
						</table>
					` : '<p class="text-muted">No API activity in the last 24 hours</p>'}
				</div>
			</div>
		`);
	}

	load_optimization_suggestions() {
		return frappe.call({
			method: 'verenigingen.utils.performance_dashboard.get_optimization_suggestions',
			callback: (r) => {
				if (r.message) {
					this.render_optimization_suggestions(r.message);
				}
			}
		});
	}

	render_optimization_suggestions(data) {
		let suggestions_html = '';

		for (let [category, items] of Object.entries(data)) {
			if (items && items.length > 0) {
				suggestions_html += `
					<div class="mb-3">
						<h6>${frappe.utils.to_title_case(category.replace('_', ' '))}</h6>
						<ul class="small">
							${items.map(item => `<li>${item}</li>`).join('')}
						</ul>
					</div>
				`;
			}
		}

		this.$container.find('.optimization-suggestions-section').html(`
			<div class="card">
				<div class="card-header">
					<h5>Optimization Suggestions</h5>
				</div>
				<div class="card-body">
					${suggestions_html || '<p class="text-muted">No optimization suggestions at this time</p>'}
				</div>
			</div>
		`);
	}

	load_database_stats() {
		return frappe.call({
			method: 'verenigingen.utils.database_query_analyzer.get_table_statistics',
			callback: (r) => {
				if (r.message && r.message.success) {
					this.render_database_stats(r.message);
				}
			}
		});
	}

	render_database_stats(data) {
		let largest_tables = data.tables.slice(0, 10);

		let table_html = largest_tables.map(table => `
			<tr>
				<td>${table.table_name}</td>
				<td class="text-right">${frappe.utils.number_format(table.table_rows)}</td>
				<td class="text-right">${table.total_size_mb.toFixed(2)} MB</td>
				<td class="text-right">${table.index_ratio_percent.toFixed(1)}%</td>
			</tr>
		`).join('');

		this.$container.find('.database-stats-section').html(`
			<div class="card">
				<div class="card-header">
					<h5>Database Statistics</h5>
				</div>
				<div class="card-body">
					<div class="row mb-3">
						<div class="col-md-4">
							<strong>Total Tables:</strong> ${data.summary.total_tables}
						</div>
						<div class="col-md-4">
							<strong>Total Rows:</strong> ${frappe.utils.number_format(data.summary.total_rows)}
						</div>
						<div class="col-md-4">
							<strong>Total Size:</strong> ${data.summary.total_size_mb.toFixed(2)} MB
						</div>
					</div>
					<h6>Largest Tables</h6>
					<table class="table table-sm">
						<thead>
							<tr>
								<th>Table Name</th>
								<th class="text-right">Rows</th>
								<th class="text-right">Size</th>
								<th class="text-right">Index Coverage</th>
							</tr>
						</thead>
						<tbody>
							${table_html}
						</tbody>
					</table>
				</div>
			</div>
		`);
	}

	load_api_performance() {
		return frappe.call({
			method: 'verenigingen.utils.performance_dashboard.get_api_performance_summary',
			args: { hours: 24 },
			callback: (r) => {
				if (r.message) {
					this.render_api_performance(r.message);
				}
			}
		});
	}

	render_api_performance(data) {
		let content = '';

		if (data.endpoints && Object.keys(data.endpoints).length > 0) {
			// Create performance chart data
			let chart_data = {
				labels: [],
				datasets: [{
					name: 'Average Response Time (ms)',
					values: []
				}]
			};

			for (let [endpoint, stats] of Object.entries(data.endpoints)) {
				chart_data.labels.push(endpoint.substring(0, 30) + '...');
				chart_data.datasets[0].values.push(stats.avg_time_ms.toFixed(2));
			}

			content = `
				<div id="api-performance-chart" style="height: 300px;"></div>
				<script>
					new frappe.Chart("#api-performance-chart", {
						data: ${JSON.stringify(chart_data)},
						type: 'bar',
						height: 300,
						colors: ['#5e64ff']
					});
				</script>
			`;
		} else {
			content = '<p class="text-muted">No API performance data available</p>';
		}

		this.$container.find('.api-performance-section').html(`
			<div class="card">
				<div class="card-header">
					<h5>API Performance (Last 24 Hours)</h5>
				</div>
				<div class="card-body">
					${content}
				</div>
			</div>
		`);
	}
}
