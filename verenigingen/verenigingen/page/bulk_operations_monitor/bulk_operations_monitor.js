/**
 * Bulk Operations Monitoring Dashboard
 * ===================================
 *
 * Real-time monitoring interface for bulk account creation operations.
 * Provides administrators with comprehensive visibility into performance metrics,
 * queue status, and system health for large-scale member imports.
 */

frappe.pages['bulk-operations-monitor'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Bulk Operations Monitor',
		single_column: true
	});

	// Initialize dashboard
	frappe.bulk_operations_monitor = new BulkOperationsMonitor(page);
}

class BulkOperationsMonitor {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);

		this.setup_layout();
		this.setup_refresh_controls();
		this.load_dashboard_data();

		// Auto-refresh every 30 seconds
		this.refresh_interval = setInterval(() => {
			this.load_dashboard_data();
		}, 30000);
	}

	setup_layout() {
		this.wrapper.html(`
			<div class="bulk-monitor-dashboard">
				<div class="row">
					<div class="col-md-8">
						<div class="card">
							<div class="card-header">
								<h5><i class="fa fa-chart-line"></i> Performance Metrics</h5>
							</div>
							<div class="card-body" id="performance-metrics">
								<div class="text-center">
									<i class="fa fa-spinner fa-spin"></i> Loading metrics...
								</div>
							</div>
						</div>
					</div>
					<div class="col-md-4">
						<div class="card">
							<div class="card-header">
								<h5><i class="fa fa-server"></i> Queue Status</h5>
							</div>
							<div class="card-body" id="queue-status">
								<div class="text-center">
									<i class="fa fa-spinner fa-spin"></i> Loading queues...
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="row mt-4">
					<div class="col-md-6">
						<div class="card">
							<div class="card-header">
								<h5><i class="fa fa-exclamation-triangle"></i> Active Alerts</h5>
							</div>
							<div class="card-body" id="active-alerts">
								<div class="text-center">
									<i class="fa fa-spinner fa-spin"></i> Loading alerts...
								</div>
							</div>
						</div>
					</div>
					<div class="col-md-6">
						<div class="card">
							<div class="card-header">
								<h5><i class="fa fa-list"></i> Recent Operations</h5>
							</div>
							<div class="card-body" id="recent-operations">
								<div class="text-center">
									<i class="fa fa-spinner fa-spin"></i> Loading operations...
								</div>
							</div>
						</div>
					</div>
				</div>

				<div class="row mt-4">
					<div class="col-md-12">
						<div class="card">
							<div class="card-header">
								<h5><i class="fa fa-redo"></i> Retry Queue Status</h5>
							</div>
							<div class="card-body" id="retry-queues">
								<div class="text-center">
									<i class="fa fa-spinner fa-spin"></i> Loading retry queues...
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		`);
	}

	setup_refresh_controls() {
		this.page.add_button('Refresh', () => {
			this.load_dashboard_data();
		}, 'fa fa-refresh');

		this.page.add_button('Clear Stuck Jobs', () => {
			this.clear_stuck_jobs();
		}, 'fa fa-broom');

		this.page.add_button('Performance Report', () => {
			this.generate_performance_report();
		}, 'fa fa-chart-bar');
	}

	async load_dashboard_data() {
		try {
			// Load performance metrics
			const performance_data = await frappe.call({
				method: 'verenigingen.utils.bulk_performance_monitor.get_performance_dashboard_data'
			});

			this.render_performance_metrics(performance_data.message);

			// Load retry queue status
			const retry_data = await frappe.call({
				method: 'verenigingen.utils.bulk_retry_processor.get_retry_queue_status'
			});

			this.render_retry_queues(retry_data.message);

		} catch (error) {
			console.error('Failed to load dashboard data:', error);
			frappe.msgprint('Failed to load dashboard data. Please check console for details.');
		}
	}

	render_performance_metrics(data) {
		if (!data.success) {
			$('#performance-metrics').html(`
				<div class="alert alert-danger">
					<i class="fa fa-exclamation-circle"></i>
					Failed to load performance data: ${data.error || 'Unknown error'}
				</div>
			`);
			return;
		}

		const metrics = data.performance_metrics || {};
		const alerts = data.alerts || [];
		const queue_status = data.queue_status || {};

		// Render performance metrics
		$('#performance-metrics').html(`
			<div class="row">
				<div class="col-md-3">
					<div class="metric-box text-center">
						<h4 class="text-primary">${metrics.total_operations || 0}</h4>
						<small class="text-muted">Total Operations (7 days)</small>
					</div>
				</div>
				<div class="col-md-3">
					<div class="metric-box text-center">
						<h4 class="text-success">${metrics.success_rate_percentage || 0}%</h4>
						<small class="text-muted">Success Rate</small>
					</div>
				</div>
				<div class="col-md-3">
					<div class="metric-box text-center">
						<h4 class="text-info">${metrics.average_processing_rate || 0}/min</h4>
						<small class="text-muted">Processing Rate</small>
					</div>
				</div>
				<div class="col-md-3">
					<div class="metric-box text-center">
						<h4 class="text-warning">${(metrics.average_completion_time_hours || 0).toFixed(1)}h</h4>
						<small class="text-muted">Avg Completion Time</small>
					</div>
				</div>
			</div>
		`);

		// Render queue status
		$('#queue-status').html(`
			<div class="queue-info">
				<div class="d-flex justify-content-between">
					<span>Bulk Queue Length:</span>
					<span class="badge badge-${queue_status.length > 20 ? 'danger' : 'success'}">
						${queue_status.length || 0}
					</span>
				</div>
				<div class="d-flex justify-content-between mt-2">
					<span>Active Workers:</span>
					<span class="badge badge-${queue_status.workers > 0 ? 'success' : 'danger'}">
						${queue_status.workers || 0}
					</span>
				</div>
				<div class="d-flex justify-content-between mt-2">
					<span>Failed Jobs:</span>
					<span class="badge badge-${queue_status.failed_count > 0 ? 'danger' : 'success'}">
						${queue_status.failed_count || 0}
					</span>
				</div>
			</div>
		`);

		// Render alerts
		this.render_alerts(alerts);

		// Render recent operations
		this.render_recent_operations(metrics.recent_operations || []);
	}

	render_alerts(alerts) {
		if (!alerts.length) {
			$('#active-alerts').html(`
				<div class="text-center text-success">
					<i class="fa fa-check-circle fa-2x"></i>
					<p class="mt-2">No active alerts</p>
				</div>
			`);
			return;
		}

		const alert_html = alerts.map(alert => `
			<div class="alert alert-${this.get_alert_class(alert.severity)} alert-sm">
				<strong>${alert.type.replace('_', ' ').toUpperCase()}:</strong>
				${alert.message}
			</div>
		`).join('');

		$('#active-alerts').html(alert_html);
	}

	render_recent_operations(operations) {
		if (!operations.length) {
			$('#recent-operations').html(`
				<div class="text-center text-muted">
					<i class="fa fa-inbox fa-2x"></i>
					<p class="mt-2">No recent operations</p>
				</div>
			`);
			return;
		}

		const operations_html = operations.map(op => `
			<div class="operation-item border-bottom pb-2 mb-2">
				<div class="d-flex justify-content-between">
					<strong>${op.name}</strong>
					<span class="badge badge-${this.get_status_class(op.status)}">${op.status}</span>
				</div>
				<small class="text-muted">
					${op.successful}/${op.records} completed (${op.progress_percentage}%)
					${op.failed > 0 ? ` • ${op.failed} failed` : ''}
				</small>
			</div>
		`).join('');

		$('#recent-operations').html(operations_html);
	}

	render_retry_queues(retry_queues) {
		if (!retry_queues.length) {
			$('#retry-queues').html(`
				<div class="text-center text-success">
					<i class="fa fa-check-circle fa-2x"></i>
					<p class="mt-2">No retry queues</p>
				</div>
			`);
			return;
		}

		const table_html = `
			<div class="table-responsive">
				<table class="table table-sm">
					<thead>
						<tr>
							<th>Tracker</th>
							<th>Type</th>
							<th>Retry Count</th>
							<th>Should Retry</th>
							<th>Age (hours)</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						${retry_queues.map(queue => `
							<tr>
								<td>${queue.tracker_name}</td>
								<td>${queue.operation_type}</td>
								<td>${queue.retry_queue_count}</td>
								<td>
									<span class="badge badge-${queue.should_retry ? 'warning' : 'secondary'}">
										${queue.should_retry ? 'Yes' : 'No'}
									</span>
								</td>
								<td>${queue.age_hours.toFixed(1)}</td>
								<td>
									<button class="btn btn-sm btn-primary" onclick="frappe.bulk_operations_monitor.retry_tracker('${queue.tracker_name}')">
										Retry Now
									</button>
								</td>
							</tr>
						`).join('')}
					</tbody>
				</table>
			</div>
		`;

		$('#retry-queues').html(table_html);
	}

	get_alert_class(severity) {
		const classes = {
			'error': 'danger',
			'critical': 'danger',
			'warning': 'warning',
			'info': 'info'
		};
		return classes[severity] || 'secondary';
	}

	get_status_class(status) {
		const classes = {
			'Completed': 'success',
			'Processing': 'info',
			'Failed': 'danger',
			'Pending': 'warning'
		};
		return classes[status] || 'secondary';
	}

	async clear_stuck_jobs() {
		frappe.confirm('Are you sure you want to clear stuck jobs? This will remove jobs that have been running too long.', () => {
			frappe.call({
				method: 'verenigingen.utils.bulk_queue_config.clear_stuck_jobs',
				callback: (r) => {
					if (r.message && r.message.success) {
						frappe.msgprint(`Cleared ${r.message.cleared_jobs.length} stuck jobs`);
						this.load_dashboard_data();
					}
				}
			});
		});
	}

	async retry_tracker(tracker_name) {
		frappe.confirm(`Retry failed requests for ${tracker_name}?`, () => {
			frappe.call({
				method: 'verenigingen.utils.bulk_retry_processor.manual_retry_failed_requests',
				args: { tracker_name },
				callback: (r) => {
					if (r.message) {
						frappe.msgprint(`Retry completed: ${r.message.succeeded} succeeded, ${r.message.failed} failed`);
						this.load_dashboard_data();
					}
				}
			});
		});
	}

	generate_performance_report() {
		frappe.set_route('query-report', 'Bulk Operations Performance Report');
	}
}
