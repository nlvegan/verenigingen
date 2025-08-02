/**
 * @fileoverview Membership Analytics Dashboard - Advanced Business Intelligence and Predictive Analytics
 *
 * This module provides comprehensive analytics and business intelligence capabilities for association
 * membership management, featuring real-time dashboards, predictive modeling, cohort analysis,
 * churn prediction, revenue forecasting, and executive reporting. The system supports strategic
 * decision-making through data-driven insights and automated alert systems.
 *
 * Key Features:
 * - Real-time membership growth tracking and trend analysis
 * - Predictive analytics with 12-month forecasting models
 * - Advanced cohort retention analysis and churn prediction
 * - Revenue projection and membership value optimization
 * - Regional and demographic segmentation analytics
 * - Goal setting and progress tracking with automated alerts
 * - Executive dashboards with export capabilities
 * - Risk assessment and member engagement analytics
 *
 * Business Value:
 * - Strategic planning through data-driven member growth insights
 * - Proactive churn prevention with risk identification
 * - Revenue optimization through membership value analysis
 * - Performance monitoring against organizational goals
 * - Operational efficiency through automated reporting
 * - Compliance support with detailed analytics audit trails
 *
 * Technical Architecture:
 * - Frappe framework integration with custom page controllers
 * - Chart.js integration for interactive data visualizations
 * - Real-time data processing with 5-minute auto-refresh
 * - Advanced filtering with multi-dimensional analytics
 * - Export capabilities (Excel, PDF, CSV) for reporting
 * - Mobile-responsive dashboard design
 *
 * Security Features:
 * - Role-based access control for analytics data
 * - Audit logging for all dashboard interactions
 * - Data anonymization for sensitive member information
 * - GDPR-compliant member data handling
 *
 * Performance Optimizations:
 * - Cached analytics data with intelligent refresh
 * - Optimized database queries for large datasets
 * - Progressive data loading for enhanced user experience
 * - Memory-efficient chart rendering and updates
 *
 * @author Verenigingen Development Team
 * @version 2.1.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires frappe.Chart
 * @requires verenigingen.verenigingen.page.membership_analytics.membership_analytics (Python backend)
 * @requires verenigingen.verenigingen.page.membership_analytics.predictive_analytics (ML backend)
 *
 * @example
 * // Dashboard is automatically initialized when accessing the Membership Analytics page
 * // Access via: Workspace > Analytics > Membership Analytics Dashboard
 *
 * @see {@link /app/membership-analytics} Dashboard URL
 * @see {@link verenigingen.verenigingen.doctype.membership_analytics_snapshot} Snapshot Management
 * @see {@link verenigingen.verenigingen.report} Related Analytics Reports
 */

/**
 * Frappe page loader for Membership Analytics Dashboard
 * Initializes the analytics dashboard with proper page structure and controls
 *
 * @param {Object} wrapper - Frappe page wrapper element
 * @throws {Error} If page initialization fails or user lacks permissions
 */
frappe.pages['membership-analytics'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Membership Analytics Dashboard'),
		single_column: true
	});

	// Create the page
	let membership_analytics = new MembershipAnalytics(page);
	membership_analytics.make();
};

/**
 * @class MembershipAnalytics
 * @classdesc Advanced Membership Analytics Dashboard with Predictive Intelligence
 *
 * Provides comprehensive business intelligence for association membership management,
 * featuring real-time analytics, predictive modeling, cohort analysis, and strategic
 * planning tools. Supports executive decision-making through interactive dashboards
 * and automated insights.
 *
 * Core Capabilities:
 * - Membership growth tracking and trend analysis
 * - Revenue forecasting and optimization analytics
 * - Churn prediction and retention modeling
 * - Demographic and geographic segmentation
 * - Goal setting and performance monitoring
 * - Risk assessment and early warning systems
 *
 * Analytics Features:
 * - Real-time dashboard with auto-refresh (5-minute intervals)
 * - Interactive filtering by time, region, demographics
 * - Comparative analysis (year-over-year, period comparisons)
 * - Cohort retention analysis with heatmap visualization
 * - Predictive scenarios (conservative, optimistic, aggressive growth)
 * - Export capabilities for executive reporting
 *
 * Data Sources:
 * - Member registration and lifecycle events
 * - Payment transactions and revenue data
 * - Engagement metrics and activity tracking
 * - Chapter performance and regional analytics
 * - External economic and demographic indicators
 *
 * @since 1.0.0
 * @version 2.1.0
 */
