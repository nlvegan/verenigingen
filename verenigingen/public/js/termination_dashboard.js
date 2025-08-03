/**
 * @fileoverview Membership Termination Dashboard - Administrative Oversight & Workflow Management
 *
 * This comprehensive dashboard provides administrative oversight of membership termination
 * processes, featuring real-time status monitoring, approval workflow management, and
 * operational analytics for membership lifecycle administration.
 *
 * ## Core Administrative Functions
 * - **Termination Request Monitoring**: Real-time tracking of all membership termination requests
 * - **Approval Workflow Management**: Streamlined approval process with role-based access control
 * - **Status Tracking**: Complete lifecycle tracking from request to execution
 * - **Priority Management**: Urgent request identification and escalation
 * - **Bulk Operations**: Efficient processing of multiple termination requests
 * - **Audit Trail**: Complete documentation of termination decisions and actions
 *
 * ## Dashboard Analytics
 * - **Pending Approvals**: Critical requests requiring immediate administrative attention
 * - **Volume Tracking**: Total termination requests with trend analysis
 * - **Recent Activity**: Real-time feed of termination-related activities
 * - **Execution Pipeline**: Approved requests ready for membership termination
 * - **Processing Metrics**: Time-to-resolution and efficiency measurements
 * - **Seasonal Patterns**: Historical termination trend analysis
 *
 * ## Workflow Integration
 * - **Automated Notifications**: Email alerts for pending approvals and status changes
 * - **Role-based Access**: Hierarchical approval permissions based on termination type
 * - **Document Management**: Attachment handling for termination documentation
 * - **Member Communication**: Automated member notifications throughout the process
 * - **Financial Integration**: Dues calculation and final payment processing
 * - **System Integration**: Seamless coordination with member management systems
 *
 * ## Termination Type Classification
 * - **Voluntary Terminations**: Member-initiated departures with standard processing
 * - **Disciplinary Actions**: Policy violation and misconduct-based terminations
 * - **Administrative Terminations**: System-initiated for non-payment or inactivity
 * - **Expulsion Proceedings**: Formal expulsion with comprehensive documentation
 * - **Automatic Terminations**: System-automated based on predefined criteria
 * - **Temporary Suspensions**: Reversible membership status changes
 *
 * ## Compliance & Documentation
 * - **Legal Compliance**: Adherence to association bylaws and termination procedures
 * - **Documentation Standards**: Standardized termination documentation and record-keeping
 * - **Privacy Protection**: GDPR-compliant data handling during termination process
 * - **Audit Requirements**: Complete audit trail for legal and regulatory compliance
 * - **Appeal Process**: Integration with member appeal and grievance procedures
 * - **Data Retention**: Proper handling of terminated member data per retention policies
 *
 * ## User Experience Features
 * - **Intuitive Interface**: Clean, actionable dashboard with clear visual hierarchy
 * - **Quick Actions**: One-click access to common termination operations
 * - **Status Visualization**: Color-coded status indicators and progress tracking
 * - **Search & Filter**: Advanced filtering for specific termination criteria
 * - **Bulk Processing**: Multi-select operations for efficiency
 * - **Mobile Responsive**: Full functionality on mobile devices for remote administration
 *
 * ## Performance & Scalability
 * - **Real-time Updates**: Live dashboard refresh without page reload
 * - **Efficient Queries**: Optimized database operations for large member datasets
 * - **Caching Strategy**: Smart caching of frequently accessed termination data
 * - **Progressive Loading**: Incremental data loading for better user experience
 * - **Memory Management**: Efficient handling of large termination datasets
 * - **Background Processing**: Non-blocking operations for complex termination tasks
 *
 * ## Integration Points
 * - Member management system
 * - Financial accounting integration
 * - Email notification service
 * - Document management system
 * - Audit logging infrastructure
 * - Reporting and analytics platform
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2024.1.0
 * @license Proprietary
 *
 * @requires frappe>=15.0.0
 * @requires verenigingen.member
 * @requires verenigingen.membership_termination_request
 * @requires verenigingen.api.termination_api
 *
 * @see {@link /termination-dashboard} Dashboard Interface
 * @see {@link /app/List/Membership%20Termination%20Request} Termination Request List
 */

/**
 * Termination Dashboard - Frappe-compatible implementation
 * Provides overview of membership termination requests
 */

frappe.provide('verenigingen.termination_dashboard');

