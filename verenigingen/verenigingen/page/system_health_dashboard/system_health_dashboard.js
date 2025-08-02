/**
 * @fileoverview System Health Dashboard Page for Verenigingen Association Management
 *
 * This page provides a comprehensive system health monitoring dashboard that displays
 * real-time metrics, performance data, optimization suggestions, and business analytics
 * for the association management system.
 *
 * @description Business Context:
 * The System Health Dashboard serves as a central monitoring hub for system administrators
 * and technical stakeholders, providing visibility into:
 * - System health status with component-level monitoring
 * - Performance metrics and API response time analysis
 * - Database statistics and optimization opportunities
 * - Business metrics including membership dues schedule processing
 * - Real-time alerts and optimization suggestions
 * - Historical trend analysis for capacity planning
 *
 * @description Key Features:
 * - Real-time system health monitoring with color-coded status indicators
 * - API performance tracking with response time analytics
 * - Database table statistics and index coverage analysis
 * - Business metrics integration with dues schedule monitoring
 * - Optimization suggestions based on system analysis
 * - Interactive charts and visualizations using Frappe Charts
 * - Error handling with graceful degradation for failed components
 *
 * @description Integration Points:
 * - Performance monitoring utilities for system metrics collection
 * - Database query analyzer for table statistics and optimization
 * - Zabbix integration for business metrics and monitoring
 * - API audit logging for performance tracking
 * - Membership dues schedule system for business analytics
 * - Frappe Charts for data visualization and trending
 *
 * @description Technical Architecture:
 * - Modular dashboard sections with independent loading
 * - Promise-based asynchronous data loading with timeout protection
 * - Responsive Bootstrap grid layout for multi-device support
 * - Real-time data refresh capabilities with user-triggered updates
 * - Error boundary protection for individual dashboard components
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.ui
 * @requires frappe.call
 * @requires moment
 * @requires jQuery
 * @requires frappe.Chart
 *
 * @example
 * // Dashboard automatically loads when page is accessed:
 * // - System health checks with component status
 * // - Performance metrics with trend analysis
 * // - Database statistics with optimization recommendations
 * // - Business metrics with real-time dues schedule tracking
 */

// Updated to use the Membership Dues Schedule system.

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

/**
 * SystemHealthDashboard Class
 *
 * Manages the system health monitoring dashboard with comprehensive metrics display,
 * real-time data loading, and interactive visualization components for system
 * administration and operational monitoring.
 *
 * @description Dashboard Architecture:
 * The dashboard is organized into six main sections:
 * - Health Status: Component-level system health monitoring
 * - Performance Metrics: API response time and throughput analysis
 * - Optimization Suggestions: Automated recommendations for system improvements
 * - Database Statistics: Table size, row counts, and index coverage analysis
 * - Business Metrics: Membership dues schedule and invoice processing metrics
 * - API Performance: Real-time API endpoint performance visualization
 *
 * @description Data Loading Strategy:
 * - Asynchronous loading with individual error handling per section
 * - Timeout protection to prevent hanging load states
 * - Graceful degradation when individual components fail
 * - Progress indication with forced cleanup to prevent UI blocking
 * - Promise-based coordination for concurrent data loading
 *
 * @class
 */
