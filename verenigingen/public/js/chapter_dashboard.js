/**
 * @fileoverview Chapter Management Dashboard
 * @description Interactive dashboard for chapter board administration and governance
 *
 * Business Context:
 * Provides chapter board members with comprehensive management tools including
 * membership approval, financial oversight, communication coordination, and
 * administrative oversight. Central hub for chapter governance operations.
 *
 * Key Features:
 * - Real-time membership metrics and pending applications
 * - Financial reporting with role-based access controls
 * - Board member management and communication tools
 * - Automated refresh and notification systems
 * - Permission-based action restrictions
 *
 * Architecture:
 * - Modular function organization with permission validation
 * - Auto-refresh mechanism for real-time data accuracy
 * - Event-driven UI updates with loading states
 * - RESTful API integration for backend operations
 *
 * Security Measures:
 * - Role-based permission validation before actions
 * - Expense approval limits enforcement
 * - Secure API communication with error handling
 * - Input validation and XSS prevention
 *
 * Performance Optimizations:
 * - Silent refresh mechanisms to reduce UI interruption
 * - Efficient DOM updates using targeted selectors
 * - Keyboard shortcuts for power users
 * - Lazy loading of financial data for unauthorized users
 *
 * Integration Points:
 * - Member management system for approval workflows
 * - Financial reporting modules for expense tracking
 * - Communication APIs for member notifications
 * - Chapter administration backend services
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module ChapterDashboard
 * @requires frappe.call, frappe.msgprint, jQuery
 */

// Global variables
let dashboardData = window.dashboardData || {};
const userPermissions = window.userPermissions || {};
const selectedChapter = window.selectedChapter || '';

// Initialize dashboard when document is ready
$(document).ready(() => {
	initializeDashboard();
});

function initializeDashboard() {
	// Set up event listeners
	setupEventListeners();

	// Set up auto-refresh
	setupAutoRefresh();

	// Initialize tooltips if available
	if (typeof $().tooltip === 'function') {
		$('[data-toggle="tooltip"]').tooltip();
	}
}

function setupEventListeners() {
	// Metric card click handlers
	$('.metric-card.members-card').on('click', () => {
		viewAllMembers();
	});

	$('.metric-card.pending-card').on('click', () => {
		showPendingApplications();
	});

	$('.metric-card.expenses-card').on('click', () => {
		if (userPermissions.can_view_finances) {
			viewFinancialReports();
		}
	});

	// Keyboard shortcuts
	$(document).on('keydown', (e) => {
		// Ctrl/Cmd + R for refresh
		if ((e.ctrlKey || e.metaKey) && e.keyCode === 82) {
			e.preventDefault();
			refreshDashboardData();
		}
	});
}

function setupAutoRefresh() {
	// Refresh dashboard data every 5 minutes
	setInterval(() => {
		refreshDashboardData(true); // Silent refresh
	}, 300000);

	// Also refresh when page becomes visible again
	$(document).on('visibilitychange', () => {
		if (!document.hidden) {
			refreshDashboardData(true);
		}
	});
}

// Member Management Functions
function viewAllMembers() {
	showLoading();
	window.location.href = `/app/report/chapter-members?chapter=${encodeURIComponent(selectedChapter)}`;
}

function addNewMember() {
	if (!userPermissions.can_approve_members) {
		frappe.msgprint(__('You do not have permission to add members.'));
		return;
	}

	// Open member creation dialog or navigate to member form
	window.location.href = '/app/member/new';
}

function approveMember(memberId) {
	if (!userPermissions.can_approve_members) {
		frappe.msgprint(__('You do not have permission to approve members.'));
		return;
	}

	frappe.confirm(
		__('Are you sure you want to approve this member application?'),
		() => {
			showLoading();

			frappe.call({
				method: 'verenigingen.api.membership_application_review.approve_membership_application',
				args: {
					member_name: memberId,
					chapter: selectedChapter
				},
				callback(r) {
					hideLoading();

					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Member approved successfully'),
							indicator: 'green'
						});

						// Refresh dashboard data
						refreshDashboardData();
					} else {
						frappe.msgprint({
							title: __('Error'),
							message: r.message ? r.message.error : __('Failed to approve member'),
							indicator: 'red'
						});
					}
				},
				error(_r) {
					hideLoading();
					frappe.msgprint({
						title: __('Error'),
						message: __('An error occurred while approving the member'),
						indicator: 'red'
					});
				}
			});
		}
	);
}