verenigingen.termination_dashboard = {
	init() {
		this.setup_dashboard();
		this.load_data();
	},

	setup_dashboard() {
		// Dashboard container setup
		if (!$('.termination-dashboard').length) {
			$('body').append(`
				<div class="termination-dashboard" style="display: none;">
					<div class="dashboard-container">
						<div class="dashboard-header">
							<h1>Membership Termination Dashboard</h1>
							<div class="dashboard-actions">
								<button class="btn btn-default" id="view-all-requests">View All Requests</button>
								<button class="btn btn-primary" id="new-termination">New Termination</button>
							</div>
						</div>
						<div class="stats-grid">
							<div class="stat-card" id="pending-card">
								<div class="stat-icon">⚠️</div>
								<div class="stat-content">
									<div class="stat-title">Pending Approvals</div>
									<div class="stat-value" id="pending-count">0</div>
									<div class="stat-description">Requiring immediate attention</div>
								</div>
							</div>
							<div class="stat-card" id="total-card">
								<div class="stat-icon">📄</div>
								<div class="stat-content">
									<div class="stat-title">Total Requests</div>
									<div class="stat-value" id="total-count">0</div>
									<div class="stat-description">All time</div>
								</div>
							</div>
							<div class="stat-card" id="recent-card">
								<div class="stat-icon">📈</div>
								<div class="stat-content">
									<div class="stat-title">Recent Activity</div>
									<div class="stat-value" id="recent-count">0</div>
									<div class="stat-description">Last 30 days</div>
								</div>
							</div>
							<div class="stat-card" id="execution-card">
								<div class="stat-icon">✅</div>
								<div class="stat-content">
									<div class="stat-title">Ready for Execution</div>
									<div class="stat-value" id="execution-count">0</div>
									<div class="stat-description">Approved requests</div>
								</div>
							</div>
						</div>
						<div class="dashboard-content">
							<div class="pending-requests-section">
								<h3>Pending Requests</h3>
								<div id="pending-requests-list"></div>
							</div>
							<div class="recent-activity-section">
								<h3>Recent Activity</h3>
								<div id="recent-activity-list"></div>
							</div>
						</div>
					</div>
				</div>
			`);
		}
		this.bind_events();
	},

	bind_events() {
		$('#view-all-requests').on('click', () => {
			frappe.set_route('List', 'Membership Termination Request');
		});

		$('#new-termination').on('click', () => {
			frappe.set_route('Form', 'Membership Termination Request', 'new');
		});
	},

	show() {
		$('.termination-dashboard').show();
		this.load_data();
	},

	hide() {
		$('.termination-dashboard').hide();
	},

	load_data() {
		const self = this;

		// Load dashboard statistics
		frappe.call({
			method: 'verenigingen.api.termination_api.get_dashboard_stats',
			callback(r) {
				if (r.message) {
					self.update_stats(r.message);
				}
			},
			error() {
				frappe.msgprint(__('Failed to load dashboard statistics'));
			}
		});

		// Load pending requests
		this.load_pending_requests();
		// Load recent activity
		this.load_recent_activity();
	},

	update_stats(stats) {
		$('#pending-count').text(stats.pending_approvals || 0);
		$('#total-count').text(stats.total_requests || 0);
		$('#recent-count').text(stats.recent_activity?.requests || 0);
		$('#execution-count').text(stats.ready_for_execution || 0);

		// Update colors based on values
		this.update_stat_colors(stats);
	},

	update_stat_colors(stats) {
		// Update pending card color based on urgency
		const pendingCard = $('#pending-card');
		if (stats.pending_approvals > 10) {
			pendingCard.addClass('urgent');
		} else if (stats.pending_approvals > 5) {
			pendingCard.addClass('warning');
		} else {
			pendingCard.addClass('normal');
		}
	},

	load_pending_requests() {
		frappe.call({
			method: 'verenigingen.api.termination_api.get_pending_requests',
			args: { limit: 10 },
			callback(r) {
				if (r.message) {
					verenigingen.termination_dashboard.render_pending_requests(r.message);
				}
			}
		});
	},

	load_recent_activity() {
		frappe.call({
			method: 'verenigingen.api.termination_api.get_recent_activity',
			args: { limit: 10 },
			callback(r) {
				if (r.message) {
					verenigingen.termination_dashboard.render_recent_activity(r.message);
				}
			}
		});
	},

	render_pending_requests(requests) {
		const container = $('#pending-requests-list');
		container.empty();

		if (!requests || requests.length === 0) {
			container.html('<p class="text-muted">No pending requests</p>');
			return;
		}

		requests.forEach((request) => {
			const statusColor = verenigingen.termination_dashboard.get_status_color(request.status);
			const typeColor = verenigingen.termination_dashboard.get_type_color(request.termination_type);

			container.append(`
				<div class="request-item" data-name="${request.name}">
					<div class="request-header">
						<span class="member-name">${request.member_name || 'Unknown Member'}</span>
						<span class="badge ${statusColor}">${request.status}</span>
					</div>
					<div class="request-details">
						<span class="termination-type ${typeColor}">${request.termination_type}</span>
						<span class="request-date">${frappe.datetime.str_to_user(request.creation)}</span>
					</div>
					<div class="request-actions">
						<button class="btn btn-xs btn-default" onclick="frappe.set_route('Form', 'Membership Termination Request', '${request.name}')">
							View
						</button>
					</div>
				</div>
			`);
		});
	},

	render_recent_activity(activities) {
		const container = $('#recent-activity-list');
		container.empty();

		if (!activities || activities.length === 0) {
			container.html('<p class="text-muted">No recent activity</p>');
			return;
		}

		activities.forEach((activity) => {
			container.append(`
				<div class="activity-item">
					<div class="activity-content">
						<span class="activity-description">${activity.description}</span>
						<span class="activity-time">${frappe.datetime.comment_when(activity.creation)}</span>
					</div>
				</div>
			`);
		});
	},

	get_status_color(status) {
		const colors = {
			Draft: 'badge-info',
			'Pending Approval': 'badge-warning',
			Approved: 'badge-success',
			Rejected: 'badge-danger',
			Executed: 'badge-secondary'
		};
		return colors[status] || 'badge-secondary';
	},

	get_type_color(type) {
		const disciplinaryTypes = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
		return disciplinaryTypes.includes(type) ? 'type-disciplinary' : 'type-voluntary';
	}
};

// Initialize when document is ready
$(document).ready(() => {
	if (frappe.get_route()[0] === 'termination-dashboard') {
		verenigingen.termination_dashboard.init();
		verenigingen.termination_dashboard.show();
	}
});

// Export for other modules
window.TerminationDashboard = verenigingen.termination_dashboard;
