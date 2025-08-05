/**
 * @fileoverview E-Boekhouden Settings DocType Controller for Verenigingen Association Management
 *
 * This controller manages the configuration and testing of E-Boekhouden integration
 * settings, providing API connection management, migration testing capabilities,
 * and comprehensive validation of accounting system integration.
 *
 * @description Business Context:
 * E-Boekhouden Settings configures the integration between the association management
 * system and the E-Boekhouden accounting platform, enabling:
 * - Automated financial data synchronization
 * - Chart of accounts mapping and validation
 * - Member and donation data migration from E-Boekhouden
 * - Real-time connection testing and status monitoring
 * - Company and cost center configuration for proper accounting allocation
 *
 * @description Key Features:
 * - REST API connection testing with real-time validation
 * - Chart of Accounts preview and verification
 * - Migration test capabilities with detailed reporting
 * - Automatic cost center assignment based on company selection
 * - Comprehensive error handling and user feedback
 * - Secure API token management and validation
 *
 * @description Integration Points:
 * - E-Boekhouden REST API for data retrieval and synchronization
 * - ERPNext Company and Cost Center for accounting allocation
 * - Migration utilities for data import and transformation
 * - Chart of Accounts mapping for financial integration
 * - Error logging and audit trail systems
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.ui.form
 * @requires frappe.call
 * @requires frappe.ui.Dialog
 *
 * @example
 * // The controller automatically handles:
 * // - API connection testing with status feedback
 * // - Chart of accounts preview and validation
 * // - Company-based cost center auto-assignment
 * // - Migration testing with detailed result reporting
 */

// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('E-Boekhouden Settings', {
	refresh(frm) {
		// Add custom buttons for testing
		frm.add_custom_button(__('Test REST API Connection'), () => {
			if (!frm.doc.api_token) {
				frappe.msgprint(__('Please enter your API token first.'));
				return;
			}

			frappe.call({
				method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.test_connection',
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Connection test successful!'),
							indicator: 'green'
						});
					} else {
						frappe.show_alert({
							message: __('Connection test failed. Check your API token.'),
							indicator: 'red'
						});
					}
					frm.reload_doc();
				}
			});
		}).addClass('btn-primary');


		// Add test API call buttons
		if (frm.doc.connection_status && frm.doc.connection_status.includes('✅')) {
			frm.add_custom_button(__('Test Chart of Accounts'), () => {
				frappe.call({
					method: 'verenigingen.e_boekhouden.utils.eboekhouden_api.preview_chart_of_accounts',
					callback(r) {
						if (r.message && r.message.success) {
							const dialog = new frappe.ui.Dialog({
								title: 'Chart of Accounts Preview',
								fields: [{
									fieldtype: 'HTML',
									options: `<div class="text-muted">
										<h5>Found ${r.message.total_count} accounts:</h5>
										<pre style="max-height: 400px; overflow-y: auto; background: #f8f9fa; padding: 10px; border-radius: 3px;">${JSON.stringify(r.message.accounts, null, 2)}</pre>
									</div>`
								}],
								primary_action_label: 'Close',
								primary_action() { dialog.hide(); }
							});
							dialog.show();
						} else {
							frappe.msgprint({
								title: 'API Test Failed',
								message: r.message.error || 'Unknown error occurred',
								indicator: 'red'
							});
						}
					}
				});
			});
		}

		// Helper function for showing migration test results
		frm.show_migration_test_results = function (r, type) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: `${type} Migration Test Results`,
					message: `
						<div>
							<p><strong>Result:</strong> ${r.message.result}</p>
							<p><strong>Total Records:</strong> ${r.message.total_records}</p>
							<p><strong>Would Import:</strong> ${r.message.imported_records}</p>
							<p><strong>Failures:</strong> ${r.message.failed_records}</p>
						</div>
					`,
					indicator: 'blue'
				});
			} else {
				frappe.msgprint({
					title: `${type} Migration Test Failed`,
					message: r.message.error || 'Unknown error occurred',
					indicator: 'red'
				});
			}
		};
	},

	default_company(frm) {
		// Auto-set cost center when company changes
		if (frm.doc.default_company) {
			frappe.db.get_value('Cost Center',
				{ company: frm.doc.default_company, is_group: 0 },
				'name'
			).then(r => {
				if (r.message && r.message.name) {
					frm.set_value('default_cost_center', r.message.name);
				}
			});
		}
	}
});

// Add help text
frappe.ui.form.on('E-Boekhouden Settings', 'onload', (frm) => {
	frm.set_intro(__('Configure your e-Boekhouden API token to enable data migration to ERPNext. You can find your API token in your e-Boekhouden account settings under "API Access" or "Integrations".'));
});
