/**
 * Termination Dashboard - Frappe-compatible implementation
 * Provides overview of membership termination requests
 */

frappe.provide('verenigingen.termination_dashboard');

verenigingen.termination_dashboard = {
	init: function() {
		this.setup_dashboard();
		this.load_data();
	},

	setup_dashboard: function() {
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

	bind_events: function() {
		$('#view-all-requests').on('click', function() {
			frappe.set_route('List', 'Membership Termination Request');
		});

		$('#new-termination').on('click', function() {
			frappe.set_route('Form', 'Membership Termination Request', 'new');
		});
	},

	show: function() {
		$('.termination-dashboard').show();
		this.load_data();
	},

	hide: function() {
		$('.termination-dashboard').hide();
	},

	load_data: function() {
		const self = this;

		// Load dashboard statistics
		frappe.call({
			method: 'verenigingen.api.termination_api.get_dashboard_stats',
			callback: function(r) {
				if (r.message) {
					self.update_stats(r.message);
				}
			},
			error: function() {
				frappe.msgprint(__('Failed to load dashboard statistics'));
			}
		});

		// Load pending requests
		this.load_pending_requests();
		// Load recent activity
		this.load_recent_activity();
	},

	update_stats: function(stats) {
		$('#pending-count').text(stats.pending_approvals || 0);
		$('#total-count').text(stats.total_requests || 0);
		$('#recent-count').text(stats.recent_activity?.requests || 0);
		$('#execution-count').text(stats.ready_for_execution || 0);

		// Update colors based on values
		this.update_stat_colors(stats);
	},

	update_stat_colors: function(stats) {
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

	load_pending_requests: function() {
		frappe.call({
			method: 'verenigingen.api.termination_api.get_pending_requests',
			args: { limit: 10 },
			callback: function(r) {
				if (r.message) {
					verenigingen.termination_dashboard.render_pending_requests(r.message);
				}
			}
		});
	},

	load_recent_activity: function() {
		frappe.call({
			method: 'verenigingen.api.termination_api.get_recent_activity',
			args: { limit: 10 },
			callback: function(r) {
				if (r.message) {
					verenigingen.termination_dashboard.render_recent_activity(r.message);
				}
			}
		});
	},

	render_pending_requests: function(requests) {
		const container = $('#pending-requests-list');
		container.empty();

		if (!requests || requests.length === 0) {
			container.html('<p class="text-muted">No pending requests</p>');
			return;
		}

		requests.forEach(function(request) {
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

	render_recent_activity: function(activities) {
		const container = $('#recent-activity-list');
		container.empty();

		if (!activities || activities.length === 0) {
			container.html('<p class="text-muted">No recent activity</p>');
			return;
		}

		activities.forEach(function(activity) {
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

	get_status_color: function(status) {
		const colors = {
			'Draft': 'badge-info',
			'Pending Approval': 'badge-warning',
			'Approved': 'badge-success',
			'Rejected': 'badge-danger',
			'Executed': 'badge-secondary'
		};
		return colors[status] || 'badge-secondary';
	},

	get_type_color: function(type) {
		const disciplinaryTypes = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
		return disciplinaryTypes.includes(type) ? 'type-disciplinary' : 'type-voluntary';
	}
};

// Initialize when document is ready
$(document).ready(function() {
	if (frappe.get_route()[0] === 'termination-dashboard') {
		verenigingen.termination_dashboard.init();
		verenigingen.termination_dashboard.show();
	}
});

// Export for other modules
window.TerminationDashboard = verenigingen.termination_dashboard;