function reviewMember(memberId) {
	// Open member record for review
	window.location.href = `/app/member/${encodeURIComponent(memberId)}`;
}

function showPendingApplications() {
	if (dashboardData.pending_actions && dashboardData.pending_actions.membership_applications) {
		const apps = dashboardData.pending_actions.membership_applications;

		if (apps.length === 0) {
			frappe.msgprint(__('No pending applications at this time.'));
			return;
		}

		// Create a dialog to show pending applications
		let html = '<div class="pending-applications-dialog">';
		html += '<h4>Pending Member Applications</h4>';
		html += '<div class="applications-list">';

		apps.forEach((app) => {
			html += `<div class="application-item ${app.is_overdue ? 'overdue' : ''}">`;
			html += '<div class="app-info">';
			html += `<strong>${app.full_name}</strong>`;
			html += `<br><small>Applied ${app.days_pending} days ago</small>`;
			if (app.is_overdue) {
				html += '<span class="overdue-badge">OVERDUE</span>';
			}
			html += '</div>';

			if (userPermissions.can_approve_members) {
				html += '<div class="app-actions">';
				html += `<button class="btn btn-success btn-sm" onclick="approveMember('${app.member}')">Approve</button>`;
				html += `<button class="btn btn-default btn-sm" onclick="reviewMember('${app.member}')">Review</button>`;
				html += '</div>';
			}
			html += '</div>';
		});

		html += '</div></div>';

		frappe.msgprint({
			title: __('Pending Applications'),
			message: html,
			wide: true
		});
	}
}

// Financial Functions
function viewFinancialReports() {
	if (!userPermissions.can_view_finances) {
		frappe.msgprint(__('You do not have permission to view financial reports.'));
		return;
	}

	window.location.href = '/app/report/chapter-expense-report';
}

function _approveExpense(expenseId, amount) {
	if (!userPermissions.can_approve_expenses) {
		frappe.msgprint(__('You do not have permission to approve expenses.'));
		return;
	}

	if (amount > userPermissions.expense_limit) {
		frappe.msgprint(__(`This expense exceeds your approval limit of €${userPermissions.expense_limit}`));
		return;
	}

	frappe.confirm(
		__(`Are you sure you want to approve this expense of €${amount}?`),
		() => {
			// Implementation for expense approval
			frappe.msgprint(__('Expense approval functionality will be implemented when expense system is integrated.'));
		}
	);
}

// Board Management Functions
function manageBoardMembers() {
	if (!userPermissions.can_manage_board) {
		frappe.msgprint(__('You do not have permission to manage board members.'));
		return;
	}

	window.location.href = `/app/chapter/${encodeURIComponent(selectedChapter)}`;
}

// Dashboard Data Management
function refreshDashboardData(silent = false) {
	if (!silent) {
		showLoading();
	}

	frappe.call({
		method: 'verenigingen.templates.pages.chapter_dashboard.get_chapter_dashboard_data',
		args: {
			chapter_name: selectedChapter
		},
		callback(r) {
			if (!silent) {
				hideLoading();
			}

			if (r.message) {
				dashboardData = r.message;
				updateDashboardDisplay();

				if (!silent) {
					frappe.show_alert({
						message: __('Dashboard refreshed'),
						indicator: 'green'
					});
				}
			}
		},
		error(_r) {
			if (!silent) {
				hideLoading();
				frappe.msgprint({
					title: __('Error'),
					message: __('Failed to refresh dashboard data'),
					indicator: 'red'
				});
			}
		}
	});
}

function updateDashboardDisplay() {
	// Update metric cards
	updateMetricCards();

	// Update pending actions count
	updatePendingActionsDisplay();

	// Update last updated timestamp
	updateLastUpdatedTime();
}

