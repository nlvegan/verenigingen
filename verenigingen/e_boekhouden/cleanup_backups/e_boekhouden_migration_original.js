/**
 * @fileoverview E-Boekhouden Migration DocType JavaScript (Original/Backup Version)
 *
 * Original implementation of the E-Boekhouden Migration DocType frontend controller,
 * preserved as a backup/reference version. This file contains the complete migration
 * workflow management interface for importing financial data from the E-Boekhouden
 * accounting system into the ERPNext/Frappe framework.
 *
 * Key Functionality:
 * - API connection testing and validation
 * - Migration preview with data sampling
 * - Full migration execution with progress tracking
 * - Error handling and rollback capabilities
 * - Status monitoring and user feedback
 * - Record count tracking and validation
 *
 * Migration Workflow:
 * 1. Connection validation to E-Boekhouden API
 * 2. Preview mode for data structure validation
 * 3. Full migration execution with progress updates
 * 4. Error handling with detailed logging
 * 5. Status tracking throughout the process
 *
 * Business Context:
 * This controller manages the complex process of migrating financial data
 * from E-Boekhouden to ERPNext, ensuring data integrity and providing
 * users with clear feedback on migration progress and any issues encountered.
 *
 * Integration Points:
 * - E-Boekhouden API utilities for data retrieval
 * - ERPNext GL Entry creation for financial records
 * - Account mapping for chart of accounts synchronization
 * - Error logging and audit trail management
 *
 * Security Considerations:
 * - API credentials validation before operations
 * - Input validation for migration parameters
 * - Error message sanitization for security
 *
 * @file Original backup version - see current implementation for active code
 * @copyright 2025, R.S.P. and contributors
 * @license See license.txt
 * @module EBoekhoudenMigrationOriginal
 * @since 2024
 */

// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('E-Boekhouden Migration', {
	refresh(frm) {
		console.log('E-Boekhouden Migration refresh called', frm.doc);
		console.log('Doc status:', frm.doc.docstatus, 'Migration status:', frm.doc.migration_status);

		// Check if we have any migration history
		const has_migrations = frm.doc.imported_records > 0 || frm.doc.total_records > 0;

		// Always show core action buttons when not submitted
		if (frm.doc.docstatus === 0) {
			// Show migration actions if not currently running
			if (frm.doc.migration_status !== 'In Progress') {
				console.log('Adding core action buttons');

				frm.add_custom_button(__('Test Connection'), () => {
					console.log('Test Connection clicked');
					frappe.call({
						method: 'verenigingen.e_boekhouden.utils.eboekhouden_api.test_api_connection',
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __('✅ Connection successful! API is working.'),
									indicator: 'green'
								});
							} else {
								frappe.show_alert({
									message: __('❌ Connection failed: ') + (r.message ? r.message.error : 'Unknown error'),
									indicator: 'red'
								});
							}
						}
					});
				}).addClass('btn-info');

				frm.add_custom_button(__('Preview Migration'), () => {
					console.log('Preview Migration button clicked');

					// Simple validation
					if (!frm.doc.migration_name) {
						frappe.msgprint(__('Migration Name is required'));
						return;
					}
					if (!frm.doc.company) {
						frappe.msgprint(__('Company is required'));
						return;
					}

					console.log('Validation passed, showing confirm dialog');
					frappe.confirm(
						__('This will preview what data would be migrated without actually importing anything. Continue?'),
						() => {
							console.log('User confirmed preview migration');

							// Use direct API call instead of form submission
							console.log('Starting preview migration via API...');

							frappe.call({
								method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.start_migration_api',
								args: {
									migration_name: frm.doc.name,
									dry_run: 1
								},
								callback(r) {
									console.log('API call completed, response:', r);

									if (r.message && r.message.success) {
										console.log('Preview migration started successfully');
										frappe.show_alert({
											message: __('✅ Preview migration started successfully!'),
											indicator: 'green'
										});

										// Reload the form to show updated status
										setTimeout(() => {
											frm.reload_doc();
										}, 1000);
									} else {
										console.error('Preview migration failed:', r.message);
										frappe.show_alert({
											message: __('❌ Preview migration failed: ') + (r.message ? r.message.error : 'Unknown error'),
											indicator: 'red'
										});
									}
								},
								error(error) {
									console.error('API call error:', error);
									frappe.show_alert({
										message: __('❌ API call failed: ') + (error.message || error),
										indicator: 'red'
									});
								}
							});
						},
						() => {
							console.log('User cancelled preview migration');
						}
					);
				}).addClass('btn-secondary');

				frm.add_custom_button(__('Start Migration'), () => {
					console.log('Start Migration button clicked');

					// Simple validation
					if (!frm.doc.migration_name) {
						frappe.msgprint(__('Migration Name is required'));
						return;
					}
					if (!frm.doc.company) {
						frappe.msgprint(__('Company is required'));
						return;
					}

					frappe.confirm(
						__('Are you sure you want to start the migration? This will import data from e-Boekhouden into ERPNext.<br><br><strong>This action cannot be undone!</strong>'),
						() => {
							console.log('User confirmed start migration');

							// Use direct API call instead of form submission
							console.log('Starting actual migration via API...');

							frappe.call({
								method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.start_migration_api',
								args: {
									migration_name: frm.doc.name,
									dry_run: 0
								},
								callback(r) {
									console.log('API call completed, response:', r);

									if (r.message && r.message.success) {
										console.log('Migration started successfully');
										frappe.show_alert({
											message: __('✅ Migration started successfully!'),
											indicator: 'green'
										});

										// Reload the form to show updated status
										setTimeout(() => {
											frm.reload_doc();
										}, 1000);
									} else {
										console.error('Migration failed:', r.message);
										frappe.show_alert({
											message: __('❌ Migration failed: ') + (r.message ? r.message.error : 'Unknown error'),
											indicator: 'red'
										});
									}
								},
								error(error) {
									console.error('API call error:', error);
									frappe.show_alert({
										message: __('❌ API call failed: ') + (error.message || error),
										indicator: 'red'
									});
								}
							});
						}
					);
				}).addClass('btn-primary');

				frm.add_custom_button(__('Full Migration'), () => {
					console.log('Full Migration button clicked');

					// Simple validation
					if (!frm.doc.company) {
						frappe.msgprint(__('Company is required'));
						return;
					}

					frappe.confirm(
						__('<h4>Full E-Boekhouden Migration</h4>'
							+ '<p>This will perform a comprehensive migration that includes:</p>'
							+ '<ul>'
							+ '<li>Automatically determine the date range from E-Boekhouden</li>'
							+ '<li>Create opening balance journal entry</li>'
							+ '<li>Migrate chart of accounts</li>'
							+ '<li>Migrate all transactions</li>'
							+ '<li>Create payment entries where applicable</li>'
							+ '</ul>'
							+ '<p><strong>⚠️ WARNING: This action cannot be undone and may take several minutes!</strong></p>'
							+ '<p>Are you sure you want to proceed?</p>'),
						() => {
							console.log('User confirmed full migration');

							// Show progress dialog
							const progress_dialog = new frappe.ui.Dialog({
								title: 'Full Migration Progress',
								fields: [{
									fieldtype: 'HTML',
									fieldname: 'progress_html',
									options: '<div id="migration-progress">'
										+ '<div class="progress">'
										+ '<div class="progress-bar progress-bar-striped active" role="progressbar" '
										+ 'style="width: 0%" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100">'
										+ '0%</div></div>'
										+ '<p class="text-muted mt-2" id="progress-message">Initializing migration...</p>'
										+ '</div>'
								}]
							});
							progress_dialog.show();
							progress_dialog.get_close_btn().hide();

							// Start full migration
							frappe.call({
								method: 'verenigingen.e_boekhouden.utils_full_migration.migrate_all_eboekhouden_data',
								callback(r) {
									progress_dialog.hide();
									console.log('Full migration completed, response:', r);

									if (r.message && r.message.success) {
										console.log('Full migration successful');

										// Show detailed summary dialog
										const summary = r.message.summary;
										let summary_html = `
										<h5>Migration Completed Successfully!</h5>
										<hr>
										<div class="row">
											<div class="col-md-6">
												<h6>Date Range:</h6>
												<p>${summary.date_range.from} to ${summary.date_range.to}<br>
												(${summary.date_range.years} years, ${summary.date_range.days} days)</p>
											</div>
											<div class="col-md-6">
												<h6>Migration Date:</h6>
												<p>${summary.migration_date}</p>
											</div>
										</div>
										<hr>
										<h6>Results Summary:</h6>
										<table class="table table-sm">
											<tr>
												<td>Chart of Accounts</td>
												<td>${summary.totals.total_accounts} accounts</td>
											</tr>
											<tr>
												<td>Journal Entries</td>
												<td>${summary.totals.total_journal_entries} created</td>
											</tr>
											<tr>
												<td>Payment Entries</td>
												<td>${summary.totals.total_payment_entries} created</td>
											</tr>
											<tr>
												<td>Total Errors</td>
												<td class="${summary.totals.total_errors > 0 ? 'text-danger' : 'text-success'}">
													${summary.totals.total_errors}
												</td>
											</tr>
										</table>
									`;

										if (summary.results.opening_balance.created) {
											summary_html += `<p><strong>Opening Balance:</strong> Created as ${summary.results.opening_balance.journal_entry}</p>`;
										}

										const result_dialog = new frappe.ui.Dialog({
											title: 'Full Migration Summary',
											fields: [{
												fieldtype: 'HTML',
												options: summary_html
											}],
											primary_action_label: 'Close',
											primary_action() {
												result_dialog.hide();
												frm.reload_doc();
											}
										});
										result_dialog.show();
									} else {
										console.error('Full migration failed:', r.message);
										frappe.msgprint({
											title: __('Migration Failed'),
											message: __('Full migration failed: ') + (r.message ? r.message.error : 'Unknown error'),
											indicator: 'red'
										});
									}
								},
								error(error) {
									progress_dialog.hide();
									console.error('Full migration error:', error);
									frappe.msgprint({
										title: __('Migration Error'),
										message: __('Full migration error: ') + (error.message || error),
										indicator: 'red'
									});
								}
							});

							// Update progress bar
							frappe.realtime.on('progress', (data) => {
								if (data.progress) {
									const percent = data.progress;
									const message = data.title || 'Processing...';

									$('#migration-progress .progress-bar')
										.css('width', `${percent}%`)
										.attr('aria-valuenow', percent)
										.text(`${percent}%`);
									$('#progress-message').text(message);
								}
							});
						}
					);
				}).addClass('btn-warning');
			}

			// Show Post-Migration buttons if we have any migration history or if status is Completed
			if (has_migrations || frm.doc.migration_status === 'Completed') {
				console.log('Adding Post-Migration buttons');

				// Add Post-Migration section with account type mapping
				frm.add_custom_button(__('Map Account Types'), () => {
					// Ask user which approach to use
					const d = new frappe.ui.Dialog({
						title: 'Choose Mapping Approach',
						fields: [
							{
								fieldtype: 'HTML',
								options: `<p>How would you like to map account types?</p>
									<div class="alert alert-info">
										<strong>Category-based (Recommended):</strong> Uses E-Boekhouden's own categories (DEB, CRED, FIN, etc.)
										and automatically splits mixed categories like Financial accounts into Cash, Bank, and PSPs.
									</div>
									<div class="alert alert-warning">
										<strong>Group-based:</strong> Uses numeric groups (002, 005, etc.) with inferred names.
									</div>`
							}
						],
						primary_action_label: 'Use Category-based (Recommended)',
						primary_action() {
							d.hide();
							// Use fixed category-based mapping
							frappe.call({
								method: 'verenigingen.e_boekhouden.utils_category_mapping_fixed.analyze_accounts_with_proper_categories',
								callback(r) {
									if (r.message && r.message.success) {
										show_account_mapping_dialog(r.message);
									} else {
										frappe.msgprint({
											title: __('Error'),
											message: __('Failed to analyze account categories'),
											indicator: 'red'
										});
									}
								}
							});
						},
						secondary_action_label: 'Use Group-based',
						secondary_action() {
							d.hide();
							// Use original group-based mapping
							frappe.call({
								method: 'verenigingen.e_boekhouden.utils_group_analysis_improved.analyze_account_categories_improved',
								args: {
									use_groups: true
								},
								callback(r) {
									if (r.message && r.message.success) {
										show_account_mapping_dialog(r.message);
									} else {
										frappe.msgprint({
											title: __('Error'),
											message: __('Failed to analyze account categories'),
											indicator: 'red'
										});
									}
								}
							});
						}
					});
					d.show();
				}, __('Post-Migration'));

				// Add other post-migration utilities
				frm.add_custom_button(__('Fix Account Types'), () => {
					console.log('Fix Account Types button clicked');

					// Create a custom dialog instead of msgprint
					const fix_dialog = new frappe.ui.Dialog({
						title: 'Fix Account Types',
						fields: [
							{
								fieldtype: 'HTML',
								options: `<div class="alert alert-info">
									<h5>This tool will:</h5>
									<ul>
										<li>Set "Te ontvangen" accounts as Receivable</li>
										<li>Set "Te betalen" accounts as Payable</li>
										<li>Fix Income/Expense account types</li>
										<li>Correct any other mistyped accounts</li>
									</ul>
								</div>`
							}
						],
						primary_action_label: 'Analyze Accounts',
						primary_action() {
							console.log('Analyze Accounts clicked, calling method...');
							fix_dialog.hide();
							frappe.call({
								method: 'verenigingen.utils.fix_receivable_payable_entries.analyze_and_fix_entries',
								callback(r) {
									console.log('Response received:', r);
									if (r.message && r.message.success) {
										if (r.message.action === 'preview' && r.message.accounts_to_fix) {
											// Show preview dialog
											const preview_dialog = new frappe.ui.Dialog({
												title: 'Confirm Account Type Fixes',
												fields: [{
													fieldtype: 'HTML',
													options: r.message.preview_html
												}],
												size: 'large',
												primary_action_label: 'Apply Fixes',
												primary_action() {
													preview_dialog.hide();
													// Apply the fixes
													frappe.call({
														method: 'verenigingen.utils.fix_receivable_payable_entries.apply_account_type_fixes',
														args: {
															accounts_to_fix: r.message.accounts_to_fix
														},
														callback(fix_result) {
															if (fix_result.message && fix_result.message.success) {
																frappe.msgprint({
																	title: __('Fixes Applied'),
																	message: fix_result.message.summary,
																	indicator: 'green'
																});
															} else {
																frappe.msgprint({
																	title: __('Error'),
																	message: fix_result.message ? fix_result.message.error : 'Unknown error',
																	indicator: 'red'
																});
															}
														}
													});
												},
												secondary_action_label: 'Cancel'
											});
											preview_dialog.show();
										} else {
											// No fixes needed
											frappe.msgprint({
												title: __('Analysis Complete'),
												message: r.message.summary,
												indicator: 'green'
											});
										}
									} else {
										frappe.msgprint({
											title: __('Error'),
											message: r.message ? r.message.error : 'Unknown error',
											indicator: 'red'
										});
									}
								},
								error(err) {
									console.error('Error calling analyze_and_fix_entries:', err);
									frappe.msgprint({
										title: __('Error'),
										message: __('Failed to call the analysis method. Check console for details.'),
										indicator: 'red'
									});
								}
							});
						},
						secondary_action_label: 'Cancel'
					});
					fix_dialog.show();
				}, __('Post-Migration'));

				frm.add_custom_button(__('View Migration History'), () => {
					let history_html = '<h5>Migration History</h5><hr>';

					if (frm.doc.migration_summary) {
						history_html += '<h6>Last Migration Summary:</h6>';
						history_html += `<pre style="max-height: 400px; overflow-y: auto; background: #f8f9fa; padding: 10px; border-radius: 3px;">${frm.doc.migration_summary}</pre>`;
					}

					history_html += '<hr><h6>Statistics:</h6>';
					history_html += '<table class="table table-sm">';
					history_html += `<tr><td>Total Records Processed</td><td>${frm.doc.total_records || 0}</td></tr>`;
					history_html += `<tr><td>Successfully Imported</td><td class="text-success">${frm.doc.imported_records || 0}</td></tr>`;
					history_html += `<tr><td>Failed Records</td><td class="text-danger">${frm.doc.failed_records || 0}</td></tr>`;
					history_html += '</table>';

					const dialog = new frappe.ui.Dialog({
						title: 'Migration History',
						fields: [{
							fieldtype: 'HTML',
							options: history_html
						}],
						primary_action_label: 'Close',
						primary_action() { dialog.hide(); }
					});
					dialog.show();
				}, __('Post-Migration'));
			}
		} else if (frm.doc.migration_status === 'Failed') {
			console.log('Adding reset button for Failed status');
			frm.add_custom_button(__('Reset to Draft'), () => {
				frappe.confirm(
					__('This will reset the migration status to Draft so you can try again. Continue?'),
					() => {
						frappe.call({
							method: 'frappe.client.set_value',
							args: {
								doctype: 'E-Boekhouden Migration',
								name: frm.doc.name,
								fieldname: {
									migration_status: 'Draft',
									error_log: '',
									current_operation: '',
									progress_percentage: 0
								}
							},
							callback(r) {
								if (r.message) {
									frappe.show_alert({
										message: __('Migration reset to Draft status'),
										indicator: 'green'
									});
									frm.reload_doc();
								}
							}
						});
					}
				);
			}).addClass('btn-secondary');
		} else {
			console.log('Not adding buttons - docstatus:', frm.doc.docstatus, 'status:', frm.doc.migration_status);
		}

		// Add progress refresh button if in progress
		if (frm.doc.migration_status === 'In Progress') {
			frm.add_custom_button(__('Refresh Progress'), () => {
				frm.reload_doc();
			});

			// Auto-refresh every 5 seconds
			if (!frm.auto_refresh_interval) {
				frm.auto_refresh_interval = setInterval(() => {
					frm.reload_doc();
				}, 5000);
			}
		} else if (frm.auto_refresh_interval) {
			clearInterval(frm.auto_refresh_interval);
			frm.auto_refresh_interval = null;
		}

		// Add view results button if completed
		if (frm.doc.migration_status === 'Completed') {
			frm.add_custom_button(__('View Migration Summary'), () => {
				const dialog = new frappe.ui.Dialog({
					title: 'Migration Summary',
					fields: [{
						fieldtype: 'HTML',
						options: `<div class="migration-summary">
							<h5>Migration Results:</h5>
							<div class="row">
								<div class="col-md-4">
									<div class="card text-center">
										<div class="card-body">
											<h3 class="text-success">${frm.doc.imported_records || 0}</h3>
											<p>Imported Records</p>
										</div>
									</div>
								</div>
								<div class="col-md-4">
									<div class="card text-center">
										<div class="card-body">
											<h3 class="text-danger">${frm.doc.failed_records || 0}</h3>
											<p>Failed Records</p>
										</div>
									</div>
								</div>
								<div class="col-md-4">
									<div class="card text-center">
										<div class="card-body">
											<h3 class="text-info">${frm.doc.total_records || 0}</h3>
											<p>Total Records</p>
										</div>
									</div>
								</div>
							</div>
							<hr>
							<h6>Detailed Summary:</h6>
							<pre style="max-height: 300px; overflow-y: auto; background: #f8f9fa; padding: 10px; border-radius: 3px;">${frm.doc.migration_summary || 'No summary available'}</pre>
						</div>`
					}],
					primary_action_label: 'Close',
					primary_action() { dialog.hide(); }
				});
				dialog.show();
			});
		}

		// Show progress bar if migration is running
		if (frm.doc.migration_status === 'In Progress') {
			frm.dashboard.add_progress('Migration Progress',
				frm.doc.progress_percentage || 0,
				frm.doc.current_operation || 'Processing...'
			);
		}

		// Set help text based on status
		if (frm.doc.migration_status === 'Draft' && !has_migrations) {
			frm.set_intro(__('<strong>How to use:</strong><br>1. First click "Test Connection" to verify API settings<br>2. Click "Preview Migration" to see what would be imported (recommended)<br>3. Click "Start Migration" to perform the actual import with specified date range<br>4. Or click "Full Migration" to automatically migrate ALL data from E-Boekhouden'), 'blue');
		} else if (frm.doc.migration_status === 'In Progress') {
			frm.set_intro(__('Migration is currently running. Progress will be updated automatically.'));
		} else if (frm.doc.migration_status === 'Completed' || has_migrations) {
			frm.set_intro(__('Migration completed successfully. You can now use the Post-Migration tools to:<br>• Map account types for proper ERPNext functionality<br>• Fix any Receivable/Payable entries missing party information<br>• View detailed migration history<br><br>You can also run additional migrations if needed.'), 'green');
		} else if (frm.doc.migration_status === 'Failed') {
			frm.set_intro(__('Migration failed. Check the error log for details. You can reset to Draft to try again.'), 'red');
		}
	},

	onload(frm) {
		// Set default company from E-Boekhouden settings
		if (!frm.doc.company) {
			frappe.db.get_single_value('E-Boekhouden Settings', 'default_company')
				.then(company => {
					if (company) {
						frm.set_value('company', company);
					}
				});
		}

		// Set default date range (last month)
		if (!frm.doc.date_from && !frm.doc.date_to) {
			const today = new Date();
			const lastMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1);
			const lastMonthEnd = new Date(today.getFullYear(), today.getMonth(), 0);

			frm.set_value('date_from', frappe.datetime.obj_to_str(lastMonth));
			frm.set_value('date_to', frappe.datetime.obj_to_str(lastMonthEnd));
		}
	},

	migrate_transactions(frm) {
		// Show/hide date fields based on transaction migration
		frm.toggle_reqd(['date_from', 'date_to'], frm.doc.migrate_transactions);
	}
});