class SystemHealthDashboard {
	/**
	 * Creates SystemHealthDashboard instance
	 *
	 * @param {Object} page - Frappe page instance for dashboard container
	 */
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
					<div class="col-md-6">
						<div class="business-metrics-section"></div>
					</div>
					<div class="col-md-6">
						<div class="api-performance-section"></div>
					</div>
				</div>
			</div>
		`).appendTo(this.page.main);
	}

	/**
	 * Forces Progress Dialog Cleanup
	 *
	 * Aggressively removes progress dialogs and modal backdrops that may persist
	 * after dashboard loading, ensuring clean UI state restoration.
	 *
	 * @description Cleanup Strategy:
	 * - Multiple fallback methods for different UI state scenarios
	 * - DOM manipulation for stuck modal elements
	 * - Frappe dialog state cleanup and reset
	 * - CSS state restoration for modal-open class conflicts
	 * - Progress element hiding with comprehensive selectors
	 *
	 * @description Implementation Notes:
	 * - Uses multiple timeout-delayed cleanup phases
	 * - Comprehensive element selection for thorough cleanup
	 * - Console logging for debugging persistent UI issues
	 * - CSS overflow restoration for body scroll functionality
	 */
	force_hide_progress() {
		console.log('Attempting to force hide progress dialog...');

		// Debug: Check what elements are present
		console.log('Modal elements found:', {
			'progress-modal': $('.progress-modal').length,
			'modal-backdrop': $('.modal-backdrop').length,
			'modal': $('.modal').length,
			'modal-open': $('body').hasClass('modal-open'),
			'frappe-modal': $('.frappe-modal').length
		});

		// Try multiple approaches to hide progress - WITHOUT the nuclear option
		try {
			// Method 1: Standard frappe.hide_progress()
			frappe.hide_progress();
			console.log('Called frappe.hide_progress()');

			// Method 2: Targeted DOM manipulation - only progress-related elements
			setTimeout(() => {
				// Only remove progress-specific elements
				$('.progress-modal').remove();
				$('.modal-backdrop').remove();
				$('body').removeClass('modal-open');

				// Force remove any remaining backdrops
				$('.modal-backdrop').each(function() {
					$(this).remove();
				});

				// Reset any CSS that might be blocking
				$('body').css('overflow', 'auto');
				$('html').css('overflow', 'auto');
				$('body').removeClass('modal-open');

				console.log('Removed progress modal elements via DOM manipulation');

				// Check if backdrop is still there
				console.log('After removal - modal-backdrop count:', $('.modal-backdrop').length);
			}, 100);

			// Method 3: Force close frappe dialogs
			setTimeout(() => {
				if (frappe.cur_dialog) {
					frappe.cur_dialog.hide();
					console.log('Closed current dialog');
				}

				// Clear any progress state
				if (frappe.freeze_count) {
					frappe.freeze_count = 0;
				}

				console.log('Closed dialogs and reset state');
			}, 200);

			// Method 4: Final cleanup - extra aggressive backdrop removal
			setTimeout(() => {
				// Remove backdrop more aggressively
				$('.modal-backdrop').remove();
				$('body').removeClass('modal-open');

				// Force hide any visible progress elements
				$('[class*="progress"]').filter(function() {
					return $(this).is(':visible');
				}).hide();

				// Target specific progress dialog elements that might persist
				$('.progress-area, .progress-bar, .progress-message').hide();
				$('div:contains("Loading")').filter(function() {
					return $(this).text().trim() === 'Loading';
				}).hide();
				$('div:contains("Please wait")').filter(function() {
					return $(this).text().includes('Please wait');
				}).hide();

				// Final check
				console.log('Final cleanup - modal-backdrop count:', $('.modal-backdrop').length);
				console.log('Final cleanup - body modal-open:', $('body').hasClass('modal-open'));
			}, 500);

		} catch (e) {
			console.error('Error hiding progress:', e);
		}
	}

	load_dashboard() {
		// Show loading
		frappe.show_progress('Loading', 0, 100, 'Please wait...');

		// Add timeout to ensure loading message doesn't hang
		const timeout = new Promise((resolve) => {
			setTimeout(() => {
				console.log('Dashboard loading timeout reached');
				resolve(null);
			}, 30000); // 30 second timeout
		});

		// Load all sections with individual error handling and detailed logging
		console.log('Starting dashboard load...');

		const healthPromise = this.load_health_status().then(r => {
			console.log('Health status loaded');
			return r;
		}).catch(err => {
			console.error('Error loading health status:', err);
			return null;
		});

		const performancePromise = this.load_performance_metrics().then(r => {
			console.log('Performance metrics loaded');
			return r;
		}).catch(err => {
			console.error('Error loading performance metrics:', err);
			return null;
		});

		const optimizationPromise = this.load_optimization_suggestions().then(r => {
			console.log('Optimization suggestions loaded');
			return r;
		}).catch(err => {
			console.error('Error loading optimization suggestions:', err);
			return null;
		});

		const databasePromise = this.load_database_stats().then(r => {
			console.log('Database stats loaded');
			return r;
		}).catch(err => {
			console.error('Error loading database stats:', err);
			return null;
		});

		const businessPromise = this.load_business_metrics().then(r => {
			console.log('Business metrics loaded');
			return r;
		}).catch(err => {
			console.error('Error loading business metrics:', err);
			return null;
		});

		const apiPromise = this.load_api_performance().then(r => {
			console.log('API performance loaded');
			return r;
		}).catch(err => {
			console.error('Error loading API performance:', err);
			return null;
		});

		Promise.race([
			Promise.all([
				healthPromise,
				performancePromise,
				optimizationPromise,
				databasePromise,
				businessPromise,
				apiPromise
			]).then(() => {
				console.log('All dashboard sections loaded successfully');
			}),
			timeout
		]).then(() => {
			console.log('Dashboard loading complete, hiding progress...');
			this.force_hide_progress();
		}).catch(err => {
			console.log('Dashboard loading failed, hiding progress...');
			this.force_hide_progress();
			console.error('Dashboard loading error:', err);
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
			},
			error: (r) => {
				console.error('Health status error:', r);
				// Show empty section with error message
				this.$container.find('.health-status-section').html(`
					<div class="alert alert-danger">
						<strong>Error loading health status:</strong> ${r.message || 'Unknown error'}
					</div>
				`);
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
							   result.status === 'warning' ? 'orange' :
							   result.status === 'slow' ? 'orange' : 'red';

			let details = '';
			if (result.response_time_ms !== undefined) {
				details += `<br><small>${result.response_time_ms.toFixed(2)}ms</small>`;
			}
			if (result.message) {
				details += `<br><small class="text-muted">${result.message}</small>`;
			}

			// Updated to use dues schedule system
			if (check === 'dues_schedule_processing' && result.active_dues_schedules !== undefined) {
				details += `<br><small>Active: ${result.active_dues_schedules}, Today: ${result.invoices_today}</small>`;
			}
			if (check === 'scheduler' && result.stuck_jobs !== undefined) {
				details += `<br><small>Stuck: ${result.stuck_jobs}, Recent: ${result.recent_activity}</small>`;
			}

			checks_html += `
				<div class="col-md-4 mb-3">
					<div class="card">
						<div class="card-body">
							<h6>${frappe.utils.to_title_case(check.replace('_', ' '))}</h6>
							<div class="text-${check_color}">
								<i class="fa fa-circle"></i> ${result.status.toUpperCase()}
								${details}
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
				<td class="text-right">${table.table_rows.toLocaleString()}</td>
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
							<strong>Total Rows:</strong> ${data.summary.total_rows.toLocaleString()}
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

