// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('E-Boekhouden Dashboard', {
	refresh: function(frm) {
		// Load dashboard data on form load
		frm.add_custom_button(__('Refresh Data'), function() {
			frm.call('load_dashboard_data').then(function() {
				frm.reload_doc();
				frappe.show_alert({
					message: __('Dashboard refreshed successfully'),
					indicator: 'green'
				});
			});
		}).addClass('btn-primary');

		// Add action buttons
		frm.add_custom_button(__('New Migration'), function() {
			frappe.new_doc('E-Boekhouden Migration');
		}).addClass('btn-success');

		frm.add_custom_button(__('View Migrations'), function() {
			frappe.set_route('List', 'E-Boekhouden Migration');
		});

		frm.add_custom_button(__('Settings'), function() {
			frappe.set_route('Form', 'E-Boekhouden Settings');
		});

		// Auto-refresh every 30 seconds if migration is active
		if (frm.doc.active_migrations > 0) {
			setTimeout(function() {
				if (cur_frm && cur_frm.doc.name === frm.doc.name) {
					frm.reload_doc();
				}
			}, 30000);
		}

		// Load data if not loaded
		if (!frm.doc.last_sync_time ||
			(new Date() - new Date(frm.doc.last_sync_time)) > 300000) { // 5 minutes
			frm.call('load_dashboard_data').then(function() {
				frm.reload_doc();
			});
		}
	},

	onload: function(frm) {
		// Set form as read-only since it's a dashboard
		frm.set_read_only();

		// Custom title
		if (frm.is_new()) {
			frm.set_value('name', 'E-Boekhouden Dashboard');
		}
	}
});

// Helper function to format numbers
function format_number(num) {
	if (num >= 1000000) {
		return (num / 1000000).toFixed(1) + 'M';
	} else if (num >= 1000) {
		return (num / 1000).toFixed(1) + 'K';
	}
	return num.toString();
}

// Real-time updates for migration progress
frappe.realtime.on('migration_progress_update', function(data) {
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
