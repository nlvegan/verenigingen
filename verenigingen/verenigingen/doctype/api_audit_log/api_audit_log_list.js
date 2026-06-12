/**
 * @fileoverview API Audit Log List View Controller for Verenigingen
 *
 * This controller customizes the list view for API Audit Log records,
 * providing administrative functions for log management.
 *
 * @description Business Context:
 * Provides administrative controls for managing the API Audit Log,
 * enabling authorized administrators to maintain log hygiene and
 * comply with data retention policies.
 *
 * @description Key Features:
 * - Clear All Logs function restricted to Verenigingen Administrators
 * - Confirmation dialog to prevent accidental deletion
 * - Bulk delete operation with progress feedback
 * - Role-based access control enforcement
 *
 * @description Security Features:
 * - Restricted to Verenigingen Administrator role only
 * - Requires explicit confirmation before deletion
 * - Audit trail of clearing operation
 * - Secure API endpoint with permission validation
 *
 * @author Verenigingen Development Team
 * @version 2025-10-25
 * @since 1.0.0
 */

frappe.listview_settings['API Audit Log'] = {
	onload(listview) {
		// Check if user has Verenigingen Administrator role
		const has_admin_role = frappe.user_roles.includes('Verenigingen Administrator');

		if (has_admin_role) {
			// Add "Clear All Logs" button for administrators
			listview.page.add_inner_button(
				__('Clear All Logs'),
				() => {
					frappe.confirm(
						__('Are you sure you want to delete ALL API Audit Log entries? This action cannot be undone.'),
						() => {
							// User confirmed - proceed with clearing logs
							frappe.call({
								method: 'verenigingen.verenigingen.doctype.api_audit_log.api_audit_log.clear_all_audit_logs',
								freeze: true,
								freeze_message: __('Clearing all API Audit Logs...'),
								callback(r) {
									if (r.message && r.message.success) {
										frappe.show_alert(
											{
												message: __('Successfully deleted {0} audit log entries', [
													r.message.deleted_count
												]),
												indicator: 'green'
											},
											5
										);

										// Refresh the list view
										listview.refresh();
									} else {
										frappe.msgprint({
											title: __('Clear Logs Failed'),
											message:
												r.message && r.message.message
													? r.message.message
													: __('Failed to clear audit logs. Check permissions.'),
											indicator: 'red'
										});
									}
								},
								error(r) {
									frappe.msgprint({
										title: __('Error'),
										message: __('An error occurred while clearing audit logs: {0}', [
											r.message || 'Unknown error'
										]),
										indicator: 'red'
									});
								}
							});
						},
						() => {
							// User cancelled
							frappe.show_alert(
								{
									message: __('Clear logs cancelled'),
									indicator: 'orange'
								},
								3
							);
						}
					);
				},
				__('Actions')
			);
		}
	},

	// Add severity-based color indicators in list view
	get_indicator(doc) {
		const severity_colors = {
			info: 'blue',
			warning: 'orange',
			error: 'red',
			critical: 'purple'
		};

		if (doc.severity) {
			return [
				__(doc.severity.toUpperCase()),
				severity_colors[doc.severity] || 'gray',
				`severity,=,${doc.severity}`
			];
		}
	}
};