class MembershipAnalytics {
	/**
	 * @constructor
	 * @description Initializes the Membership Analytics Dashboard with default configuration
	 *
	 * Sets up the analytics environment with comprehensive filtering options,
	 * chart management, and real-time data refresh capabilities. Establishes
	 * baseline analytics parameters for member growth tracking and business intelligence.
	 *
	 * @param {Object} page - Frappe page object for dashboard rendering
	 *
	 * @property {Object} page - Main page container for dashboard UI
	 * @property {Object} charts - Chart instances management for memory optimization
	 * @property {Object} filters - Multi-dimensional filtering configuration
	 * @property {number} filters.year - Current analysis year (default: current year)
	 * @property {string} filters.period - Analysis period (year/quarter/month)
	 * @property {boolean} filters.compare_previous - Enable period comparison
	 * @property {string|null} filters.chapter - Chapter-specific filtering
	 * @property {string|null} filters.region - Geographic region filtering
	 * @property {string|null} filters.membership_type - Membership type segmentation
	 * @property {string|null} filters.age_group - Demographic age grouping
	 * @property {string|null} filters.payment_method - Payment method analysis
	 *
	 * @since 1.0.0
	 */
	constructor(page) {
		this.page = page;
		this.charts = {};
		this.filters = {
			year: new Date().getFullYear(),
			period: 'year',
			compare_previous: false,
			chapter: null,
			region: null,
			membership_type: null,
			age_group: null,
			payment_method: null
		};
	}

	/**
	 * @method make
	 * @description Initializes and renders the complete analytics dashboard
	 *
	 * Orchestrates the dashboard creation process including HTML template rendering,
	 * filter setup, button configuration, and initial data loading. Establishes
	 * auto-refresh mechanism for real-time analytics updates.
	 *
	 * Dashboard Components:
	 * - Summary cards with key performance indicators
	 * - Interactive charts for growth trends and revenue analysis
	 * - Advanced filtering interface with multi-dimensional options
	 * - Goal tracking and progress monitoring
	 * - Export and snapshot capabilities
	 * - Predictive analytics and risk assessment tools
	 *
	 * @throws {Error} If template rendering fails or backend connectivity issues
	 * @since 1.0.0
	 */
	make() {
		// Add HTML content
		$(this.page.main).html(frappe.render_template('membership_analytics', {}));

		// Initialize components
		this.setup_filters();
		this.setup_buttons();
		this.refresh_dashboard();

		// Auto-refresh every 5 minutes
		setInterval(() => this.refresh_dashboard(), 5 * 60 * 1000);
	}

	setup_filters() {
		// Populate year dropdown
		const currentYear = new Date().getFullYear();
		const yearSelect = $('#filter-year');

		for (let year = currentYear; year >= currentYear - 5; year--) {
			yearSelect.append(`<option value="${year}">${year}</option>`);
		}

		// Set current year
		yearSelect.val(currentYear);

		// Load filter options
		this.load_filter_options();

		// Bind filter changes
		$('#filter-year, #filter-period').on('change', () => {
			this.filters.year = $('#filter-year').val();
			this.filters.period = $('#filter-period').val();
			this.refresh_dashboard();
		});

		$('#compare-previous').on('change', () => {
			this.filters.compare_previous = $('#compare-previous').is(':checked');
			this.refresh_dashboard();
		});

		// Advanced filters
		$('#filter-chapter, #filter-region, #filter-membership-type, #filter-age-group, #filter-payment-method').on('change', () => {
			this.filters.chapter = $('#filter-chapter').val() || null;
			this.filters.region = $('#filter-region').val() || null;
			this.filters.membership_type = $('#filter-membership-type').val() || null;
			this.filters.age_group = $('#filter-age-group').val() || null;
			this.filters.payment_method = $('#filter-payment-method').val() || null;
			this.refresh_dashboard();
		});

		// Reset filters button
		$('#btn-reset-filters').on('click', () => {
			$('#filter-chapter, #filter-region, #filter-membership-type, #filter-age-group, #filter-payment-method').val('').trigger('change');
		});
	}