// Clean up intervals when form is destroyed
frappe.ui.form.on('E-Boekhouden Migration', 'before_unload', (frm) => {
	if (frm.auto_refresh_interval) {
		clearInterval(frm.auto_refresh_interval);
	}
});

// Function to show account mapping dialog
function show_account_mapping_dialog(analysis_data) {
	const mapping_fields = [];

	// Add intro with any explanatory notes
	let intro_html = `<div class="alert alert-info">
		<h5>Account Type Mapping</h5>
		<p>Map E-Boekhouden categories to ERPNext account types. This is a two-step process:</p>
		<ol>
			<li>Review and adjust the mappings below</li>
			<li>Preview changes before applying</li>
		</ol>
		<p><strong>Note:</strong> Receivable/Payable accounts require party information in journal entries.</p>
	</div>`;

	// Add explanatory notes if provided
	if (analysis_data.explanatory_notes) {
		analysis_data.explanatory_notes.forEach((note) => {
			intro_html += `<div class="alert alert-warning mt-2">
				<strong>${note.title}:</strong>
				<ul class="mb-0">`;
			note.items.forEach((item) => {
				intro_html += `<li>${item}</li>`;
			});
			intro_html += '</ul></div>';
		});
	}

	mapping_fields.push({
		fieldtype: 'HTML',
		options: intro_html
	});

	// Add section break after intro
	mapping_fields.push({
		fieldtype: 'Section Break',
		label: 'Account Mappings'
	});

	// Add action buttons
	mapping_fields.push({
		fieldtype: 'HTML',
		options: `
			<div class="mb-3">
				<button type="button" class="btn btn-xs btn-default" onclick="
					$('.mapping-select').each(function() {
						let suggested = $(this).find('option[selected]').val();
						if (suggested) $(this).val(suggested);
					});
				">Apply All Suggestions</button>
				<button type="button" class="btn btn-xs btn-default ml-2" onclick="
					$('.mapping-select').val(&quot;Skip&quot;);
				">Skip All</button>
				<span class="text-muted ml-3">${analysis_data.mapping_proposals.length} mappings to configure</span>
			</div>
		`
	});

	// Create a container for better layout with proper spacing and scrolling
	mapping_fields.push({
		fieldtype: 'HTML',
		options: '<div class="mapping-container" style="height: 350px; overflow-y: auto; padding: 10px; margin-bottom: 20px; border: 1px solid #d1d8dd; border-radius: 4px; background-color: #fafbfc;">'
	});

	// Add mapping fields for each proposal (group or category) as rows
	analysis_data.mapping_proposals.forEach((proposal) => {
		const suggested = proposal.suggested_mapping || {};
		const proposal_type = proposal.type || 'category';
		const display_name = proposal.name || proposal.identifier || proposal.category;
		const identifier = proposal.identifier || proposal.category;

		// Create a simpler row layout
		let row_html = `
			<div class="mapping-row" style="margin-bottom: 8px; padding: 10px; background-color: white; border: 1px solid #e3e3e3; border-radius: 3px;">
				<div class="row align-items-center">
					<div class="col-md-7">
						<div style="margin-bottom: 5px;">
							<strong>${display_name}</strong>
							<span class="text-muted ml-2">(${proposal.account_count} accounts)</span>`;

		// Show type badge inline
		if (proposal_type === 'category') {
			row_html += ` <span class="badge badge-primary badge-sm ml-2">${identifier}</span>`;
		} else if (proposal_type === 'subcategory') {
			row_html += ` <span class="badge badge-info badge-sm ml-2">${proposal.parent_category}</span>`;
		}

		row_html += '</div>';

		// Show sample accounts more compactly
		if (proposal.sample_accounts && proposal.sample_accounts.length > 0) {
			row_html += '<div class="text-muted small" style="line-height: 1.4;">';
			const examples = proposal.sample_accounts.slice(0, 2).map(acc =>
				`${acc.code} - ${acc.description || acc.name || ''}`
			).join(', ');
			row_html += examples;
			if (proposal.account_count > 2) {
				row_html += ` <em>(+${proposal.account_count - 2} more)</em>`;
			}
			row_html += '</div>';
		}

		row_html += `</div>
					<div class="col-md-3">`;

		// Show suggestion compactly
		if (suggested.reason) {
			const confidence_color = suggested.confidence === 'high' ? 'text-success'
				: suggested.confidence === 'medium' ? 'text-warning' : 'text-muted';
			row_html += `<div class="small ${confidence_color}" style="margin-bottom: 5px;">
				<i class="fa fa-lightbulb-o"></i> ${suggested.reason}
			</div>`;
		}

		row_html += `</div>
					<div class="col-md-2">
						<select class="form-control form-control-sm mapping-select" id="mapping_${identifier}" data-identifier="${identifier}">`;

		// Simplified options without optgroups for cleaner look
		const option_list = [
			{ value: '', label: '-- Select --' },
			{ value: 'Skip', label: 'Skip' },
			{ value: '---', label: '─────────', disabled: true },
			{ value: 'Cash', label: 'Cash' },
			{ value: 'Bank', label: 'Bank' },
			{ value: 'Receivable', label: 'Receivable' },
			{ value: 'Payable', label: 'Payable' },
			{ value: 'Stock', label: 'Stock' },
			{ value: 'Current Asset', label: 'Current Asset' },
			{ value: 'Fixed Asset', label: 'Fixed Asset' },
			{ value: 'Current Liability', label: 'Current Liability' },
			{ value: 'Equity', label: 'Equity' },
			{ value: '---2', label: '─────────', disabled: true },
			{ value: 'Income Account', label: 'Income Account' },
			{ value: 'Expense Account', label: 'Expense Account' },
			{ value: 'Tax', label: 'Tax' },
			{ value: 'Depreciation', label: 'Depreciation' },
			{ value: 'Temporary', label: 'Temporary' }
		];

		option_list.forEach((opt) => {
			const selected = (suggested.type === opt.value) ? 'selected' : '';
			const disabled = opt.disabled ? 'disabled' : '';
			row_html += `<option value="${opt.value}" ${selected} ${disabled}>${opt.label}</option>`;
		});

		row_html += `
						</select>
					</div>
				</div>
			</div>`;

		mapping_fields.push({
			fieldtype: 'HTML',
			fieldname: `mapping_row_${identifier}`,
			options: row_html
		});

		// No section breaks needed with the cleaner layout
	});

	// Close the container
	mapping_fields.push({
		fieldtype: 'HTML',
		options: '</div>'
	});

	// Create dialog
	const mapping_dialog = new frappe.ui.Dialog({
		title: 'Map E-Boekhouden Account Types',
		fields: mapping_fields,
		size: 'extra-large',
		primary_action_label: 'Preview Changes',
		primary_action(_values) {
			// Extract mappings from custom select elements
			const mappings = {};

			// Get values from our custom select elements
			mapping_dialog.$wrapper.find('.mapping-select').each(function () {
				const identifier = $(this).data('identifier');
				const value = $(this).val();
				if (value && value !== 'Skip') {
					mappings[identifier] = value;
				}
			});

			if (Object.keys(mappings).length === 0) {
				frappe.msgprint({
					title: __('No Mappings Selected'),
					message: __('Please select at least one account type mapping before previewing.'),
					indicator: 'orange'
				});
				return;
			}

			// Preview changes - detect which type of mapping we're using
			let preview_method = 'verenigingen.e_boekhouden.utils_account_type_mapping.get_mapping_preview';

			// Check if this is category-based mapping
			const mapping_keys = Object.keys(mappings);
			if (mapping_keys.some(k => k.includes('_') || ['DEB', 'CRED', 'FIN', 'KAS', 'VW', 'BTW', 'EIG', 'BAL'].includes(k))) {
				preview_method = 'verenigingen.e_boekhouden.utils_category_preview.get_category_mapping_preview';
			}

			frappe.call({
				method: preview_method,
				args: { mappings },
				callback(r) {
					if (r.message && r.message.success) {
						show_mapping_preview(mappings, r.message.preview);
						mapping_dialog.hide();
					} else {
						frappe.msgprint({
							title: __('Preview Failed'),
							message: r.message ? r.message.error : 'Unknown error',
							indicator: 'red'
						});
					}
				}
			});
		},
		secondary_action_label: 'Cancel'
	});

	// Add some custom CSS for better appearance
	mapping_dialog.$wrapper.find('.modal-dialog').css('max-width', '1000px');
	// Remove max-height restriction on modal-body to prevent conflicts
	mapping_dialog.$wrapper.find('.modal-body').css('overflow', 'visible');

	// Add CSS to fix any potential overlap issues
	mapping_dialog.$wrapper.find('head').append(`
		<style>
			.mapping-row:hover {
				background-color: #f5f7fa !important;
				border-color: #d1d8dd !important;
			}
			.mapping-container {
				margin-top: 10px;
			}
			.form-section {
				margin-bottom: 15px;
			}
		</style>
	`);

	mapping_dialog.show();
}

