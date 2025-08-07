/**
 * @fileoverview E-Boekhouden Settings DocType Controller for Verenigingen Association Management
 *
 * This controller manages the configuration and testing of E-Boekhouden integration
 * settings, providing API connection management, migration testing capabilities,
 * cost center mapping and creation, and comprehensive validation of accounting system integration.
 *
 * @description Business Context:
 * E-Boekhouden Settings configures the integration between the association management
 * system and the E-Boekhouden accounting platform, enabling:
 * - Automated financial data synchronization
 * - Chart of accounts mapping and validation
 * - Member and donation data migration from E-Boekhouden
 * - Real-time connection testing and status monitoring
 * - Company and cost center configuration for proper accounting allocation
 * - Phase 2: Intelligent cost center creation from account groups
 *
 * @description Key Features:
 * - REST API connection testing with real-time validation
 * - Chart of Accounts preview and verification
 * - Migration test capabilities with detailed reporting
 * - Automatic cost center assignment based on company selection
 * - Cost center mapping configuration and intelligent suggestions
 * - Cost center creation engine with preview and validation
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
 * @version 2025-08-07 - Phase 2: Cost Center Creation Engine
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
 * // - Cost center parsing and intelligent suggestions
 * // - Cost center creation with preview and batch processing
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

		// Phase 2: Cost Center Creation Engine buttons
		if (frm.doc.cost_center_mappings && frm.doc.cost_center_mappings.length > 0) {
			// Add preview button
			frm.add_custom_button(__('Preview Cost Center Creation'), () => {
				frappe.call({
					method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.preview_cost_center_creation',
					callback(r) {
						if (r.message && r.message.success) {
							frm.show_cost_center_preview(r.message);
						} else {
							frappe.msgprint({
								title: 'Preview Failed',
								message: r.message.error || 'Failed to preview cost center creation',
								indicator: 'red'
							});
						}
					}
				});
			}).addClass('btn-info');

			// Add create button
			frm.add_custom_button(__('Create Cost Centers'), () => {
				frappe.confirm(
					__('This will create actual Cost Centers in ERPNext based on your configuration. This action cannot be undone. Continue?'),
					() => {
						frappe.call({
							method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.create_cost_centers_from_mappings',
							callback(r) {
								if (r.message && r.message.success) {
									frm.show_cost_center_results(r.message);
								} else {
									frappe.msgprint({
										title: 'Creation Failed',
										message: r.message.error || 'Failed to create cost centers',
										indicator: 'red'
									});
								}
							}
						});
					},
					() => {
						// User cancelled
					}
				);
			}).addClass('btn-success');
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

		// Helper function to show cost center preview results
		frm.show_cost_center_preview = function (results) {
			const preview_html = `
				<div class="cost-center-preview">
					<h5>Cost Center Creation Preview</h5>
					<div class="row">
						<div class="col-md-4">
							<div class="preview-stat">
								<h6>Total to Process</h6>
								<span class="badge badge-primary">${results.total_to_process}</span>
							</div>
						</div>
						<div class="col-md-4">
							<div class="preview-stat">
								<h6>Would Create</h6>
								<span class="badge badge-success">${results.would_create}</span>
							</div>
						</div>
						<div class="col-md-4">
							<div class="preview-stat">
								<h6>Would Skip</h6>
								<span class="badge badge-warning">${results.would_skip}</span>
							</div>
						</div>
					</div>
					<hr>
					<h6>Detailed Preview:</h6>
					<div class="preview-table" style="max-height: 400px; overflow-y: auto;">
						<table class="table table-sm table-bordered">
							<thead>
								<tr>
									<th>Group</th>
									<th>Cost Center Name</th>
									<th>Action</th>
									<th>Type</th>
								</tr>
							</thead>
							<tbody>
								${results.preview_results.map(item => `
									<tr>
										<td><code>${item.group_code}</code><br><small class="text-muted">${item.group_name}</small></td>
										<td>
											<strong>${item.cost_center_name}</strong>
											${item.parent_cost_center ? `<br><small class="text-muted">Parent: ${item.parent_cost_center}</small>` : ''}
										</td>
										<td>
											<span class="badge ${item.already_exists ? 'badge-warning' : 'badge-success'}">
												${item.action}
											</span>
											${item.existing_id ? `<br><small class="text-muted">Existing: ${item.existing_id}</small>` : ''}
										</td>
										<td>
											<span class="badge ${item.is_group ? 'badge-info' : 'badge-light'}">
												${item.is_group ? 'Group' : 'Leaf'}
											</span>
										</td>
									</tr>
								`).join('')}
							</tbody>
						</table>
					</div>
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Cost Center Creation Preview',
				fields: [{
					fieldtype: 'HTML',
					options: preview_html
				}],
				primary_action_label: 'Close',
				primary_action() { dialog.hide(); }
			});
			dialog.show();
		};

		// Helper function to show cost center creation results
		frm.show_cost_center_results = function (results) {
			const results_html = `
				<div class="cost-center-results">
					<h5>Cost Center Creation Results</h5>
					<div class="row">
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Total Processed</h6>
								<span class="badge badge-primary">${results.total_processed}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Successfully Created</h6>
								<span class="badge badge-success">${results.created_count}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Skipped</h6>
								<span class="badge badge-warning">${results.skipped_count}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Failed</h6>
								<span class="badge badge-danger">${results.failed_count}</span>
							</div>
						</div>
					</div>
					<hr>

					${results.created_count > 0 ? `
						<h6 class="text-success">Successfully Created Cost Centers:</h6>
						<div class="created-list" style="max-height: 200px; overflow-y: auto; margin-bottom: 20px;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group</th><th>Cost Center</th><th>Type</th></tr>
								</thead>
								<tbody>
									${results.created_cost_centers.map(item => `
										<tr>
											<td><code>${item.group_code}</code></td>
											<td>
												<strong>${item.cost_center_name}</strong><br>
												<small class="text-muted">${item.cost_center_id}</small>
											</td>
											<td>
												<span class="badge ${item.is_group ? 'badge-info' : 'badge-light'}">
													${item.is_group ? 'Group' : 'Leaf'}
												</span>
											</td>
										</tr>
									`).join('')}
								</tbody>
							</table>
						</div>
					` : ''}

					${results.skipped_count > 0 ? `
						<h6 class="text-warning">Skipped (Already Exist):</h6>
						<div class="skipped-list" style="max-height: 200px; overflow-y: auto; margin-bottom: 20px;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group</th><th>Cost Center</th><th>Reason</th></tr>
								</thead>
								<tbody>
									${results.skipped_cost_centers.map(item => `
										<tr>
											<td><code>${item.group_code}</code></td>
											<td><strong>${item.cost_center_name}</strong></td>
											<td><small class="text-muted">${item.reason}</small></td>
										</tr>
									`).join('')}
								</tbody>
							</table>
						</div>
					` : ''}

					${results.failed_count > 0 ? `
						<h6 class="text-danger">Failed:</h6>
						<div class="failed-list" style="max-height: 200px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group</th><th>Cost Center</th><th>Error</th></tr>
								</thead>
								<tbody>
									${results.failed_cost_centers.map(item => `
										<tr>
											<td><code>${item.group_code}</code></td>
											<td><strong>${item.cost_center_name}</strong></td>
											<td><small class="text-danger">${item.error}</small></td>
										</tr>
									`).join('')}
								</tbody>
							</table>
						</div>
					` : ''}
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Cost Center Creation Results',
				size: 'large',
				fields: [{
					fieldtype: 'HTML',
					options: results_html
				}],
				primary_action_label: 'Close',
				primary_action() { dialog.hide(); }
			});
			dialog.show();

			// Show summary message
			if (results.created_count > 0) {
				frappe.show_alert({
					message: __('Created {0} cost centers successfully', [results.created_count]),
					indicator: 'green'
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
	},

	parse_groups_button(frm) {
		// Parse the account group mappings and suggest cost centers
		if (!frm.doc.account_group_mappings) {
			frappe.msgprint(__('Please enter account group mappings first.'));
			return;
		}

		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers',
			args: {
				group_mappings_text: frm.doc.account_group_mappings,
				company: frm.doc.default_company
			},
			callback(r) {
				if (r.message && r.message.success) {
					// Clear existing mappings
					frm.clear_table('cost_center_mappings');

					// Add suggested mappings
					r.message.suggestions.forEach((suggestion) => {
						const row = frm.add_child('cost_center_mappings');
						row.group_code = suggestion.group_code;
						row.group_name = suggestion.group_name;
						row.create_cost_center = suggestion.create_cost_center;
						row.cost_center_name = suggestion.cost_center_name;
						row.is_group = suggestion.is_group;
						row.suggestion_reason = suggestion.reason;
						row.account_count = suggestion.account_count || 0;
					});

					frm.refresh_field('cost_center_mappings');

					frappe.show_alert({
						message: __('Parsed {0} groups with {1} cost center suggestions',
							[r.message.total_groups, r.message.suggested_count]),
						indicator: 'green'
					});

					// Expand the cost center section
					frm.toggle_display('cost_center_section', true);
				} else {
					frappe.msgprint({
						title: 'Parse Failed',
						message: r.message.error || 'Failed to parse account groups',
						indicator: 'red'
					});
				}
			}
		});
	}
});

// Add help text
frappe.ui.form.on('E-Boekhouden Settings', 'onload', (frm) => {
	frm.set_intro(__('Configure your e-Boekhouden API token to enable data migration to ERPNext. You can find your API token in your e-Boekhouden account settings under "API Access" or "Integrations".'));
});
