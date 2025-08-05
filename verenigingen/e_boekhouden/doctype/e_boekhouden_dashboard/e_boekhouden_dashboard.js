/**
 * @fileoverview E-Boekhouden Dashboard DocType JavaScript for migration monitoring
 *
 * Provides comprehensive dashboard functionality for monitoring E-Boekhouden
 * integration and migration activities. This DocType serves as the central
 * control panel for financial data synchronization between the Verenigingen
 * system and the E-Boekhouden accounting platform.
 *
 * Key Features:
 * - Real-time migration progress monitoring
 * - Dashboard data refresh and auto-sync capabilities
 * - Quick access to migration management functions
 * - Integration status indicators and health metrics
 * - Automated dashboard updates during active migrations
 * - Custom styling for optimal dashboard presentation
 *
 * Dashboard Components:
 * - Migration status overview with progress indicators
 * - Active migration count and status tracking
 * - Quick action buttons for common operations
 * - Real-time updates via WebSocket connections
 * - Auto-refresh functionality for active migrations
 * - Settings and configuration access
 *
 * Business Context:
 * Essential for financial administrators monitoring the complex process of
 * synchronizing membership and financial data with external accounting systems.
 * Provides visibility into migration health, progress tracking, and quick
 * access to troubleshooting tools for maintaining data integrity.
 *
 * Integration:
 * - Connects to E-Boekhouden Migration DocType for operation tracking
 * - Links to E-Boekhouden Settings for configuration management
 * - Uses real-time updates for migration progress monitoring
 * - Integrates with background migration processes
 * - Supports automated data synchronization workflows
 *
 * @author Verenigingen Development Team
 * @version 2.1.0
 * @since 2024-10-15
 */

// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('E-Boekhouden Dashboard', {
	refresh(frm) {
		// Load dashboard data on form load
		frm.add_custom_button(__('Refresh Data'), () => {
			frm.call('load_dashboard_data').then(() => {
				frm.reload_doc();
				frappe.show_alert({
					message: __('Dashboard refreshed successfully'),
					indicator: 'green'
				});
			});
		}).addClass('btn-primary');

		// Add action buttons
		frm.add_custom_button(__('New Migration'), () => {
			frappe.new_doc('E-Boekhouden Migration');
		}).addClass('btn-success');

		frm.add_custom_button(__('View Migrations'), () => {
			frappe.set_route('List', 'E-Boekhouden Migration');
		});

		frm.add_custom_button(__('Settings'), () => {
			frappe.set_route('Form', 'E-Boekhouden Settings');
		});

		// Auto-refresh every 30 seconds if migration is active
		if (frm.doc.active_migrations > 0) {
			setTimeout(() => {
				if (cur_frm && cur_frm.doc.name === frm.doc.name) {
					frm.reload_doc();
				}
			}, 30000);
		}

		// Load data if not loaded
		if (!frm.doc.last_sync_time
			|| (new Date() - new Date(frm.doc.last_sync_time)) > 300000) { // 5 minutes
			frm.call('load_dashboard_data').then(() => {
				frm.reload_doc();
			});
		}
	},

	onload(frm) {
		// Set form as read-only since it's a dashboard
		frm.set_read_only();

		// Custom title
		if (frm.is_new()) {
			frm.set_value('name', 'E-Boekhouden Dashboard');
		}
	}
});

// Helper function to format numbers
function _format_number(num) {
	if (num >= 1000000) {
		return `${(num / 1000000).toFixed(1)}M`;
	} else if (num >= 1000) {
		return `${(num / 1000).toFixed(1)}K`;
	}
	return num.toString();
}

// Real-time updates for migration progress
frappe.realtime.on('migration_progress_update', (data) => {
	if (cur_frm && cur_frm.doctype === 'E-Boekhouden Dashboard') {
		// Update dashboard if we're viewing it
		cur_frm.reload_doc();
	}
});

// Custom CSS for better dashboard appearance
$('<style>')
	.prop('type', 'text/css')
	.html(`
		.form-page[data-doctype="E-Boekhouden Dashboard"] .form-sidebar {
			display: none;
		}
		.form-page[data-doctype="E-Boekhouden Dashboard"] .form-column {
			padding: 0;
		}
		.form-page[data-doctype="E-Boekhouden Dashboard"] .form-section {
			box-shadow: none;
			border: none;
		}
	`)
	.appendTo('head');