// Function to show mapping preview
function show_mapping_preview(mappings, preview) {
	let preview_html = '<h5>Preview of Changes</h5><hr>';
	let total_updates = 0;

	for (const category in preview) {
		const cat_data = preview[category];
		const update_count = cat_data.accounts_to_update.length;
		total_updates += update_count;

		preview_html += `<h6>${category} → ${cat_data.target_type}</h6>`;

		if (update_count > 0) {
			preview_html += `<p class="text-success">${update_count} accounts will be updated:</p>`;
			preview_html += '<ul class="small">';
			cat_data.accounts_to_update.slice(0, 5).forEach(acc => {
				preview_html += `<li>${acc.code} - ${acc.description} (${acc.current_type} → ${acc.new_type})</li>`;
			});
			if (update_count > 5) {
				preview_html += `<li>... and ${update_count - 5} more</li>`;
			}
			preview_html += '</ul>';
		}

		if (cat_data.accounts_already_correct.length > 0) {
			preview_html += `<p class="text-muted small">${cat_data.accounts_already_correct.length} accounts already correct</p>`;
		}

		if (cat_data.accounts_not_found.length > 0) {
			preview_html += `<p class="text-warning small">${cat_data.accounts_not_found.length} accounts not found in ERPNext</p>`;
		}
	}

	preview_html += `<hr><p><strong>Total accounts to update: ${total_updates}</strong></p>`;

	const preview_dialog = new frappe.ui.Dialog({
		title: 'Confirm Account Type Updates',
		fields: [{
			fieldtype: 'HTML',
			options: preview_html
		}],
		size: 'large',
		primary_action_label: 'Apply Changes',
		primary_action() {
			preview_dialog.hide();

			// Determine which apply method to use based on mapping keys
			let apply_method = 'verenigingen.e_boekhouden.utils_account_type_mapping.apply_account_type_mappings';

			// Check if this is category-based mapping
			const mapping_keys = Object.keys(mappings);
			if (mapping_keys.some(k => k.includes('_') || ['DEB', 'CRED', 'FIN', 'KAS', 'VW', 'BTW', 'EIG', 'BAL', 'AF19', 'AF6', 'AFOVERIG', 'BTWRC', 'VOOR'].includes(k))) {
				apply_method = 'verenigingen.utils.apply_category_mapping_fixed.apply_fixed_category_mappings';
			}

			// Apply mappings
			frappe.call({
				method: apply_method,
				args: { mappings },
				callback(r) {
					if (r.message && r.message.success) {
						const summary = r.message.summary;
						frappe.msgprint({
							title: __('Account Types Updated'),
							message: __(`Successfully updated ${summary.total_updated} accounts.
								${summary.total_skipped} skipped, ${summary.total_errors} errors.`),
							indicator: 'green'
						});
					} else {
						frappe.msgprint({
							title: __('Error'),
							message: __('Failed to update account types'),
							indicator: 'red'
						});
					}
				}
			});
		},
		secondary_action_label: 'Back',
		secondary_action() {
			preview_dialog.hide();
		}
	});

	preview_dialog.show();
}