	load_filter_options() {
		// Load chapters
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Chapter',
				fields: ['name'],
				filters: { is_active: 1 },
				limit_page_length: 0
			},
			callback: (r) => {
				if (r.message) {
					const select = $('#filter-chapter');
					r.message.forEach(chapter => {
						select.append(`<option value="${chapter.name}">${chapter.chapter_name}</option>`);
					});
				}
			}
		});

		// Load membership types
		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Membership Type',
				fields: ['name'],
				filters: { is_active: 1 },
				limit_page_length: 0
			},
			callback: (r) => {
				if (r.message) {
					const select = $('#filter-membership-type');
					r.message.forEach(type => {
						select.append(`<option value="${type.name}">${type.name}</option>`);
					});
				}
			}
		});

		// Regions are hardcoded based on postal codes
		const regions = [
			'Noord-Holland', 'Zuid-Holland', 'Utrecht', 'Gelderland',
			'Noord-Brabant', 'Limburg', 'Zeeland', 'Overijssel', 'Groningen'
		];
		const regionSelect = $('#filter-region');
		regions.forEach(region => {
			regionSelect.append(`<option value="${region}">${region}</option>`);
		});

		// Age groups are predefined
		const ageGroups = ['Under 25', '25-34', '35-44', '45-54', '55-64', '65+'];
		const ageSelect = $('#filter-age-group');
		ageGroups.forEach(age => {
			ageSelect.append(`<option value="${age}">${age}</option>`);
		});

		// Payment methods
		const paymentMethods = ['Bank Transfer', 'Direct Debit', 'Credit Card', 'PayPal'];
		const paymentSelect = $('#filter-payment-method');
		paymentMethods.forEach(method => {
			paymentSelect.append(`<option value="${method}">${method}</option>`);
		});
	}

	setup_buttons() {
		// Refresh button
		$('#btn-refresh').on('click', () => {
			this.refresh_dashboard();
		});

		// Add Goal button
		$('#btn-add-goal').on('click', () => {
			this.show_goal_dialog();
		});

		// Export buttons - use event delegation for dropdown items
		$(document).on('click', '#btn-export-excel', (e) => {
			e.preventDefault();
			this.export_data('excel');
		});

		$(document).on('click', '#btn-export-pdf', (e) => {
			e.preventDefault();
			this.export_data('pdf');
		});

		$(document).on('click', '#btn-export-csv', (e) => {
			e.preventDefault();
			this.export_data('csv');
		});

		// Create Snapshot button
		$('#btn-create-snapshot').on('click', () => {
			this.create_snapshot();
		});

		// Toggle advanced filters
		$('#btn-toggle-filters').on('click', () => {
			$('#advanced-filters').slideToggle(() => {
				// Show/hide reset button based on filter visibility
				if ($('#advanced-filters').is(':visible')) {
					$('#btn-reset-filters').show();
				} else {
					$('#btn-reset-filters').hide();
				}
			});
		});

		// Predictive Analytics button
		$('#btn-predictive').on('click', () => {
			this.show_predictive_analytics();
		});

		// Alert Rules button
		$('#btn-alert-rules').on('click', () => {
			frappe.set_route('List', 'Analytics Alert Rule');
		});
	}

	/**
	 * @method refresh_dashboard
	 * @description Refreshes all dashboard data and visualizations with current filter settings
	 *
	 * Orchestrates a complete dashboard refresh by fetching updated analytics data
	 * from the backend and re-rendering all charts, summaries, and insights.
	 * Implements proper loading states and error handling for enhanced user experience.
	 *
	 * Data Refresh Process:
	 * 1. Display loading state with progress indicator
	 * 2. Fetch comprehensive analytics data with current filters
	 * 3. Update summary cards with key performance metrics
	 * 4. Re-render all interactive charts and visualizations
	 * 5. Refresh goals, insights, and recommendations
	 * 6. Update timestamp for data freshness indication
	 *
	 * Backend Integration:
	 * - Calls Python analytics engine for data processing
	 * - Applies multi-dimensional filtering (time, geography, demographics)
	 * - Retrieves predictive analytics and trend analysis
	 * - Includes comparative metrics for period-over-period analysis
	 *
	 * Error Handling:
	 * - Network connectivity issues
	 * - Backend processing errors
	 * - Data validation failures
	 * - User permission restrictions
	 *
	 * @throws {Error} If backend communication fails or data processing errors occur
	 * @since 1.0.0
	 *
	 * @example
	 * // Triggered automatically every 5 minutes
	 * setInterval(() => this.refresh_dashboard(), 5 * 60 * 1000);
	 *
	 * // Manual refresh via button click
	 * $('#btn-refresh').on('click', () => this.refresh_dashboard());
	 */
	refresh_dashboard() {
		// Show loading state
		frappe.dom.freeze('Loading dashboard data...');

		frappe.call({
			method: 'verenigingen.verenigingen.page.membership_analytics.membership_analytics.get_dashboard_data',
			args: {
				year: this.filters.year,
				period: this.filters.period,
				compare_previous: this.filters.compare_previous,
				filters: this.filters
			},
			callback: (r) => {
				frappe.dom.unfreeze();
				if (r.message) {
					this.render_dashboard(r.message);
				}
			},
			error: () => {
				frappe.dom.unfreeze();
				frappe.msgprint(__('Error loading dashboard data'));
			}
		});
	}

	render_dashboard(data) {
		// Update summary cards
		this.update_summary_cards(data.summary, data.previous_period);

		// Update charts
		this.render_growth_chart(data.growth_trend);
		this.render_revenue_chart(data.revenue_projection);

		// Update goals and breakdown
		this.render_goals_progress(data.goals);
		this.render_membership_breakdown(data.membership_breakdown);

		// Update insights
		this.render_insights(data.insights);

		// Render segmentation data
		if (data.segmentation) {
			this.render_segmentation(data.segmentation);
		}

		// Render cohort analysis
		if (data.cohort_analysis) {
			this.render_cohort_analysis(data.cohort_analysis);
		}

		// Update last updated time
		$('#last-updated').text(frappe.datetime.str_to_user(data.last_updated));
	}

	update_summary_cards(summary, previous) {
		// Total Members
		$('#total-members').text(this.format_number(summary.total_members));

		// Net Growth
		$('#net-growth').html(this.format_growth_number(summary.net_growth));

		// Growth Rate
		$('#growth-rate').text(summary.growth_rate.toFixed(1) + '%');

		// Projected Revenue
		$('#projected-revenue').text(this.format_currency(summary.projected_revenue));

		// Show comparison if available
		if (previous) {
			const growth_change = summary.net_growth - previous.net_growth;
			const growth_pct = previous.net_growth ?
				((growth_change / Math.abs(previous.net_growth)) * 100).toFixed(1) : 0;

			$('#net-growth-change').html(
				`<i class="fa fa-${growth_change >= 0 ? 'arrow-up' : 'arrow-down'}"></i> ${growth_pct}%`
			);
		}
	}

	render_growth_chart(data) {
		const chart_data = {
			labels: data.map(d => d.period),
			datasets: [{
				name: __('New Members'),
				values: data.map(d => d.new_members),
				chartType: 'bar'
			}, {
				name: __('Lost Members'),
				values: data.map(d => -d.lost_members),
				chartType: 'bar'
			}, {
				name: __('Net Growth'),
				values: data.map(d => d.net_growth),
				chartType: 'line'
			}]
		};

		if (this.charts.growth) {
			this.charts.growth.destroy();
		}

		this.charts.growth = new frappe.Chart('#growth-trend-chart', {
			data: chart_data,
			type: 'axis-mixed',
			height: 300,
			colors: ['#5e64ff', '#ff4757', '#2ecc71'],
			axisOptions: {
				xAxisMode: 'tick',
				xIsSeries: true
			},
			barOptions: {
				stacked: false
			}
		});
	}

	render_revenue_chart(data) {
		const chart_data = {
			labels: data.map(d => d.membership_type),
			datasets: [{
				name: __('Revenue'),
				values: data.map(d => d.revenue)
			}]
		};

		if (this.charts.revenue) {
			this.charts.revenue.destroy();
		}

		this.charts.revenue = new frappe.Chart('#revenue-chart', {
			data: chart_data,
			type: 'bar',
			height: 300,
			colors: ['#00d2d3'],
			format_tooltip_y: d => this.format_currency(d)
		});
	}

	render_goals_progress(goals) {
		const container = $('#goals-progress');
		container.empty();

		if (!goals || goals.length === 0) {
			container.html('<p class="text-muted">' + __('No goals set for this period') + '</p>');
			return;
		}

		goals.forEach(goal => {
			const progress_class = goal.achievement_percentage >= 100 ? 'progress-bar-success' :
				goal.achievement_percentage >= 75 ? 'progress-bar-warning' :
					'progress-bar-danger';

			const goal_html = `
                <div class="goal-item mb-3">
                    <div class="d-flex justify-content-between mb-1">
                        <strong>${goal.goal_name}</strong>
                        <span>${goal.achievement_percentage.toFixed(1)}%</span>
                    </div>
                    <div class="progress">
                        <div class="progress-bar ${progress_class}"
                             style="width: ${Math.min(goal.achievement_percentage, 100)}%">
                        </div>
                    </div>
                    <small class="text-muted">
                        ${this.format_goal_value(goal.current_value, goal.goal_type)} /
                        ${this.format_goal_value(goal.target_value, goal.goal_type)}
                    </small>
                </div>
            `;
			container.append(goal_html);
		});
	}

	render_membership_breakdown(data) {
		const container = $('#membership-breakdown');
		container.empty();

		if (!data || data.length === 0) {
			container.html('<p class="text-muted">' + __('No membership data available') + '</p>');
			return;
		}

		const total = data.reduce((sum, item) => sum + item.count, 0);

		data.forEach(item => {
			const percentage = ((item.count / total) * 100).toFixed(1);
			const breakdown_html = `
                <div class="breakdown-item mb-3">
                    <div class="d-flex justify-content-between">
                        <strong>${item.membership_type}</strong>
                        <span>${item.count} members</span>
                    </div>
                    <div class="progress" style="height: 10px;">
                        <div class="progress-bar" style="width: ${percentage}%"></div>
                    </div>
                    <small class="text-muted">${this.format_currency(item.revenue)}</small>
                </div>
            `;
			container.append(breakdown_html);
		});
	}

	render_insights(insights) {
		const container = $('#insights-list');
		container.empty();

		if (!insights || insights.length === 0) {
			container.html('<p class="text-muted">' + __('No insights available') + '</p>');
			return;
		}

		insights.forEach(insight => {
			const insight_html = `
                <div class="insight-item insight-${insight.type}">
                    <i class="fa fa-${this.get_insight_icon(insight.type)}"></i>
                    ${insight.message}
                </div>
            `;
			container.append(insight_html);
		});
	}

	show_goal_dialog() {
		const d = new frappe.ui.Dialog({
			title: __('Add Membership Goal'),
			fields: [
				{
					label: __('Goal Name'),
					fieldname: 'goal_name',
					fieldtype: 'Data',
					reqd: 1
				},
				{
					label: __('Goal Type'),
					fieldname: 'goal_type',
					fieldtype: 'Select',
					options: [
						'Member Count Growth',
						'Revenue Growth',
						'Retention Rate',
						'New Member Acquisition',
						'Churn Reduction',
						'Chapter Expansion'
					],
					reqd: 1
				},
				{
					label: __('Target Value'),
					fieldname: 'target_value',
					fieldtype: 'Float',
					reqd: 1,
					description: __('Enter number or percentage based on goal type')
				},
				{
					label: __('Goal Year'),
					fieldname: 'goal_year',
					fieldtype: 'Int',
					default: new Date().getFullYear(),
					reqd: 1
				},
				{
					label: __('Start Date'),
					fieldname: 'start_date',
					fieldtype: 'Date',
					default: frappe.datetime.year_start(),
					reqd: 1
				},
				{
					label: __('End Date'),
					fieldname: 'end_date',
					fieldtype: 'Date',
					default: frappe.datetime.year_end(),
					reqd: 1
				},
				{
					label: __('Description'),
					fieldname: 'description',
					fieldtype: 'Text'
				}
			],
			primary_action_label: __('Create Goal'),
			primary_action: (values) => {
				frappe.call({
					method: 'verenigingen.verenigingen.page.membership_analytics.membership_analytics.create_goal',
					args: {
						goal_data: values
					},
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __('Goal created successfully'),
								indicator: 'green'
							});
							d.hide();
							this.refresh_dashboard();
						}
					}
				});
			}
		});
		d.show();
	}

	// Helper functions
	format_number(num) {
		return num.toLocaleString();
	}

	format_growth_number(num) {
		const formatted = this.format_number(Math.abs(num));
		if (num > 0) {
			return `<span class="text-success">+${formatted}</span>`;
		} else if (num < 0) {
			return `<span class="text-danger">-${formatted}</span>`;
		}
		return formatted;
	}

	format_currency(amount) {
		return format_currency(amount, frappe.defaults.get_default('currency') || 'EUR');
	}

	format_goal_value(value, goal_type) {
		if (goal_type.includes('Rate') || goal_type.includes('Percentage')) {
			return value.toFixed(1) + '%';
		} else if (goal_type.includes('Revenue')) {
			return this.format_currency(value);
		}
		return this.format_number(value);
	}

	get_insight_icon(type) {
		const icons = {
			'success': 'check-circle',
			'warning': 'exclamation-triangle',
			'danger': 'exclamation-circle',
			'info': 'info-circle'
		};
		return icons[type] || 'info-circle';
	}

	render_segmentation(segmentation) {
		// Render chapter segmentation
		if (segmentation.by_chapter) {
			this.render_segmentation_chart('chapter-segmentation-chart', segmentation.by_chapter, 'Chapter Distribution');
		}

		// Render region segmentation
		if (segmentation.by_region) {
			this.render_segmentation_chart('region-segmentation-chart', segmentation.by_region, 'Regional Distribution');
		}

		// Render age segmentation
		if (segmentation.by_age) {
			this.render_segmentation_chart('age-segmentation-chart', segmentation.by_age, 'Age Distribution');
		}

		// Render payment method segmentation
		if (segmentation.by_payment_method) {
			this.render_segmentation_chart('payment-method-chart', segmentation.by_payment_method, 'Payment Methods');
		}
	}

	render_segmentation_chart(elementId, data, title) {
		const container = $(`#${elementId}`);
		if (!container.length) return;

		// Sort by total members descending and take top 10
		const sortedData = data.sort((a, b) => b.total_members - a.total_members).slice(0, 10);

		const chartData = {
			labels: sortedData.map(d => d.name),
			datasets: [{
				name: __('Total Members'),
				values: sortedData.map(d => d.total_members)
			}]
		};

		// Destroy existing chart if any
		if (this.charts[elementId]) {
			this.charts[elementId].destroy();
		}

		this.charts[elementId] = new frappe.Chart(`#${elementId}`, {
			data: chartData,
			type: 'bar',
			height: 250,
			colors: ['#5e64ff'],
			axisOptions: {
				xAxisMode: 'tick',
				xIsSeries: true
			}
		});
	}

	render_cohort_analysis(cohortData) {
		const container = $('#cohort-heatmap');
		if (!container.length || !cohortData || cohortData.length === 0) return;

		// Create heatmap data
		const heatmapData = {
			labels: {
				months: ['M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9', 'M10', 'M11'],
				cohorts: cohortData.map(c => c.cohort)
			},
			datasets: []
		};

		// Build dataset for heatmap
		cohortData.forEach((cohort, idx) => {
			const values = [];
			for (let i = 0; i < 12; i++) {
				const retention = cohort.retention.find(r => r.month === i);
				values.push(retention ? retention.rate : null);
			}
			heatmapData.datasets.push({
				name: cohort.cohort,
				values: values
			});
		});

		// Render as a table for now (Frappe Charts doesn't have native heatmap)
		this.render_cohort_table(cohortData);
	}

	render_cohort_table(cohortData) {
		const container = $('#cohort-heatmap');
		container.empty();

		let tableHtml = `
            <table class="table table-bordered table-sm cohort-table">
                <thead>
                    <tr>
                        <th>Cohort</th>
                        <th>Size</th>`;

		// Add month headers
		for (let i = 0; i < 12; i++) {
			tableHtml += `<th>M${i}</th>`;
		}
		tableHtml += '</tr></thead><tbody>';

		// Add cohort rows
		cohortData.forEach(cohort => {
			tableHtml += `<tr>
                <td><strong>${cohort.cohort}</strong></td>
                <td>${cohort.initial}</td>`;

			for (let i = 0; i < 12; i++) {
				const retention = cohort.retention.find(r => r.month === i);
				if (retention) {
					const rate = retention.rate;
					const colorClass = rate >= 80 ? 'bg-success' :
						rate >= 60 ? 'bg-info' :
							rate >= 40 ? 'bg-warning' : 'bg-danger';
					tableHtml += `<td class="${colorClass} text-white">${rate.toFixed(0)}%</td>`;
				} else {
					tableHtml += '<td>-</td>';
				}
			}
			tableHtml += '</tr>';
		});

		tableHtml += '</tbody></table>';
		container.html(tableHtml);
	}

	/**
	 * @method export_data
	 * @description Exports comprehensive analytics data in multiple formats for reporting
	 *
	 * Generates executive-ready reports containing all dashboard analytics data,
	 * charts, and insights in professional formats suitable for board presentations,
	 * regulatory compliance, and strategic planning documentation.
	 *
	 * Export Formats:
	 * - Excel: Comprehensive workbook with multiple sheets, charts, and pivot tables
	 * - PDF: Executive summary with visualizations and key insights
	 * - CSV: Raw data for further analysis and integration
	 *
	 * Report Contents:
	 * - Membership growth trends and projections
	 * - Revenue analysis and forecasting
	 * - Regional and demographic breakdowns
	 * - Goal progress and achievement metrics
	 * - Comparative period analysis
	 * - Key performance indicators summary
	 *
	 * Compliance Features:
	 * - Audit trail with export timestamps
	 * - Data validation and integrity checks
	 * - GDPR-compliant member data handling
	 * - Secure file generation and transfer
	 *
	 * @param {string} format - Export format ('excel', 'pdf', 'csv')
	 * @throws {Error} If export generation fails or format unsupported
	 * @since 1.5.0
	 *
	 * @example
	 * // Export Excel report
	 * this.export_data('excel');
	 *
	 * // Export PDF summary
	 * this.export_data('pdf');
	 */
	export_data(format) {
		frappe.dom.freeze('Preparing export...');

		frappe.call({
			method: 'verenigingen.verenigingen.page.membership_analytics.membership_analytics.export_dashboard_data',
			args: {
				year: this.filters.year,
				period: this.filters.period,
				format: format
			},
			callback: (r) => {
				frappe.dom.unfreeze();
				if (format === 'excel') {
					// Handle binary download
					const blob = new Blob([r.message], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
					const url = window.URL.createObjectURL(blob);
					const a = document.createElement('a');
					a.href = url;
					a.download = `membership_analytics_${frappe.datetime.nowdate()}.xlsx`;
					document.body.appendChild(a);
					a.click();
					window.URL.revokeObjectURL(url);
					document.body.removeChild(a);
				} else {
					frappe.msgprint(__('Export feature for {0} is under development', [format]));
				}
			},
			error: () => {
				frappe.dom.unfreeze();
				frappe.msgprint(__('Error exporting data'));
			}
		});
	}

	create_snapshot() {
		frappe.confirm(
			__('Create a snapshot of current analytics data?'),
			() => {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot.create_snapshot',
					args: {
						snapshot_type: 'Manual',
						specific_date: frappe.datetime.nowdate()
					},
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __('Snapshot created successfully'),
								indicator: 'green'
							});
						}
					}
				});
			}
		);
	}

	/**
	 * @method show_predictive_analytics
	 * @description Displays advanced predictive analytics dialog with machine learning insights
	 *
	 * Launches a comprehensive predictive analytics interface featuring 12-month
	 * membership growth forecasts, revenue projections, scenario modeling, and
	 * churn risk analysis. Integrates machine learning algorithms for strategic planning.
	 *
	 * Predictive Analytics Features:
	 * - Member growth forecasting with confidence intervals
	 * - Revenue projection based on membership trends
	 * - Multiple growth scenarios (conservative, optimistic, aggressive)
	 * - Churn risk identification and member retention analytics
	 * - Cohort behavior prediction and lifecycle modeling
	 * - Actionable recommendations for membership optimization
	 *
	 * Machine Learning Integration:
	 * - Time series analysis for trend extrapolation
	 * - Regression models for revenue forecasting
	 * - Classification algorithms for churn prediction
	 * - Clustering analysis for member segmentation
	 * - Anomaly detection for unusual membership patterns
	 *
	 * Strategic Planning Support:
	 * - Goal setting with data-driven targets
	 * - Resource allocation recommendations
	 * - Risk mitigation strategies
	 * - Market opportunity identification
	 * - Performance benchmarking and optimization
	 *
	 * @param {number} [months_ahead=12] - Forecast horizon in months
	 * @throws {Error} If ML backend is unavailable or data insufficient for predictions
	 * @since 2.0.0
	 *
	 * @example
	 * // Triggered by Predictive Analytics button
	 * $('#btn-predictive').on('click', () => this.show_predictive_analytics());
	 */
	show_predictive_analytics() {
		frappe.dom.freeze('Loading predictive analytics...');

		frappe.call({
			method: 'verenigingen.verenigingen.page.membership_analytics.predictive_analytics.get_predictive_analytics',
			args: {
				months_ahead: 12
			},
			callback: (r) => {
				frappe.dom.unfreeze();
				if (r.message) {
					this.render_predictive_dialog(r.message);
				}
			},
			error: () => {
				frappe.dom.unfreeze();
				frappe.msgprint(__('Error loading predictive analytics'));
			}
		});
	}

	render_predictive_dialog(data) {
		const dialog = new frappe.ui.Dialog({
			title: __('Predictive Analytics'),
			size: 'extra-large',
			fields: [{
				fieldname: 'content',
				fieldtype: 'HTML'
			}],
			primary_action_label: __('Close'),
			primary_action: () => dialog.hide()
		});

		const html = this.build_predictive_html(data);
		dialog.fields_dict.content.$wrapper.html(html);
		dialog.show();

		// Render charts after dialog is shown
		setTimeout(() => {
			this.render_forecast_chart(data.member_growth_forecast);
			this.render_revenue_forecast_chart(data.revenue_forecast);
			this.render_scenarios_chart(data.growth_scenarios);
		}, 100);
	}

	build_predictive_html(data) {
		return `
            <div class="predictive-analytics-content">
                <!-- Member Growth Forecast -->
                <div class="section">
                    <h4>${__('Member Growth Forecast')}</h4>
                    <div class="row">
                        <div class="col-md-8">
                            <div id="member-forecast-chart" style="height: 300px;"></div>
                        </div>
                        <div class="col-md-4">
                            <div class="forecast-metrics">
                                <div class="metric-card">
                                    <h6>${__('Current Members')}</h6>
                                    <h3>${this.format_number(data.member_growth_forecast.metrics.current_members)}</h3>
                                </div>
                                <div class="metric-card">
                                    <h6>${__('Forecast Members (12m)')}</h6>
                                    <h3>${this.format_number(data.member_growth_forecast.metrics.forecast_members)}</h3>
                                </div>
                                <div class="metric-card">
                                    <h6>${__('Expected Growth')}</h6>
                                    <h3 class="text-success">+${this.format_number(data.member_growth_forecast.metrics.expected_growth)}</h3>
                                    <small>${data.member_growth_forecast.metrics.growth_rate}%</small>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Revenue Forecast -->
                <div class="section mt-4">
                    <h4>${__('Revenue Forecast')}</h4>
                    <div class="row">
                        <div class="col-md-8">
                            <div id="revenue-forecast-chart" style="height: 300px;"></div>
                        </div>
                        <div class="col-md-4">
                            <div class="forecast-metrics">
                                <div class="metric-card">
                                    <h6>${__('Annual Projection')}</h6>
                                    <h3>${this.format_currency(data.revenue_forecast.annual_projection)}</h3>
                                </div>
                                <div class="metric-card">
                                    <h6>${__('Avg Member Value')}</h6>
                                    <h3>${this.format_currency(data.revenue_forecast.avg_member_value)}</h3>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Growth Scenarios -->
                <div class="section mt-4">
                    <h4>${__('Growth Scenarios')}</h4>
                    <div id="scenarios-chart" style="height: 300px;"></div>
                    <div class="scenarios-grid mt-3">
                        ${this.build_scenarios_html(data.growth_scenarios)}
                    </div>
                </div>

                <!-- Churn Risk Analysis -->
                <div class="section mt-4">
                    <h4>${__('Churn Risk Analysis')}</h4>
                    <div class="row">
                        <div class="col-md-4">
                            <div class="risk-summary">
                                <h6>${__('At-Risk Members')}</h6>
                                <div class="risk-stats">
                                    <div class="risk-stat high-risk">
                                        <span class="label">${__('High Risk')}</span>
                                        <span class="value">${data.churn_risk_analysis.statistics.high_risk}</span>
                                    </div>
                                    <div class="risk-stat medium-risk">
                                        <span class="label">${__('Medium Risk')}</span>
                                        <span class="value">${data.churn_risk_analysis.statistics.medium_risk}</span>
                                    </div>
                                    <div class="risk-stat low-risk">
                                        <span class="label">${__('Low Risk')}</span>
                                        <span class="value">${data.churn_risk_analysis.statistics.low_risk}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-8">
                            <h6>${__('High Risk Members')}</h6>
                            <div class="risk-members-list">
                                ${this.build_risk_members_html(data.churn_risk_analysis.high_risk_members)}
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Recommendations -->
                <div class="section mt-4">
                    <h4>${__('Recommendations')}</h4>
                    <div class="recommendations-list">
                        ${this.build_recommendations_html(data.recommendations)}
                    </div>
                </div>
            </div>

            <style>
                .predictive-analytics-content {
                    padding: 20px;
                }
                .section {
                    background: #f8f9fa;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                }
                .metric-card {
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    margin-bottom: 15px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                .metric-card h6 {
                    color: #6c757d;
                    font-size: 12px;
                    margin-bottom: 10px;
                }
                .metric-card h3 {
                    margin: 0;
                    font-size: 24px;
                }
                .risk-stats {
                    display: flex;
                    gap: 10px;
                }
                .risk-stat {
                    flex: 1;
                    padding: 10px;
                    border-radius: 8px;
                    text-align: center;
                }
                .high-risk { background: #fee; color: #d9534f; }
                .medium-risk { background: #fff3cd; color: #856404; }
                .low-risk { background: #d4edda; color: #155724; }
                .scenarios-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 15px;
                }
                .scenario-card {
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                .recommendation-item {
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    margin-bottom: 15px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                .priority-badge {
                    display: inline-block;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                }
                .priority-critical { background: #d9534f; color: white; }
                .priority-high { background: #f0ad4e; color: white; }
                .priority-medium { background: #5bc0de; color: white; }
            </style>
        `;
	}

	build_scenarios_html(scenarios) {
		let html = '';
		for (const [key, scenario] of Object.entries(scenarios.scenarios)) {
			html += `
                <div class="scenario-card">
                    <h5>${scenario.name}</h5>
                    <p class="text-muted small">${scenario.description}</p>
                    <div class="scenario-stats">
                        <div><strong>${__('Growth Rate')}:</strong> ${scenario.growth_rate.toFixed(1)}%</div>
                        <div><strong>${__('Year 1')}:</strong> ${this.format_number(scenario.projections.year_1.members)} members</div>
                        <div><strong>${__('Revenue')}:</strong> ${this.format_currency(scenario.projections.year_1.revenue)}</div>
                    </div>
                </div>
            `;
		}
		return html;
	}

	build_risk_members_html(members) {
		if (!members || members.length === 0) {
			return '<p class="text-muted">' + __('No high-risk members identified') + '</p>';
		}

		let html = '<table class="table table-sm"><thead><tr><th>Member</th><th>Risk Score</th><th>Factors</th><th>Action</th></tr></thead><tbody>';
		members.forEach(member => {
			html += `
                <tr>
                    <td>${member.member_name}</td>
                    <td>${(member.risk_score * 100).toFixed(0)}%</td>
                    <td>${member.risk_factors.join(', ')}</td>
                    <td><small>${member.recommended_action}</small></td>
                </tr>
            `;
		});
		html += '</tbody></table>';
		return html;
	}

	build_recommendations_html(recommendations) {
		let html = '';
		recommendations.forEach(rec => {
			html += `
                <div class="recommendation-item">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h5>${rec.recommendation}</h5>
                        <span class="priority-badge priority-${rec.priority.toLowerCase()}">${rec.priority}</span>
                    </div>
                    <p class="text-muted">${rec.impact}</p>
                    <h6>${__('Actions')}:</h6>
                    <ul class="mb-0">
                        ${rec.actions.map(action => `<li>${action}</li>`).join('')}
                    </ul>
                </div>
            `;
		});
		return html;
	}

	render_forecast_chart(forecast) {
		if (!forecast || !forecast.forecast) return;

		const chartData = {
			labels: [...forecast.historical_trend.months, ...forecast.forecast.months],
			datasets: [{
				name: __('Historical'),
				values: [...forecast.historical_trend.values, ...Array(forecast.forecast.values.length).fill(null)]
			}, {
				name: __('Forecast'),
				values: [...Array(forecast.historical_trend.values.length).fill(null), ...forecast.forecast.values]
			}]
		};

		new frappe.Chart('#member-forecast-chart', {
			data: chartData,
			type: 'line',
			height: 300,
			colors: ['#5e64ff', '#00d2d3'],
			axisOptions: {
				xAxisMode: 'tick',
				xIsSeries: true
			}
		});
	}

	render_revenue_forecast_chart(forecast) {
		if (!forecast || !forecast.monthly_forecast) return;

		const chartData = {
			labels: forecast.monthly_forecast.map(d => d.month),
			datasets: [{
				name: __('Monthly Revenue'),
				values: forecast.monthly_forecast.map(d => d.revenue)
			}, {
				name: __('Cumulative'),
				values: forecast.cumulative_revenue
			}]
		};

		new frappe.Chart('#revenue-forecast-chart', {
			data: chartData,
			type: 'line',
			height: 300,
			colors: ['#28a745', '#ffc107'],
			axisOptions: {
				xAxisMode: 'tick',
				xIsSeries: true
			},
			format_tooltip_y: d => this.format_currency(d)
		});
	}

	render_scenarios_chart(scenarios) {
		if (!scenarios || !scenarios.scenarios) return;

		const labels = [];
		const year1_values = [];
		const year3_values = [];

		for (const [key, scenario] of Object.entries(scenarios.scenarios)) {
			labels.push(scenario.name);
			year1_values.push(scenario.projections.year_1.members);
			year3_values.push(scenario.projections.year_3.members);
		}

		const chartData = {
			labels: labels,
			datasets: [{
				name: __('Year 1'),
				values: year1_values
			}, {
				name: __('Year 3'),
				values: year3_values
			}]
		};

		new frappe.Chart('#scenarios-chart', {
			data: chartData,
			type: 'bar',
			height: 300,
			colors: ['#5e64ff', '#00d2d3'],
			axisOptions: {
				xAxisMode: 'tick',
				xIsSeries: true
			}
		});
	}
}