	load_business_metrics() {
		return frappe.call({
			method: 'verenigingen.monitoring.zabbix_integration.get_metrics_for_zabbix',
			callback: (r) => {
				if (r.message && r.message.metrics) {
					this.render_business_metrics(r.message.metrics);
				}
			},
			error: (r) => {
				console.error('Business metrics error:', r);
				// Show empty section with error message
				this.$container.find('.business-metrics-section').html(`
					<div class="card">
						<div class="card-header">
							<h5>Business & System Metrics</h5>
						</div>
						<div class="card-body">
							<div class="alert alert-danger">
								<strong>Error loading business metrics:</strong> ${r.message || 'Unknown error'}
							</div>
						</div>
					</div>
				`);
			}
		});
	}

	render_business_metrics(metrics) {
		const businessMetrics = [
			{
				label: 'Active Subscriptions',
				value: metrics.active_dues_schedules || 0,
				color: 'blue'
			},
			{
				label: 'Sales Invoices Today',
				value: metrics.sales_invoices_today || 0,
				color: 'green'
			},
			{
				label: 'Subscription Invoices Today',
				value: metrics.dues_schedule_invoices_today || 0,
				color: 'orange'
			},
			{
				label: 'Total Invoices Today',
				value: metrics.total_invoices_today || 0,
				color: 'purple'
			},
			{
				label: 'Hours Since Last Subscription Run',
				value: metrics.last_dues_schedule_run || 0,
				color: metrics.last_dues_schedule_run > 25 ? 'red' : metrics.last_dues_schedule_run > 4 ? 'orange' : 'green'
			},
			{
				label: 'Stuck Scheduler Jobs',
				value: metrics.stuck_jobs || 0,
				color: metrics.stuck_jobs > 0 ? 'red' : 'green'
			}
		];

		let metrics_html = businessMetrics.map(metric => `
			<div class="col-md-6 mb-3">
				<div class="card">
					<div class="card-body text-center">
						<h3 class="text-${metric.color}">${metric.value}</h3>
						<p class="mb-0 small">${metric.label}</p>
					</div>
				</div>
			</div>
		`).join('');

		this.$container.find('.business-metrics-section').html(`
			<div class="card">
				<div class="card-header">
					<h5>Business & System Metrics</h5>
					<small class="text-muted">Real-time dues schedule and invoice tracking</small>
				</div>
				<div class="card-body">
					<div class="row">
						${metrics_html}
					</div>
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