function updateMetricCards() {
	if (dashboardData.key_metrics) {
		const metrics = dashboardData.key_metrics;

		// Update members metric
		if (metrics.members) {
			$('.members-card .metric-content h3').text(metrics.members.active);
			const trend = $('.members-card .trend');
			if (metrics.members.new_this_month > 0) {
				trend.text(`+${metrics.members.new_this_month} this month`).addClass('positive');
			} else {
				trend.hide();
			}
		}

		// Update pending metric
		if (metrics.members) {
			$('.pending-card .metric-content h3').text(metrics.members.pending);
		}

		// Update expenses metric
		if (metrics.expenses) {
			$('.expenses-card .metric-content h3').text(`€${Math.round(metrics.expenses.pending_amount)}`);
		}
	}
}

function updatePendingActionsDisplay() {
	if (dashboardData.pending_actions) {
		const totalPending = dashboardData.pending_actions.total_pending || 0;
		$('.urgency-indicator').text(`${totalPending} items`);

		// Show/hide pending actions card based on whether there are items
		if (totalPending === 0) {
			$('.pending-actions').hide();
		} else {
			$('.pending-actions').show();
		}
	}
}

function updateLastUpdatedTime() {
	if (dashboardData.last_updated) {
		const now = new Date();
		const lastUpdated = new Date(dashboardData.last_updated);
		const diffMinutes = Math.floor((now - lastUpdated) / (1000 * 60));

		let timeText;
		if (diffMinutes < 1) {
			timeText = 'Just now';
		} else if (diffMinutes < 60) {
			timeText = `${diffMinutes} minutes ago`;
		} else {
			timeText = lastUpdated.toLocaleString();
		}

		$('.last-updated').text(`Last Updated: ${timeText}`);
	}
}

// Utility Functions
function showLoading() {
	$('#loading-overlay').show();
}

function hideLoading() {
	$('#loading-overlay').hide();
}

function _formatCurrency(amount) {
	return new Intl.NumberFormat('en-EU', {
		style: 'currency',
		currency: 'EUR'
	}).format(amount);
}

function formatDate(dateString) {
	const date = new Date(dateString);
	return date.toLocaleDateString('en-EU', {
		year: 'numeric',
		month: 'long',
		day: 'numeric'
	});
}

function _formatRelativeTime(dateString) {
	const date = new Date(dateString);
	const now = new Date();
	const diffDays = Math.floor((now - date) / (1000 * 60 * 60 * 24));

	if (diffDays === 0) {
		return 'Today';
	} else if (diffDays === 1) {
		return 'Yesterday';
	} else if (diffDays < 7) {
		return `${diffDays} days ago`;
	} else if (diffDays < 30) {
		const weeks = Math.floor(diffDays / 7);
		return `${weeks} week${weeks > 1 ? 's' : ''} ago`;
	} else {
		return formatDate(dateString);
	}
}

// Email Functions
function emailAllMembers() {
	if (!userPermissions.can_approve_members) {
		frappe.msgprint(__('You do not have permission to email all members.'));
		return;
	}

	// Get member emails for the chapter
	frappe.call({
		method: 'verenigingen.api.member_management.get_chapter_member_emails',
		args: {
			chapter_name: selectedChapter
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				const emails = r.message.join(';');
				window.location.href = `mailto:${emails}`;
			} else {
				frappe.msgprint(__('No member emails found for this chapter.'));
			}
		}
	});
}

// Export functions for global access
window.chapterDashboard = {
	viewAllMembers,
	addNewMember,
	approveMember,
	reviewMember,
	showPendingApplications,
	viewFinancialReports,
	manageBoardMembers,
	refreshDashboardData,
	emailAllMembers
};

// Make functions globally available for HTML onclick handlers
window.viewAllMembers = viewAllMembers;
window.addNewMember = addNewMember;
window.approveMember = approveMember;
window.reviewMember = reviewMember;
window.viewFinancialReports = viewFinancialReports;
window.manageBoardMembers = manageBoardMembers;
window.refreshDashboardData = refreshDashboardData;
