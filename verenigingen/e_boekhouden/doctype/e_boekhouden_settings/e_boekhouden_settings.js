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
		verenigingen.suppressPasswordAutofill(frm, ['api_token']);

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

		// Group Type Mapping buttons - for re-classifying existing accounts
		if (frm.doc.group_type_mappings && frm.doc.group_type_mappings.length > 0) {
			// Account Types menu (classification - root_type and account_type)
			frm.add_custom_button(
				__('Preview Re-classification'),
				() => {
					frappe.call({
						method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.reclassify_accounts_by_group_mappings',
						args: { dry_run: true },
						callback(r) {
							if (r.message && r.message.success) {
								frm.show_reclassify_preview(r.message);
							} else {
								frappe.msgprint({
									title: 'Preview Failed',
									message: r.message.error || 'Failed to preview account re-classification',
									indicator: 'red'
								});
							}
						}
					});
				},
				__('Account Types')
			);

			frm.add_custom_button(
				__('Apply Re-classification'),
				() => {
					frappe.confirm(
						__(
							'This will update account types for existing accounts based on your group type mappings. This affects financial reporting. Continue?'
						),
						() => {
							frappe.call({
								method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.reclassify_accounts_by_group_mappings',
								args: { dry_run: false },
								callback(r) {
									if (r.message && r.message.success) {
										frm.show_reclassify_results(r.message);
									} else {
										frappe.msgprint({
											title: 'Re-classification Failed',
											message: r.message.error || 'Failed to re-classify accounts',
											indicator: 'red'
										});
									}
								}
							});
						}
					);
				},
				__('Account Types')
			);

			// Account Hierarchy menu (parent-child organization)
			frm.add_custom_button(
				__('Preview Reorganization'),
				() => {
					frappe.call({
						method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.reorganize_account_hierarchy',
						args: { dry_run: true },
						callback(r) {
							if (r.message && r.message.success) {
								frm.show_hierarchy_preview(r.message);
							} else {
								frappe.msgprint({
									title: 'Preview Failed',
									message: r.message.error || 'Failed to preview hierarchy reorganization',
									indicator: 'red'
								});
							}
						}
					});
				},
				__('Account Hierarchy')
			);

			frm.add_custom_button(
				__('Apply Reorganization'),
				() => {
					frappe.confirm(
						__(
							'This will reorganize the Chart of Accounts hierarchy, moving accounts under their group parent accounts based on your group type mappings. Continue?'
						),
						() => {
							frappe.call({
								method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.reorganize_account_hierarchy',
								args: { dry_run: false },
								callback(r) {
									if (r.message && r.message.success) {
										frm.show_hierarchy_results(r.message);
									} else {
										frappe.msgprint({
											title: 'Reorganization Failed',
											message: r.message.error || 'Failed to reorganize account hierarchy',
											indicator: 'red'
										});
									}
								}
							});
						}
					);
				},
				__('Account Hierarchy')
			);
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
					__(
						'This will create actual Cost Centers in ERPNext based on your configuration. This action cannot be undone. Continue?'
					),
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
								${results.preview_results
									.map(
										(item) => `
									<tr>
										<td><code>${frm.escape_html(item.group_code)}</code><br><small class="text-muted">${frm.escape_html(item.group_name)}</small></td>
										<td>
											<strong>${frm.escape_html(item.cost_center_name)}</strong>
											${item.parent_cost_center ? `<br><small class="text-muted">Parent: ${frm.escape_html(item.parent_cost_center)}</small>` : ''}
										</td>
										<td>
											<span class="badge ${item.already_exists ? 'badge-warning' : 'badge-success'}">
												${frm.escape_html(item.action)}
											</span>
											${item.existing_id ? `<br><small class="text-muted">Existing: ${frm.escape_html(item.existing_id)}</small>` : ''}
										</td>
										<td>
											<span class="badge ${item.is_group ? 'badge-info' : 'badge-light'}">
												${item.is_group ? 'Group' : 'Leaf'}
											</span>
										</td>
									</tr>
								`
									)
									.join('')}
							</tbody>
						</table>
					</div>
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Cost Center Creation Preview',
				fields: [
					{
						fieldtype: 'HTML',
						options: preview_html
					}
				],
				primary_action_label: 'Close',
				primary_action() {
					dialog.hide();
				}
			});
			dialog.show();
		};

		// Helper function to escape HTML for safe rendering
		frm.escape_html = function (str) {
			if (!str) {
				return '';
			}
			return String(str)
				.replace(/&/g, '&amp;')
				.replace(/</g, '&lt;')
				.replace(/>/g, '&gt;')
				.replace(/"/g, '&quot;')
				.replace(/'/g, '&#39;');
		};

		// Helper function to show re-classification preview
		frm.show_reclassify_preview = function (results) {
			const changes_to_show = results.changes.filter((c) => c.status === 'would_update');
			const skipped_no_mapping = results.changes.filter((c) => c.status === 'skipped' && c.reason);

			const preview_html = `
				<div class="reclassify-preview">
					<h5>Account Re-classification Preview</h5>
					<div class="row">
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Total Accounts</h6>
								<span class="badge badge-primary">${results.total_accounts}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Would Update</h6>
								<span class="badge badge-success">${results.would_update}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Skipped</h6>
								<span class="badge badge-secondary">${results.skipped}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Mappings Used</h6>
								<span class="badge badge-info">${results.mappings_used}</span>
							</div>
						</div>
					</div>
					${
						changes_to_show.length > 0
							? `
						<hr>
						<h6>Accounts to Update:</h6>
						<div class="preview-table" style="max-height: 300px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr>
										<th>Account</th>
										<th>Group</th>
										<th>Current Type</th>
										<th>New Type</th>
									</tr>
								</thead>
								<tbody>
									${changes_to_show
										.map(
											(item) => `
										<tr>
											<td>
												<code>${frm.escape_html(item.account)}</code><br>
												<small class="text-muted">${frm.escape_html(item.account_name)}</small>
											</td>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td>
												<span class="text-danger">${frm.escape_html(item.old_root_type || '-')}/${frm.escape_html(item.old_account_type || '-')}</span>
											</td>
											<td>
												<span class="text-success">${frm.escape_html(item.new_root_type || '-')}/${frm.escape_html(item.new_account_type || '-')}</span>
											</td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: '<p class="text-muted">No accounts need updating.</p>'
					}
					${
						skipped_no_mapping.length > 0
							? `
						<hr>
						<h6 class="text-warning">Skipped (No Mapping):</h6>
						<div style="max-height: 150px; overflow-y: auto;">
							<small class="text-muted">
								${skipped_no_mapping
									.slice(0, 20)
									.map(
										(item) =>
											`${frm.escape_html(item.account)} (group ${frm.escape_html(item.group_code)})`
									)
									.join(', ')}
								${skipped_no_mapping.length > 20 ? `... and ${skipped_no_mapping.length - 20} more` : ''}
							</small>
						</div>
					`
							: ''
					}
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Account Re-classification Preview',
				size: 'large',
				fields: [{ fieldtype: 'HTML', options: preview_html }],
				primary_action_label: 'Close',
				primary_action() {
					dialog.hide();
				}
			});
			dialog.show();
		};

		// Helper function to show re-classification results
		frm.show_reclassify_results = function (results) {
			const updated = results.changes.filter((c) => c.status === 'updated');
			const errors = results.changes.filter((c) => c.status === 'error');

			const results_html = `
				<div class="reclassify-results">
					<h5>Account Re-classification Results</h5>
					<div class="row">
						<div class="col-md-4">
							<div class="result-stat">
								<h6>Total Processed</h6>
								<span class="badge badge-primary">${results.total_accounts}</span>
							</div>
						</div>
						<div class="col-md-4">
							<div class="result-stat">
								<h6>Updated</h6>
								<span class="badge badge-success">${results.updated}</span>
							</div>
						</div>
						<div class="col-md-4">
							<div class="result-stat">
								<h6>Skipped</h6>
								<span class="badge badge-secondary">${results.skipped}</span>
							</div>
						</div>
					</div>
					${
						updated.length > 0
							? `
						<hr>
						<h6 class="text-success">Successfully Updated:</h6>
						<div style="max-height: 250px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Account</th><th>Old Type</th><th>New Type</th></tr>
								</thead>
								<tbody>
									${updated
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.account)}</code> - ${frm.escape_html(item.account_name)}</td>
											<td><span class="text-muted">${frm.escape_html(item.old_root_type)}/${frm.escape_html(item.old_account_type || '-')}</span></td>
											<td><span class="text-success">${frm.escape_html(item.new_root_type)}/${frm.escape_html(item.new_account_type || '-')}</span></td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
					${
						errors.length > 0
							? `
						<hr>
						<h6 class="text-danger">Errors:</h6>
						<div style="max-height: 150px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<tbody>
									${errors
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.account)}</code></td>
											<td class="text-danger">${frm.escape_html(item.error)}</td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Account Re-classification Results',
				size: 'large',
				fields: [{ fieldtype: 'HTML', options: results_html }],
				primary_action_label: 'Close',
				primary_action() {
					dialog.hide();
				}
			});
			dialog.show();

			if (results.updated > 0) {
				frappe.show_alert({
					message: __('Updated {0} accounts successfully', [results.updated]),
					indicator: 'green'
				});
			}
		};

		// Helper function to show hierarchy reorganization preview
		frm.show_hierarchy_preview = function (results) {
			const moves_to_show = results.changes.filter((c) => c.status === 'would_move');
			const groups_to_create = results.groups.filter((g) => g.status === 'would_create');

			const preview_html = `
				<div class="hierarchy-preview">
					<h5>Account Hierarchy Reorganization Preview</h5>
					<div class="row">
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Total Accounts</h6>
								<span class="badge badge-primary">${results.total_accounts}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Would Move</h6>
								<span class="badge badge-success">${results.would_move}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Groups to Create</h6>
								<span class="badge badge-info">${results.groups_created}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="preview-stat">
								<h6>Skipped</h6>
								<span class="badge badge-secondary">${results.skipped}</span>
							</div>
						</div>
					</div>
					${
						groups_to_create.length > 0
							? `
						<hr>
						<h6>Group Accounts to Create:</h6>
						<div class="preview-table" style="max-height: 150px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr>
										<th>Group Code</th>
										<th>Group Name</th>
										<th>Root Type</th>
										<th>Parent</th>
									</tr>
								</thead>
								<tbody>
									${groups_to_create
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td><strong>${frm.escape_html(item.group_name)}</strong></td>
											<td><span class="badge badge-light">${frm.escape_html(item.root_type)}</span></td>
											<td><small class="text-muted">${frm.escape_html(item.parent)}</small></td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
					${
						moves_to_show.length > 0
							? `
						<hr>
						<h6>Accounts to Move:</h6>
						<div class="preview-table" style="max-height: 300px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr>
										<th>Account</th>
										<th>Group</th>
										<th>Current Parent</th>
										<th>New Parent</th>
									</tr>
								</thead>
								<tbody>
									${moves_to_show
										.map(
											(item) => `
										<tr>
											<td>
												<code>${frm.escape_html(item.account)}</code><br>
												<small class="text-muted">${frm.escape_html(item.account_name)}</small>
											</td>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td>
												<span class="text-danger">${frm.escape_html(item.old_parent || '-')}</span>
											</td>
											<td>
												<span class="text-success">${frm.escape_html(item.new_parent_name)}</span>
											</td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: '<p class="text-muted">No accounts need to be moved.</p>'
					}
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Account Hierarchy Reorganization Preview',
				size: 'large',
				fields: [{ fieldtype: 'HTML', options: preview_html }],
				primary_action_label: 'Close',
				primary_action() {
					dialog.hide();
				}
			});
			dialog.show();
		};

		// Helper function to show hierarchy reorganization results
		frm.show_hierarchy_results = function (results) {
			const moved = results.changes.filter((c) => c.status === 'moved');
			const errors = results.changes.filter((c) => c.status === 'error');
			const groups_created = results.groups.filter((g) => g.status === 'created');

			const results_html = `
				<div class="hierarchy-results">
					<h5>Account Hierarchy Reorganization Results</h5>
					<div class="row">
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Total Processed</h6>
								<span class="badge badge-primary">${results.total_accounts}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Moved</h6>
								<span class="badge badge-success">${results.moved}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Groups Created</h6>
								<span class="badge badge-info">${results.groups_created}</span>
							</div>
						</div>
						<div class="col-md-3">
							<div class="result-stat">
								<h6>Skipped</h6>
								<span class="badge badge-secondary">${results.skipped}</span>
							</div>
						</div>
					</div>
					${
						groups_created.length > 0
							? `
						<hr>
						<h6 class="text-info">Created Group Accounts:</h6>
						<div style="max-height: 150px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group Code</th><th>Group Name</th><th>Root Type</th></tr>
								</thead>
								<tbody>
									${groups_created
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td><strong>${frm.escape_html(item.group_name)}</strong></td>
											<td>${frm.escape_html(item.root_type)}</td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
					${
						moved.length > 0
							? `
						<hr>
						<h6 class="text-success">Successfully Moved:</h6>
						<div style="max-height: 250px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Account</th><th>Old Parent</th><th>New Parent</th></tr>
								</thead>
								<tbody>
									${moved
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.account)}</code> - ${frm.escape_html(item.account_name)}</td>
											<td><span class="text-muted">${frm.escape_html(item.old_parent || '-')}</span></td>
											<td><span class="text-success">${frm.escape_html(item.new_parent_name)}</span></td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
					${
						errors.length > 0
							? `
						<hr>
						<h6 class="text-danger">Errors:</h6>
						<div style="max-height: 150px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<tbody>
									${errors
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.account)}</code></td>
											<td class="text-danger">${frm.escape_html(item.error)}</td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Account Hierarchy Reorganization Results',
				size: 'large',
				fields: [{ fieldtype: 'HTML', options: results_html }],
				primary_action_label: 'Close',
				primary_action() {
					dialog.hide();
				}
			});
			dialog.show();

			if (results.moved > 0 || results.groups_created > 0) {
				frappe.show_alert({
					message: __('Reorganized hierarchy: {0} accounts moved, {1} groups created', [
						results.moved,
						results.groups_created
					]),
					indicator: 'green'
				});
			}
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

					${
						results.created_count > 0
							? `
						<h6 class="text-success">Successfully Created Cost Centers:</h6>
						<div class="created-list" style="max-height: 200px; overflow-y: auto; margin-bottom: 20px;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group</th><th>Cost Center</th><th>Type</th></tr>
								</thead>
								<tbody>
									${results.created_cost_centers
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td>
												<strong>${frm.escape_html(item.cost_center_name)}</strong><br>
												<small class="text-muted">${frm.escape_html(item.cost_center_id)}</small>
											</td>
											<td>
												<span class="badge ${item.is_group ? 'badge-info' : 'badge-light'}">
													${item.is_group ? 'Group' : 'Leaf'}
												</span>
											</td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}

					${
						results.skipped_count > 0
							? `
						<h6 class="text-warning">Skipped (Already Exist):</h6>
						<div class="skipped-list" style="max-height: 200px; overflow-y: auto; margin-bottom: 20px;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group</th><th>Cost Center</th><th>Reason</th></tr>
								</thead>
								<tbody>
									${results.skipped_cost_centers
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td><strong>${frm.escape_html(item.cost_center_name)}</strong></td>
											<td><small class="text-muted">${frm.escape_html(item.reason)}</small></td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}

					${
						results.failed_count > 0
							? `
						<h6 class="text-danger">Failed:</h6>
						<div class="failed-list" style="max-height: 200px; overflow-y: auto;">
							<table class="table table-sm table-bordered">
								<thead>
									<tr><th>Group</th><th>Cost Center</th><th>Error</th></tr>
								</thead>
								<tbody>
									${results.failed_cost_centers
										.map(
											(item) => `
										<tr>
											<td><code>${frm.escape_html(item.group_code)}</code></td>
											<td><strong>${frm.escape_html(item.cost_center_name)}</strong></td>
											<td><small class="text-danger">${frm.escape_html(item.error)}</small></td>
										</tr>
									`
										)
										.join('')}
								</tbody>
							</table>
						</div>
					`
							: ''
					}
				</div>
			`;

			const dialog = new frappe.ui.Dialog({
				title: 'Cost Center Creation Results',
				size: 'large',
				fields: [
					{
						fieldtype: 'HTML',
						options: results_html
					}
				],
				primary_action_label: 'Close',
				primary_action() {
					dialog.hide();
				}
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
			frappe.db.get_value('Cost Center', { company: frm.doc.default_company, is_group: 0 }, 'name').then((r) => {
				if (r.message && r.message.name) {
					frm.set_value('default_cost_center', r.message.name);
				}
			});
		}
	},

	rebuild_account_tree_button(frm) {
		// Rebuild account tree structure based on current settings
		if (!frm.doc.default_company) {
			frappe.msgprint(__('Please select a default company first.'));
			return;
		}

		frappe.confirm(
			__(
				'This will reorganize all accounts under the configured group accounts (Vorderingen, Financial Accounts, Overlopende activa, Schulden, Belastingen). Continue?'
			),
			() => {
				frappe.call({
					method: 'verenigingen.e_boekhouden.services.account_organization_service.organize_balance_sheet_accounts',
					args: {
						company: frm.doc.default_company
					},
					callback(r) {
						if (r.message && r.message.success) {
							const details = r.message.details;
							let message = `<div class="text-muted">
								<h5>Account Tree Rebuilt Successfully</h5>
								<p><strong>Groups Created/Updated:</strong></p>
								<ul>`;

							details.created_groups.forEach((group) => {
								message += `<li>${frm.escape_html(group)}</li>`;
							});

							message += `</ul>
								<p><strong>Accounts Reorganized:</strong> ${details.updated.length}</p>`;

							if (details.updated.length > 0) {
								message += `<ul>`;
								details.updated.slice(0, 10).forEach((update) => {
									message += `<li>${frm.escape_html(update)}</li>`;
								});
								if (details.updated.length > 10) {
									message += `<li><em>... and ${details.updated.length - 10} more</em></li>`;
								}
								message += `</ul>`;
							}

							if (details.errors.length > 0) {
								message += `<p class="text-danger"><strong>Errors:</strong></p><ul>`;
								details.errors.forEach((error) => {
									message += `<li>${frm.escape_html(error)}</li>`;
								});
								message += `</ul>`;
							}

							message += `</div>`;

							frappe.msgprint({
								title: __('Account Tree Rebuilt'),
								message,
								indicator: 'green'
							});
						} else {
							frappe.msgprint({
								title: __('Rebuild Failed'),
								message: r.message.error || __('Failed to rebuild account tree'),
								indicator: 'red'
							});
						}
					}
				});
			}
		);
	},

	parse_groups_button(frm) {
		// Parse the account group mappings and suggest cost centers
		const balance_sheet_mappings = frm.doc.balance_sheet_group_mappings || '';
		const pl_mappings = frm.doc.pl_group_mappings || '';

		if (!balance_sheet_mappings && !pl_mappings) {
			frappe.msgprint(__('Please enter balance sheet or P/L group mappings first.'));
			return;
		}

		// Only use P&L mappings for cost centers - balance sheet accounts don't need cost centers
		const cost_center_mappings = pl_mappings;

		if (!cost_center_mappings || !cost_center_mappings.trim()) {
			frappe.msgprint(__('Please enter P&L group mappings. Balance sheet accounts do not require cost centers.'));
			return;
		}

		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_cost_centers',
			args: {
				group_mappings_text: cost_center_mappings,
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
						message: __('Parsed {0} groups with {1} cost center suggestions', [
							r.message.total_groups,
							r.message.suggested_count
						]),
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
	},

	parse_group_types_button(frm) {
		// Parse the account group mappings and suggest account type mappings
		const balance_sheet_mappings = frm.doc.balance_sheet_group_mappings || '';
		const pl_mappings = frm.doc.pl_group_mappings || '';

		if (!balance_sheet_mappings && !pl_mappings) {
			frappe.msgprint(__('Please enter Balance Sheet or P&L group mappings first.'));
			return;
		}

		// Helper function to actually do the parsing
		const do_parse = (merge_mode) => {
			frappe.call({
				method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_settings.e_boekhouden_settings.parse_groups_and_suggest_type_mappings',
				args: { merge_mode },
				callback(r) {
					if (r.message && r.message.success) {
						// Show duplicate warnings if any
						if (r.message.duplicates && r.message.duplicates.length > 0) {
							const dup_list = r.message.duplicates
								.map(
									(d) =>
										`<li>Code <code>${frm.escape_html(d.code)}</code>: "${frm.escape_html(d.name)}" duplicates "${frm.escape_html(d.existing_name)}"</li>`
								)
								.join('');
							frappe.msgprint({
								title: __('Duplicate Groups Found'),
								message: `<p>The following duplicate group codes were found in the source text and skipped:</p><ul>${dup_list}</ul>`,
								indicator: 'orange'
							});
						}

						if (!merge_mode) {
							// Replace mode: clear existing mappings
							frm.clear_table('group_type_mappings');
						}

						// Add suggested mappings
						r.message.suggestions.forEach((suggestion) => {
							const row = frm.add_child('group_type_mappings');
							row.group_code = suggestion.group_code;
							row.group_name = suggestion.group_name;
							row.root_type = suggestion.root_type;
							row.account_type = suggestion.account_type;
							row.confidence = suggestion.confidence;
							row.notes = suggestion.notes;
						});

						frm.refresh_field('group_type_mappings');

						let msg = __('Parsed {0} groups with {1} type suggestions', [
							r.message.total_groups,
							r.message.suggested_count
						]);
						if (merge_mode && r.message.skipped_existing > 0) {
							msg += __(', skipped {0} existing', [r.message.skipped_existing]);
						}

						frappe.show_alert({
							message: msg,
							indicator: 'green'
						});

						// Mark form as dirty so user knows to save
						frm.dirty();
					} else {
						frappe.msgprint({
							title: 'Parse Failed',
							message: r.message.error || 'Failed to parse account groups for type mappings',
							indicator: 'red'
						});
					}
				}
			});
		};

		// Check if there are existing mappings - offer merge mode
		const has_existing = frm.doc.group_type_mappings && frm.doc.group_type_mappings.length > 0;

		if (has_existing) {
			const dialog = new frappe.ui.Dialog({
				title: __('Parse Group Types'),
				fields: [
					{
						fieldtype: 'HTML',
						options: `<p>You have <strong>${frm.doc.group_type_mappings.length}</strong> existing group type mappings.</p>`
					},
					{
						fieldname: 'mode',
						fieldtype: 'Select',
						label: __('Parse Mode'),
						options: [
							{ value: 'replace', label: __('Replace All (clear existing, add all parsed)') },
							{ value: 'merge', label: __('Merge (keep existing, add only new groups)') }
						],
						default: 'merge'
					}
				],
				primary_action_label: __('Parse'),
				primary_action(values) {
					dialog.hide();
					do_parse(values.mode === 'merge');
				}
			});
			dialog.show();
		} else {
			do_parse(false);
		}
	}
});

// Add help text
frappe.ui.form.on('E-Boekhouden Settings', 'onload', (frm) => {
	frm.set_intro(
		__(
			'Configure your e-Boekhouden API token to enable data migration to ERPNext. You can find your API token in your e-Boekhouden account settings under "API Access" or "Integrations".'
		)
	);
});
