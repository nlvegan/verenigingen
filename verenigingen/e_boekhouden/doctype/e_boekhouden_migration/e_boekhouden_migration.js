/**
 * @fileoverview E-Boekhouden Migration Interface - Enterprise Financial Data Integration
 *
 * This module provides a comprehensive financial data migration interface for importing
 * Chart of Accounts, transactions, and financial data from E-Boekhouden (Dutch accounting
 * software) into ERPNext. The system supports both SOAP and REST API endpoints with
 * intelligent fallback mechanisms and robust data validation.
 *
 * ## Core Business Functions
 * - **Two-Phase Migration Process**: Streamlined CoA setup followed by transaction import
 * - **Multi-API Support**: SOAP API for basic operations, REST API for complete historical data
 * - **Automatic Account Mapping**: Intelligent account type detection based on usage patterns
 * - **Duplicate Prevention**: Advanced mutation ID tracking prevents duplicate transactions
 * - **Opening Balance Integration**: Proper ERPNext Opening Invoice creation for receivables/payables
 * - **Real-time Progress Monitoring**: Live migration status with detailed progress reporting
 *
 * ## Technical Architecture
 * - **Progressive Enhancement**: Falls back from REST to SOAP when API credentials unavailable
 * - **Transaction Batching**: Processes large datasets efficiently with memory management
 * - **Error Recovery**: Comprehensive error handling with detailed logging and retry mechanisms
 * - **Data Validation**: Pre-import analysis with data quality reporting
 * - **Account Type Intelligence**: Uses transaction patterns to auto-classify account types
 *
 * ## Security & Compliance
 * - **API Key Management**: Secure handling of E-Boekhouden API credentials
 * - **Data Integrity**: Transaction checksums and validation before import
 * - **Audit Trail**: Complete migration logging for compliance and debugging
 * - **Permission Validation**: Ensures proper ERPNext permissions before data creation
 *
 * ## Performance Optimization
 * - **Chunked Processing**: Handles large datasets without memory exhaustion
 * - **Smart Caching**: Reduces API calls through intelligent data caching
 * - **Background Processing**: Long-running imports use background jobs
 * - **Progress Tracking**: Real-time status updates without blocking UI
 *
 * ## Integration Points
 * - ERPNext Chart of Accounts management
 * - Customer/Supplier master data synchronization
 * - Journal Entry creation with proper ERPNext workflow
 * - Opening Invoice generation for proper balance sheet reconciliation
 * - Cost Center mapping for departmental accounting
 *
 * @company R.S.P. (Verenigingen Association Management)
 * @version 2025.1.0
 * @since 2024.3.0
 * @license Proprietary
 *
 * @requires frappe>=15.0.0
 * @requires erpnext>=15.0.0
 * @requires verenigingen.e_boekhouden
 *
 * @see {@link https://api.e-boekhouden.nl/swagger/v1/swagger.json} E-Boekhouden REST API
 * @see {@link https://cdn.e-boekhouden.nl/handleiding/Documentatie_soap.pdf} E-Boekhouden SOAP API
 */

// Copyright (c) 2025, R.S.P. and contributors
// E-Boekhouden Migration Interface - Streamlined with SOAP API

frappe.ui.form.on('E-Boekhouden Migration', {
	refresh(frm) {
		// Hide legacy checkbox fields
		hide_legacy_fields(frm);

		// Add migration guide at the top
		add_migration_guide(frm);

		// Remove old migration type selector - we use buttons now
		if (frm.migration_type_wrapper) {
			frm.migration_type_wrapper.remove();
		}

		// Show appropriate buttons based on status
		setup_action_buttons(frm);

		// Show progress if running
		if (frm.doc.migration_status === 'In Progress') {
			show_migration_progress(frm);
		}

		// Set helpful status message
		set_status_message(frm);
	},

	onload(frm) {
		// Set defaults for new migration
		if (frm.is_new()) {
			set_migration_defaults(frm);
		}

		// Add Tools dropdown buttons
		if (!frm.is_new() && frm.doc.docstatus === 0) {
			add_tools_dropdown(frm);
		}
	}
});

function add_migration_guide(frm) {
	// Add simplified guide at the top of the form
	const guide_html = `
		<div class="migration-guide" style="margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px; border-left: 4px solid #5e64ff;">
			<h5 style="margin-top: 0; color: #333;">📋 E-Boekhouden Migration - Two Step Process</h5>

			<div style="margin-bottom: 15px;">
				<strong>Step 1: Setup Chart of Accounts</strong>
				<ul style="margin: 5px 0;">
					<li>Import your complete Chart of Accounts from E-Boekhouden</li>
					<li>Import Cost Centers if configured</li>
					<li>Review and adjust account mappings before finalizing</li>
				</ul>
			</div>

			<div style="margin-bottom: 15px;">
				<strong>Step 2: Import Transactions</strong>
				<ul style="margin: 5px 0;">
					<li><strong>All Transactions:</strong> Import complete history via REST API</li>
					<li><strong>Recent Transactions:</strong> Import last 90 days via REST API</li>
					<li>Any new customers/suppliers found will be imported automatically</li>
					<li>Duplicate transactions are automatically skipped</li>
					<li>REST API token required for both options</li>
				</ul>
			</div>

			<div style="margin-top: 15px; padding: 10px; background: #e3f2fd; border-radius: 3px;">
				<strong>💡 Tips:</strong>
				<ul style="margin: 5px 0; padding-left: 20px;">
					<li>Complete Step 1 first - you need accounts before importing transactions</li>
					<li>You can run transaction imports multiple times - duplicates are prevented</li>
				</ul>
			</div>

		</div>
	`;

	// Remove any existing guide
	if (frm.guide_wrapper) {
		frm.guide_wrapper.remove();
	}

	// Add guide after the title
	frm.guide_wrapper = $('<div></div>').insertAfter(frm.$wrapper.find('.page-head'));
	frm.guide_wrapper.html(guide_html);
}

function hide_legacy_fields(frm) {
	// Hide the old checkbox fields - we use radio buttons now
	const fields_to_hide = [
		'migrate_accounts', 'migrate_cost_centers', 'migrate_customers',
		'migrate_suppliers', 'migrate_transactions', 'migrate_stock_transactions',
		'dry_run'
	];

	fields_to_hide.forEach(field => {
		frm.set_df_property(field, 'hidden', 1);
	});

	// Also hide the migration scope section
	frm.set_df_property('migration_scope_section', 'hidden', 1);
}

function add_migration_type_selector(frm) {
	// Remove any existing selector first
	if (frm.migration_type_wrapper) {
		frm.migration_type_wrapper.remove();
	}

	// Create wrapper div after the company field
	const company_field = frm.fields_dict.company.$wrapper;
	frm.migration_type_wrapper = $('<div class="form-section"></div>').insertAfter(company_field);

	// Add custom HTML
	const html = `
		<div class="migration-type-selector" style="margin: 20px 0;">
			<style>
				.migration-option {
					display: block;
					margin: 10px 0;
					padding: 15px;
					background: white;
					border: 2px solid #d1d8dd;
					border-radius: 5px;
					cursor: pointer;
					transition: all 0.2s;
				}
				.migration-option:hover {
					border-color: #5e64ff;
					background: #f8f9ff;
				}
				.migration-option.selected {
					border-color: #5e64ff;
					background: #f0f3ff;
				}
				.migration-option input[type="radio"] {
					margin-right: 10px;
				}
				.migration-badge {
					font-size: 11px;
					padding: 2px 8px;
					border-radius: 3px;
					margin-left: 10px;
				}
			</style>

			<h5 style="margin-bottom: 15px; color: #4c5053;">Select Migration Type</h5>

			<div class="migration-options">
				<label class="migration-option" data-type="full_initial">
					<input type="radio" name="eb_migration_type" value="full_initial">
					<strong>Full Initial Migration</strong>
					<span class="migration-badge badge badge-primary">Recommended for first time</span>
					<div style="margin-top: 5px; color: #6c757d; font-size: 13px;">
						Complete import of all data: chart of accounts, customers, suppliers, and all transactions.
						The system will automatically determine the date range from your E-Boekhouden data.
					</div>
				</label>

				<label class="migration-option" data-type="transactions_update">
					<input type="radio" name="eb_migration_type" value="transactions_update">
					<strong>Transaction Update</strong>
					<span class="migration-badge badge badge-info">For regular updates</span>
					<div style="margin-top: 5px; color: #6c757d; font-size: 13px;">
						Import only new transactions for a specific date range.
						Duplicate transactions are automatically skipped based on mutation ID.
					</div>
				</label>

				<label class="migration-option" data-type="preview">
					<input type="radio" name="eb_migration_type" value="preview">
					<strong>Preview Mode</strong>
					<span class="migration-badge badge badge-secondary">Test run</span>
					<div style="margin-top: 5px; color: #6c757d; font-size: 13px;">
						See what would be imported without making any changes.
						Perfect for testing your settings and understanding the data.
					</div>
				</label>
			</div>

			<div class="date-range-section" style="display: none; margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px;">
				<h6 style="margin-bottom: 10px;">Date Range Required</h6>
				<div class="row">
					<div class="col-md-6">
						<div class="form-group">
							<label>From Date</label>
							<input type="date" class="form-control" id="eb_date_from">
						</div>
					</div>
					<div class="col-md-6">
						<div class="form-group">
							<label>To Date</label>
							<input type="date" class="form-control" id="eb_date_to">
						</div>
					</div>
				</div>
			</div>
		</div>
	`;

	// Insert the HTML into our wrapper
	frm.migration_type_wrapper.html(html);

	// Add event handlers
	setup_migration_type_handlers(frm);
}

function setup_migration_type_handlers(frm) {
	const wrapper = frm.migration_type_wrapper;

	// Radio button change handler
	wrapper.find('input[name="eb_migration_type"]').on('change', function () {
		const selected = $(this).val();
		frm.selected_migration_type = selected;

		// Update UI
		wrapper.find('.migration-option').removeClass('selected');
		$(this).closest('.migration-option').addClass('selected');

		// Show/hide date range
		if (selected === 'transactions_update' || selected === 'preview') {
			wrapper.find('.date-range-section').slideDown();

			// Set default dates if empty
			const dateFrom = wrapper.find('#eb_date_from');
			const dateTo = wrapper.find('#eb_date_to');

			if (!dateFrom.val()) {
				// Default to last month
				const today = new Date();
				const firstDay = new Date(today.getFullYear(), today.getMonth() - 1, 1);
				const lastDay = new Date(today.getFullYear(), today.getMonth(), 0);

				dateFrom.val(frappe.datetime.obj_to_str(firstDay));
				dateTo.val(frappe.datetime.obj_to_str(lastDay));
			}
		} else {
			wrapper.find('.date-range-section').slideUp();
		}
	});

	// Date change handlers
	wrapper.find('#eb_date_from, #eb_date_to').on('change', () => {
		frm.set_value('date_from', wrapper.find('#eb_date_from').val());
		frm.set_value('date_to', wrapper.find('#eb_date_to').val());
	});
}

function setup_action_buttons(frm) {
	// Clear existing buttons
	frm.clear_custom_buttons();

	if (frm.doc.docstatus === 0) {
		if (frm.doc.migration_status !== 'In Progress') {
			// Two main action buttons

			// Step 1: Setup Chart of Accounts
			frm.add_custom_button(__('1. Setup Chart of Accounts'), () => {
				handle_setup_coa(frm);
			}).addClass('btn-primary');

			// Step 2: Import Transactions
			frm.add_custom_button(__('2. Import Transactions'), () => {
				handle_import_transactions(frm);
			}).addClass('btn-primary');

			// Opening Balance Import
			frm.add_custom_button(__('Import Opening Balances'), () => {
				handle_import_opening_balances(frm);
			}).addClass('btn-secondary');

			// Helper buttons in dropdown
			frm.add_custom_button(__('Test Connection'), () => {
				test_api_connection();
			}, __('Tools'));

			// Single mutation import for debugging
			frm.add_custom_button(__('Import Single Mutation'), () => {
				handle_import_single_mutation(frm);
			}, __('Tools'));
		} else {
			// Refresh button for in-progress
			frm.add_custom_button(__('Refresh'), () => {
				frm.reload_doc();
			});
		}
	}

	// Post-migration tools
	if (frm.doc.migration_status === 'Completed' || frm.doc.imported_records > 0) {
		add_post_migration_tools(frm);
	}
}

function analyze_eboekhouden_data(frm) {
	// Show loading
	frappe.show_alert({
		message: __('Analyzing E-Boekhouden data...'),
		indicator: 'blue'
	});

	frappe.call({
		method: 'verenigingen.api.update_prepare_system_button.analyze_eboekhouden_data',
		callback(r) {
			if (r.message && r.message.success) {
				const data = r.message;
				let html = '<div style="max-height: 500px; overflow-y: auto;">';

				// Date range
				if (data.date_range && data.date_range.earliest_date) {
					html += '<div class="alert alert-info">';
					html += '<h5>📅 Date Range</h5>';
					html += `<strong>Earliest transaction:</strong> ${data.date_range.earliest_date}<br>`;
					html += `<strong>Latest transaction:</strong> ${data.date_range.latest_date}<br>`;

					// Store for later use
					window.eboekhouden_date_range = data.date_range;

					html += '<em>These dates will be used automatically for full migration.</em>';
					html += '</div>';
				}

				// SOAP API Limitation Warning
				if (data.total_mutations === 500) {
					html += '<div class="alert alert-warning">';
					html += '<h5>⚠️ SOAP API Limitation</h5>';
					html += '<p>The SOAP API only returns the <strong>most recent 500 mutations</strong>, regardless of date range.</p>';
					if (data.total_estimate) {
						html += `<p>Your E-Boekhouden account has <strong>${data.total_estimate}</strong> total mutations.</p>`;
					}
					html += '<p><strong>Important:</strong> The migration will also be limited to these 500 most recent transactions.</p>';
					html += '<p>To import all historical data, REST API credentials are required.</p>';
					html += '</div>';
				}

				// Transaction summary
				html += '<h5>📊 Transaction Summary</h5>';
				html += `<p>Mutations available for import: <strong>${data.total_mutations}</strong>`;
				if (data.total_mutations === 500) {
					html += ' <span class="text-muted">(SOAP API limit)</span>';
				}
				html += '</p>';

				if (Object.keys(data.mutation_types).length > 0) {
					html += '<table class="table table-bordered">';
					html += '<thead><tr><th>Transaction Type</th><th>Count</th></tr></thead>';
					html += '<tbody>';

					// Sort by count
					const sorted_types = Object.entries(data.mutation_types)
						.sort((a, b) => b[1] - a[1]);

					sorted_types.forEach(([type, count]) => {
						// Translate mutation types
						const type_labels = {
							FactuurVerstuurd: 'Sales Invoices',
							FactuurOntvangen: 'Purchase Invoices',
							FactuurbetalingOntvangen: 'Customer Payments',
							FactuurbetalingVerstuurd: 'Supplier Payments',
							GeldOntvangen: 'Money Received',
							GeldUitgegeven: 'Money Spent',
							Memoriaal: 'Journal Entries'
						};

						const label = type_labels[type] || type;
						html += `<tr><td>${label}</td><td>${count}</td></tr>`;
					});

					html += '</tbody></table>';
				}

				// Account summary
				if (data.account_summary) {
					html += '<h5>📁 Account Usage</h5>';
					html += '<table class="table table-bordered">';
					html += '<thead><tr><th>Account Type</th><th>Count</th></tr></thead>';
					html += '<tbody>';

					const account_labels = {
						receivable_accounts: 'Receivable Accounts (Used in Mutations)',
						payable_accounts: 'Payable Accounts (Used in Mutations)',
						bank_accounts: 'Bank Accounts',
						income_accounts: 'Income Accounts',
						expense_accounts: 'Expense Accounts'
					};

					Object.entries(data.account_summary).forEach(([type, count]) => {
						if (type !== 'actual_receivable_accounts' && count > 0) {
							html += `<tr><td>${account_labels[type] || type}</td><td>${count}</td></tr>`;
						}
					});

					// Show actual receivable accounts if different
					if (data.account_summary.actual_receivable_accounts
						&& data.account_summary.actual_receivable_accounts !== data.account_summary.receivable_accounts) {
						html += `<tr><td><strong>Receivable Accounts (System Total)</strong></td><td><strong>${data.account_summary.actual_receivable_accounts}</strong></td></tr>`;
					}

					html += '</tbody></table>';

					// Note: Warning about 500 limit is already shown at the top
				}

				// Entity summary
				if (data.entity_summary) {
					html += '<h5>👥 Entities</h5>';
					html += '<ul>';
					if (data.entity_summary.unique_customers > 0) {
						html += `<li><strong>${data.entity_summary.unique_customers}</strong> unique customers</li>`;
					}
					if (data.entity_summary.unique_suppliers > 0) {
						html += `<li><strong>${data.entity_summary.unique_suppliers}</strong> unique suppliers</li>`;
					}
					html += '</ul>';
				}

				// Insights
				if (data.insights && data.insights.length > 0) {
					html += '<h5>💡 Insights</h5>';
					html += '<ul>';
					data.insights.forEach(insight => {
						html += `<li>${insight}</li>`;
					});
					html += '</ul>';
				}

				// Next steps
				if (data.total_mutations === 500) {
					html += '<div class="alert alert-info" style="margin-top: 20px;">';
					html += '<strong>Ready to Import (Limited Data)</strong><br>';
					html += 'You can proceed with importing the 500 most recent transactions.<br>';
					html += 'For complete historical data import, please configure REST API credentials.';
					html += '</div>';
				} else {
					html += '<div class="alert alert-success" style="margin-top: 20px;">';
					html += '<strong>✅ Ready to Import!</strong><br>';
					html += 'Your E-Boekhouden data has been analyzed. You can now proceed with the migration.';
					html += '</div>';
				}

				html += '</div>';

				// Show dialog
				const dialog = new frappe.ui.Dialog({
					title: 'E-Boekhouden Data Analysis',
					fields: [{
						fieldtype: 'HTML',
						options: html
					}],
					size: 'large',
					primary_action_label: 'Close',
					primary_action() {
						dialog.hide();
					}
				});

				dialog.show();
			} else {
				frappe.msgprint({
					title: __('Analysis Failed'),
					message: r.message ? r.message.error : 'Unknown error',
					indicator: 'red'
				});
			}
		}
	});
}

function handle_start_migration(frm) {
	// Validate selection
	if (!frm.selected_migration_type) {
		frappe.msgprint({
			title: __('Selection Required'),
			message: __('Please select a migration type before starting.'),
			indicator: 'orange'
		});
		return;
	}

	// Validate company
	if (!frm.doc.company) {
		frappe.msgprint({
			title: __('Company Required'),
			message: __('Please select a company for the migration.'),
			indicator: 'orange'
		});
		return;
	}

	// Validate dates if needed
	if (frm.selected_migration_type === 'transactions_update' || frm.selected_migration_type === 'preview') {
		const dateFrom = $('#eb_date_from').val();
		const dateTo = $('#eb_date_to').val();

		if (!dateFrom || !dateTo) {
			frappe.msgprint({
				title: __('Date Range Required'),
				message: __('Please select both from and to dates.'),
				indicator: 'orange'
			});
			return;
		}

		frm.set_value('date_from', dateFrom);
		frm.set_value('date_to', dateTo);
	}

	// Set appropriate flags based on migration type
	const type_settings = {
		full_initial: {
			migrate_accounts: 1,
			migrate_cost_centers: 1,
			migrate_customers: 1,
			migrate_suppliers: 1,
			migrate_transactions: 1,
			dry_run: 0,
			message: 'This will import all available data from E-Boekhouden (up to 500 most recent transactions due to SOAP API limit).',
			auto_dates: true
		},
		transactions_update: {
			migrate_accounts: 0,
			migrate_cost_centers: 0,
			migrate_customers: 1, // May need to import new customers
			migrate_suppliers: 1, // May need to import new suppliers
			migrate_transactions: 1,
			dry_run: 0,
			message: 'This will import transactions for the selected date range.'
		},
		preview: {
			migrate_accounts: 1,
			migrate_cost_centers: 1,
			migrate_customers: 1,
			migrate_suppliers: 1,
			migrate_transactions: 1,
			dry_run: 1,
			message: 'This will preview the import without making any changes.',
			auto_dates: true
		}
	};

	const settings = type_settings[frm.selected_migration_type];

	// Confirm action with enhanced message
	frappe.confirm(
		__(`${settings.message}<br><br>The system will:<br>`
		+ `• Automatically detect and set correct account types<br>`
		+ `• Create accounts, customers, and suppliers as needed<br>`
		+ `• Import data in the correct sequence<br>`
		+ `• Skip any duplicate transactions<br><br>`
		+ `Continue?`),
		() => {
			// Apply settings
			Object.keys(settings).forEach(key => {
				if (key !== 'message' && key !== 'auto_dates') {
					frm.set_value(key, settings[key]);
				}
			});

			// Set default dates for full migration if needed
			if (settings.auto_dates && (!frm.doc.date_from || !frm.doc.date_to)) {
				// Use detected date range if available
				if (window.eboekhouden_date_range) {
					frm.set_value('date_from', window.eboekhouden_date_range.earliest_date);
					frm.set_value('date_to', window.eboekhouden_date_range.latest_date);
					frappe.show_alert({
						message: __('Using detected date range from E-Boekhouden'),
						indicator: 'blue'
					});
				} else {
					// Fall back to 10-year range
					const today = frappe.datetime.get_today();
					const tenYearsAgo = frappe.datetime.add_days(today, -3650);

					frm.set_value('date_from', tenYearsAgo);
					frm.set_value('date_to', today);
					frappe.show_alert({
						message: __('Using default 10-year date range. Click "Analyze Data" to detect actual range.'),
						indicator: 'yellow'
					});
				}
			}

			// Save and start
			frm.save().then(() => {
				frappe.call({
					method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.start_migration',
					args: {
						migration_name: frm.doc.name
					},
					callback(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __('Migration started successfully!'),
								indicator: 'green'
							});
							// Reload and immediately start progress tracking
							frm.reload_doc().then(() => {
								if (frm.doc.migration_status === 'In Progress') {
									show_migration_progress(frm);
								}
							});
						} else {
							frappe.msgprint({
								title: __('Error'),
								message: r.message ? r.message.error : 'Unknown error',
								indicator: 'red'
							});
						}
					}
				});
			});
		}
	);
}

function test_api_connection() {
	frappe.call({
		method: 'verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection',
		callback(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __('Connection Successful'),
					message: r.message.message,
					indicator: 'green'
				});
			} else {
				frappe.msgprint({
					title: __('Connection Failed'),
					message: r.message ? r.message.error : 'Unknown error',
					indicator: 'red'
				});
			}
		}
	});
}

function show_migration_statistics() {
	frappe.call({
		method: 'verenigingen.api.eboekhouden_migration_redesign.get_migration_statistics',
		callback(r) {
			if (r.message) {
				const stats = r.message;
				let html = '<div style="max-height: 500px; overflow-y: auto;">';

				// Migration history
				if (stats.migrations && stats.migrations.length > 0) {
					html += '<h5>Migration History</h5>';
					html += '<table class="table table-bordered table-sm">';
					html += '<thead><tr><th>Status</th><th>Count</th><th>Records Imported</th><th>Failed</th></tr></thead>';
					html += '<tbody>';

					stats.migrations.forEach(m => {
						const statusClass = m.migration_status === 'Completed' ? 'text-success'
							: m.migration_status === 'Failed' ? 'text-danger' : '';
						html += `<tr>
							<td class="${statusClass}">${m.migration_status}</td>
							<td>${m.count}</td>
							<td>${m.total_records || 0}</td>
							<td>${m.total_failed || 0}</td>
						</tr>`;
					});

					html += '</tbody></table>';
				}

				// Duplicate check
				if (stats.duplicate_mutations && stats.duplicate_mutations.length > 0) {
					html += '<div class="alert alert-warning">';
					html += `<strong>Note:</strong> Found ${stats.duplicate_mutations.length} transactions that have been imported multiple times. `;
					html += 'This is normal if you\'ve run multiple migrations.';
					html += '</div>';
				}

				// Account statistics
				if (stats.accounts) {
					html += '<h5>Imported Accounts</h5>';
					html += `<p>Total accounts with E-Boekhouden numbers: <strong>${stats.accounts.total}</strong></p>`;

					if (stats.accounts.by_type && stats.accounts.by_type.length > 0) {
						html += '<table class="table table-bordered table-sm">';
						html += '<thead><tr><th>Account Type</th><th>Count</th></tr></thead>';
						html += '<tbody>';

						stats.accounts.by_type.forEach(t => {
							html += `<tr>
								<td>${t.account_type || '<em>Not Set</em>'}</td>
								<td>${t.count}</td>
							</tr>`;
						});

						html += '</tbody></table>';
					}
				}

				html += '</div>';

				const dialog = new frappe.ui.Dialog({
					title: 'Migration Statistics',
					fields: [{
						fieldtype: 'HTML',
						options: html
					}],
					size: 'large',
					primary_action_label: 'Close',
					primary_action() {
						dialog.hide();
					}
				});

				dialog.show();
			}
		}
	});
}

function show_migration_progress(frm) {
	// Clean up any existing progress tracking first
	clear_migration_progress(frm);

	// Add progress bar - clear any existing ones first
	frm.dashboard.clear_headline();
	frm.dashboard.add_progress('Migration Progress',
		frm.doc.progress_percentage || 0,
		frm.doc.current_operation || 'Processing...'
	);

	// Auto-refresh only if migration is actually in progress
	if (frm.doc.migration_status === 'In Progress' && !frm.auto_refresh_interval) {
		frm.auto_refresh_interval = setInterval(() => {
			// Only reload if the form is still visible and migration is in progress
			if (frm.doc && frm.doc.migration_status === 'In Progress') {
				frm.reload_doc().catch((error) => {
					console.warn('Failed to reload migration progress:', error);
					// Clear interval on error to prevent endless failed requests
					clear_migration_progress(frm);
				});
			} else {
				// Stop refreshing if migration is no longer in progress
				clear_migration_progress(frm);
			}
		}, 3000); // Reduced to 3 seconds for better responsiveness
	}
}

function clear_migration_progress(frm) {
	// Clear auto-refresh interval
	if (frm.auto_refresh_interval) {
		clearInterval(frm.auto_refresh_interval);
		frm.auto_refresh_interval = null;
	}
}

function set_status_message(frm) {
	if (frm.doc.migration_status === 'Draft' && frm.doc.docstatus === 0) {
		// Don't show intro if guide is already displayed
		if (!frm.guide_wrapper) {
			frm.set_intro(
				'<strong>Welcome to E-Boekhouden Migration!</strong><br>'
				+ 'Follow the guide above to import your data.',
				'blue'
			);
		}
	} else if (frm.doc.migration_status === 'In Progress') {
		frm.set_intro('Migration is running. Progress updates automatically.', 'yellow');
	} else if (frm.doc.migration_status === 'Completed') {
		frm.set_intro(
			'Migration completed successfully! '
			+ 'Account types have been set automatically based on usage. '
			+ 'Use the Review button only if you notice any issues.',
			'green'
		);
	} else if (frm.doc.migration_status === 'Failed') {
		frm.set_intro('Migration failed. Check the error log below for details.', 'red');
	}
}

function set_migration_defaults(frm) {
	// Set meaningful migration name
	const today = frappe.datetime.get_today();
	frm.set_value('migration_name', `E-Boekhouden Import ${today}`);

	// Get default company from settings
	frappe.db.get_single_value('E-Boekhouden Settings', 'default_company')
		.then(company => {
			if (company && !frm.doc.company) {
				frm.set_value('company', company);
			}
		});
}

function add_post_migration_tools(frm) {
	// Simplified post-migration tool
	frm.add_custom_button(__('Review Account Types'), () => {
		// Redirect to the enhanced mapping review page
		window.location.href = '/eboekhouden_mapping_review';
	}, __('Tools'));

	// Add mapping review button if using account mappings
	if (frm.doc.use_account_mappings) {
		frm.add_custom_button(__('Review Mappings'), () => {
			window.location.href = '/eboekhouden_mapping_review';
		}, __('Tools'));
	}

	// Add Data Quality Check button
	frm.add_custom_button(__('Check Data Quality'), () => {
		frappe.show_alert({
			message: __('Analyzing data quality...'),
			indicator: 'blue'
		});

		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.check_migration_data_quality',
			args: {
				migration_name: frm.doc.name
			},
			freeze: true,
			freeze_message: __('Analyzing imported data quality...'),
			callback(r) {
				if (r.message && r.message.success) {
					show_data_quality_report(frm, r.message.report);
				} else {
					frappe.msgprint({
						title: __('Quality Check Failed'),
						message: r.message ? r.message.error : 'Unknown error',
						indicator: 'red'
					});
				}
			}
		});
	}, __('Tools'));
}

function check_account_types(frm) {
	frappe.call({
		method: 'verenigingen.api.check_account_types.review_account_types',
		args: {
			company: frm.doc.company
		},
		callback(r) {
			if (r.message && r.message.success) {
				const data = r.message;
				let html = '<div style="max-height: 500px; overflow-y: auto;">';

				if (data.issues.length === 0) {
					html += '<div class="alert alert-success">';
					html += '<strong>✅ All account types look correct!</strong><br>';
					html += 'No issues found with account categorization.';
					html += '</div>';
				} else {
					html += '<div class="alert alert-warning">';
					html += `<strong>Found ${data.issues.length} potential issues:</strong>`;
					html += '</div>';

					html += '<table class="table table-bordered">';
					html += '<thead><tr><th>Account</th><th>Current Type</th><th>Suggested Type</th><th>Reason</th></tr></thead>';
					html += '<tbody>';

					data.issues.forEach(issue => {
						html += `<tr>
							<td>${issue.account_name}</td>
							<td>${issue.current_type}</td>
							<td><strong>${issue.suggested_type}</strong></td>
							<td>${issue.reason}</td>
						</tr>`;
					});

					html += '</tbody></table>';
				}

				html += '</div>';

				const dialog = new frappe.ui.Dialog({
					title: 'Account Type Review',
					fields: [{
						fieldtype: 'HTML',
						options: html
					}],
					size: 'large',
					primary_action_label: data.issues.length > 0 ? 'Fix Issues' : 'Close',
					primary_action() {
						dialog.hide();
						if (data.issues.length > 0) {
							fix_account_type_issues(data.issues);
						}
					},
					secondary_action_label: data.issues.length > 0 ? 'Cancel' : null
				});

				dialog.show();
			}
		}
	});
}

function fix_account_type_issues(issues) {
	frappe.call({
		method: 'verenigingen.api.check_account_types.fix_account_type_issues',
		args: {
			issues
		},
		callback(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __('Success'),
					message: __(`Fixed ${r.message.fixed_count} account type issues.`),
					indicator: 'green'
				});
			}
		}
	});
}

// Clean up on form unload and status changes
frappe.ui.form.on('E-Boekhouden Migration', 'before_unload', (frm) => {
	clear_migration_progress(frm);
});

frappe.ui.form.on('E-Boekhouden Migration', 'migration_status', (frm) => {
	// Clear progress tracking when status changes from 'In Progress'
	if (frm.doc.migration_status !== 'In Progress') {
		clear_migration_progress(frm);
	}
});

frappe.ui.form.on('E-Boekhouden Migration', 'refresh', (frm) => {
	// Ensure cleanup when form refreshes but migration is not in progress
	if (frm.doc.migration_status !== 'In Progress') {
		clear_migration_progress(frm);
	}
});

function handle_setup_coa(frm) {
	// Validate company
	if (!frm.doc.company) {
		frappe.msgprint({
			title: __('Company Required'),
			message: __('Please select a company before setting up the Chart of Accounts.'),
			indicator: 'orange'
		});
		return;
	}

	// Show setup dialog with cleanup option
	const dialog = new frappe.ui.Dialog({
		title: 'Setup Chart of Accounts',
		fields: [
			{
				fieldname: 'info_section',
				fieldtype: 'HTML',
				options: `<div class="alert alert-info">
					<strong>This will import:</strong>
					<ul>
						<li>Complete Chart of Accounts from E-Boekhouden</li>
						<li>All Customers and Suppliers</li>
						<li>Cost Centers (if configured)</li>
					</ul>
					<p class="mt-2">You will be able to review and adjust account types after import.</p>
				</div>`
			},
			{
				fieldname: 'cleanup_type',
				label: 'Clean up existing accounts first',
				fieldtype: 'Select',
				options: 'No cleanup\nClean up E-Boekhouden accounts only\nClean up ALL accounts',
				default: 'No cleanup',
				description: 'Choose what to clean up before importing',
				onchange() {
					const cleanup_type = dialog.get_value('cleanup_type');
					dialog.set_df_property('cleanup_warning', 'hidden', cleanup_type === 'No cleanup');

					// Update warning message based on selection
					if (cleanup_type === 'Clean up E-Boekhouden accounts only') {
						dialog.set_df_property('cleanup_warning', 'options',
							'<div class="alert alert-warning"><strong>⚠️ Warning:</strong> This will delete all accounts with E-Boekhouden numbers. Make sure you have no transactions linked to these accounts!</div>'
						);
					} else if (cleanup_type === 'Clean up ALL accounts') {
						dialog.set_df_property('cleanup_warning', 'options',
							'<div class="alert alert-danger"><strong>🚨 DANGER:</strong> This will delete ALL accounts in the Chart of Accounts for this company! This action cannot be undone. Only use this if you want to completely reset your Chart of Accounts.</div>'
						);
					}
				}
			},
			{
				fieldname: 'cleanup_warning',
				fieldtype: 'HTML',
				hidden: 1,
				options: ''
			}
		],
		primary_action_label: 'Start Setup',
		primary_action(values) {
			dialog.hide();

			// If cleanup requested, do it first
			if (values.cleanup_type !== 'No cleanup') {
				const delete_all = values.cleanup_type === 'Clean up ALL accounts';

				// Extra confirmation for delete all
				if (delete_all) {
					frappe.confirm(
						'<strong>Are you absolutely sure?</strong><br><br>'
						+ 'This will delete ALL accounts in your Chart of Accounts.<br>'
						+ 'This action cannot be undone!<br><br>'
						+ 'Type "DELETE ALL" to confirm:',
						() => {
							// Get the input value from the prompt
							frappe.prompt({
								fieldname: 'confirmation',
								label: 'Type "DELETE ALL" to confirm',
								fieldtype: 'Data',
								reqd: 1
							}, (values) => {
								if (values.confirmation === 'DELETE ALL') {
									perform_cleanup(frm, true);
								} else {
									frappe.msgprint('Confirmation text did not match. Cleanup cancelled.');
								}
							}, 'Confirm Deletion', 'Delete');
						},
						() => {
							// Cancelled - do nothing
						}
					);
				} else {
					// Regular E-Boekhouden cleanup
					perform_cleanup(frm, false);
				}
			} else {
				// Start import directly
				start_coa_import(frm);
			}
		}
	});

	dialog.show();
}

function perform_cleanup(frm, delete_all_accounts) {
	frappe.call({
		method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.cleanup_chart_of_accounts',
		args: {
			company: frm.doc.company,
			delete_all_accounts
		},
		callback(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				});
				// Continue with import after cleanup
				start_coa_import(frm);
			} else {
				frappe.msgprint({
					title: __('Cleanup Failed'),
					message: r.message.error || 'Unknown error',
					indicator: 'red'
				});
			}
		}
	});
}

function start_coa_import(frm) {
	// Save settings for CoA import
	frm.set_value('migrate_accounts', 1);
	frm.set_value('migrate_customers', 1);
	frm.set_value('migrate_suppliers', 1);
	frm.set_value('migrate_cost_centers', 1);
	frm.set_value('migrate_transactions', 0); // Don't import transactions yet
	frm.set_value('dry_run', 0);

	// Set date range to full range
	const today = frappe.datetime.get_today();
	const tenYearsAgo = frappe.datetime.add_days(today, -3650);
	frm.set_value('date_from', tenYearsAgo);
	frm.set_value('date_to', today);

	// Save and start
	frm.save().then(() => {
		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.start_migration',
			args: {
				migration_name: frm.doc.name,
				setup_only: true // Special flag for CoA setup
			},
			callback(r) {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: __('Chart of Accounts setup started!'),
						indicator: 'green'
					});
					frm.reload_doc();

					// Show progress
					show_migration_progress(frm);

					// After completion, show account type review
					setTimeout(() => {
						check_and_show_account_type_review(frm);
					}, 5000);
				} else {
					frappe.msgprint({
						title: __('Error'),
						message: r.message ? r.message.error : 'Unknown error',
						indicator: 'red'
					});
				}
			}
		});
	});
}

function check_and_show_account_type_review(frm) {
	// Check migration status first
	frappe.call({
		method: 'frappe.client.get',
		args: {
			doctype: 'E-Boekhouden Migration',
			name: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.migration_status === 'Completed') {
				// Migration completed, show account type review
				show_account_type_adjustment_dialog(frm);
			} else if (r.message && r.message.migration_status === 'In Progress') {
				// Still in progress, check again later
				setTimeout(() => {
					check_and_show_account_type_review(frm);
				}, 5000);
			}
		}
	});
}

function show_account_type_adjustment_dialog(frm) {
	// Show brief success message and redirect immediately
	frappe.show_alert({
		message: __('Chart of Accounts imported successfully! Redirecting to account type review...'),
		indicator: 'green'
	});

	// Redirect immediately after brief delay
	setTimeout(() => {
		window.location.href = '/eboekhouden_mapping_review';
	}, 1500);
}

function update_single_account_type(account_name, new_type, company, button) {
	// Show loading state
	button.prop('disabled', true).text('Updating...');

	frappe.call({
		method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.update_account_type_mapping',
		args: {
			account_name, // This is the doctype name, not the account_name field
			new_account_type: new_type,
			company
		},
		callback(r) {
			if (r.message && r.message.success) {
				button.text('✓ Updated').removeClass('btn-primary').addClass('btn-success');
			} else {
				button.prop('disabled', false).text('Update');
				frappe.msgprint({
					title: __('Update Failed'),
					message: r.message.error || 'Unknown error',
					indicator: 'red'
				});
			}
		}
	});
}

function update_all_account_types(dialog, recommendations, company) {
	// Collect all updates
	const updates = [];

	dialog.$wrapper.find('.account-type-select').each(function () {
		const idx = $(this).data('idx');
		const rec = recommendations[idx];
		const new_type = $(this).val();

		if (new_type && new_type !== rec.current_type) {
			updates.push({
				account: rec.account,
				account_name: rec.account_name,
				new_type
			});
		}
	});

	if (updates.length === 0) {
		frappe.msgprint(__('No changes to update'));
		return;
	}

	// Show progress
	frappe.show_alert({
		message: __(`Updating ${updates.length} accounts...`),
		indicator: 'blue'
	});

	// Update accounts one by one
	let completed = 0;
	updates.forEach(update => {
		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.update_account_type_mapping',
			args: {
				account_name: update.account, // Use the doctype name
				new_account_type: update.new_type,
				company
			},
			callback(r) {
				completed++;
				if (completed === updates.length) {
					dialog.hide();
					frappe.show_alert({
						message: __('All account types updated successfully!'),
						indicator: 'green'
					});
				}
			}
		});
	});
}

function handle_import_transactions(frm) {
	// Validate company
	if (!frm.doc.company) {
		frappe.msgprint({
			title: __('Company Required'),
			message: __('Please select a company before importing transactions.'),
			indicator: 'orange'
		});
		return;
	}

	// Check if CoA exists
	frappe.call({
		method: 'frappe.client.get_count',
		args: {
			doctype: 'Account',
			filters: {
				company: frm.doc.company,
				eboekhouden_grootboek_nummer: ['!=', '']
			}
		},
		callback(r) {
			if (r.message === 0) {
				frappe.msgprint({
					title: __('Setup Required'),
					message: __('Please run "Setup Chart of Accounts" first. No E-Boekhouden accounts found.'),
					indicator: 'orange'
				});
				return;
			}

			// Show transaction import dialog
			show_transaction_import_dialog(frm);
		}
	});
}

function show_transaction_import_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: 'Import Transactions',
		fields: [
			{
				label: 'Import Method',
				fieldname: 'import_method',
				fieldtype: 'Select',
				options: 'Recent Transactions (Last 90 days)\nAll Transactions (Complete history)',
				default: 'Recent Transactions (Last 90 days)',
				description: 'Choose how many transactions to import',
				onchange() {
					const method = dialog.get_value('import_method');
					dialog.set_df_property('rest_note', 'hidden', !method.includes('REST'));
					dialog.set_df_property('date_range_section', 'hidden', method.includes('All'));
				}
			},
			{
				fieldname: 'rest_note',
				fieldtype: 'HTML',
				hidden: 1,
				options: '<div class="alert alert-info">REST API will fetch all historical transactions by iterating through mutation IDs. This may take several minutes.</div>'
			},
			{
				fieldname: 'date_range_section',
				fieldtype: 'Section Break',
				label: 'Date Range (Optional)'
			},
			{
				label: 'From Date',
				fieldname: 'date_from',
				fieldtype: 'Date',
				description: 'Leave empty to use auto-detected range'
			},
			{
				label: 'To Date',
				fieldname: 'date_to',
				fieldtype: 'Date',
				description: 'Leave empty to use auto-detected range'
			},
			{
				fieldname: 'options_section',
				fieldtype: 'Section Break',
				label: 'Options'
			},
			{
				label: 'Preview Only',
				fieldname: 'dry_run',
				fieldtype: 'Check',
				default: 0,
				description: 'Check to see what would be imported without making changes'
			}
		],
		primary_action_label: 'Start Import',
		primary_action(values) {
			dialog.hide();

			// Always use REST API now - determine type based on method
			const import_type = values.import_method.includes('Recent') ? 'recent' : 'all';
			import_transactions_rest(frm, values, import_type);
		}
	});

	dialog.show();
}

function import_transactions_soap(frm, options) {
	// Configure for transaction-only import
	frm.set_value('migrate_accounts', 0);
	frm.set_value('migrate_cost_centers', 0);
	frm.set_value('migrate_customers', 1); // Import new customers if needed
	frm.set_value('migrate_suppliers', 1); // Import new suppliers if needed
	frm.set_value('migrate_transactions', 1);
	frm.set_value('dry_run', options.dry_run ? 1 : 0);

	// Set dates
	if (options.date_from) {
		frm.set_value('date_from', options.date_from);
	}
	if (options.date_to) {
		frm.set_value('date_to', options.date_to);
	}

	// Save and start
	frm.save().then(() => {
		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.start_migration',
			args: {
				migration_name: frm.doc.name
			},
			callback(r) {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: __('Transaction import started successfully!'),
						indicator: 'green'
					});
					// Reload and start progress tracking if migration is in progress
					frm.reload_doc().then(() => {
						if (frm.doc.migration_status === 'In Progress') {
							show_migration_progress(frm);
						}
					});
				} else {
					frappe.msgprint({
						title: __('Error'),
						message: r.message ? r.message.error : 'Unknown error',
						indicator: 'red'
					});
				}
			}
		});
	});
}

function import_transactions_rest(frm, options, import_type = 'all') {
	// First check if REST API is configured
	frappe.call({
		method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.check_rest_api_status',
		callback(r) {
			if (!r.message || !r.message.configured) {
				frappe.msgprint({
					title: __('REST API Not Configured'),
					message: __('Please configure the REST API token in E-Boekhouden Settings first.'),
					indicator: 'red'
				});
				return;
			}

			if (!r.message.working) {
				frappe.msgprint({
					title: __('REST API Error'),
					message: r.message.message || __('REST API authentication failed'),
					indicator: 'red'
				});
				return;
			}

			// REST API is working, configure and save the document first
			// Configure for transaction-only import
			frm.set_value('migrate_accounts', 0);
			frm.set_value('migrate_cost_centers', 0);
			frm.set_value('migrate_customers', 1); // Import new customers if needed
			frm.set_value('migrate_suppliers', 1); // Import new suppliers if needed
			frm.set_value('migrate_transactions', 1);
			frm.set_value('dry_run', options.dry_run ? 1 : 0);

			// Set dates based on import type
			if (options.date_from) {
				frm.set_value('date_from', options.date_from);
			} else {
				// Set default dates based on import type
				if (import_type === 'recent') {
					// Last 90 days for recent transactions
					const today = frappe.datetime.get_today();
					const ninety_days_ago = frappe.datetime.add_days(today, -90);
					frm.set_value('date_from', ninety_days_ago);
				} else {
					// For 'all' transactions, clear date filters to import everything
					frm.set_value('date_from', '');
					frm.set_value('date_to', '');
				}
			}

			// Function to continue with import after date is set
			function continue_rest_import() {
				if (options.date_to) {
					frm.set_value('date_to', options.date_to);
				} else {
					// Always use today as end date for complete import
					frm.set_value('date_to', frappe.datetime.get_today());
				}

				// Continue with the rest of the import logic
				finish_rest_import_setup();
			}

			// For non-'all' imports, continue immediately
			if (import_type !== 'all') {
				continue_rest_import();
			}

			function finish_rest_import_setup() {
				// Save document first, then start import
				frm.save().then(() => {
				// Double-check that document exists before calling API
					if (!frm.doc.name) {
						frappe.msgprint({
							title: __('Save Failed'),
							message: __('Document was not saved properly. Please try again.'),
							indicator: 'red'
						});
						return;
					}

					// Add a small delay to ensure save is committed
					setTimeout(() => {
						frappe.call({
							method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.start_transaction_import',
							args: {
								migration_name: frm.doc.name,
								import_type
							},
							callback(r) {
								if (r.message && r.message.success) {
									frappe.show_alert({
										message: __('REST API transaction import started! This may take several minutes.'),
										indicator: 'green'
									});
									// Reload and start progress tracking if migration is in progress
									frm.reload_doc().then(() => {
										if (frm.doc.migration_status === 'In Progress') {
											show_migration_progress(frm);
										}
									});
								} else {
									frappe.msgprint({
										title: __('Import Failed'),
										message: r.message.error || __('Unknown error occurred'),
										indicator: 'red'
									});
								}
							}
						});
					}, 500); // 500ms delay to ensure save is committed
				}).catch(err => {
					frappe.msgprint({
						title: __('Save Failed'),
						message: __('Failed to save migration document: ') + err.message,
						indicator: 'red'
					});
				});
			} // Close finish_rest_import_setup function
		}

	});
}

function show_account_mapping_dialog(frm, mappings) {
	// Show dialog for reviewing account mappings
	let html = '<div style="max-height: 400px; overflow-y: auto;">';
	html += '<p>Review the account mappings below. You can adjust them if needed.</p>';
	html += '<table class="table table-bordered">';
	html += '<thead><tr><th>E-Boekhouden Account</th><th>ERPNext Account</th><th>Type</th></tr></thead>';
	html += '<tbody>';

	// Add mapping rows
	if (mappings && mappings.length > 0) {
		mappings.forEach(m => {
			html += `<tr>
				<td>${m.eb_account}</td>
				<td>${m.erp_account}</td>
				<td>${m.account_type}</td>
			</tr>`;
		});
	}

	html += '</tbody></table>';
	html += '</div>';

	const dialog = new frappe.ui.Dialog({
		title: 'Review Account Mappings',
		fields: [{
			fieldtype: 'HTML',
			options: html
		}],
		size: 'large',
		primary_action_label: 'Confirm & Continue',
		primary_action() {
			dialog.hide();
			frappe.show_alert({
				message: __('Chart of Accounts setup completed successfully!'),
				indicator: 'green'
			});
			// Reload and clear any existing progress tracking (CoA setup is complete)
			frm.reload_doc().then(() => {
				clear_migration_progress(frm);
			});
		},
		secondary_action_label: 'Edit Mappings',
		secondary_action() {
			dialog.hide();
			// Redirect to mapping page
			window.location.href = '/eboekhouden_mapping_review';
		}
	});

	dialog.show();
}

function handle_import_opening_balances(frm) {
	// Validate company
	if (!frm.doc.company) {
		frappe.msgprint({
			title: __('Company Required'),
			message: __('Please select a company before importing opening balances.'),
			indicator: 'orange'
		});
		return;
	}

	// Check if CoA exists
	frappe.call({
		method: 'frappe.client.get_count',
		args: {
			doctype: 'Account',
			filters: {
				company: frm.doc.company,
				eboekhouden_grootboek_nummer: ['!=', '']
			}
		},
		callback(r) {
			if (r.message === 0) {
				frappe.msgprint({
					title: __('Setup Required'),
					message: __('Please run "Setup Chart of Accounts" first. No E-Boekhouden accounts found.'),
					indicator: 'orange'
				});
				return;
			}

			// Show opening balance import dialog
			show_opening_balance_import_dialog(frm);
		}
	});
}

function show_opening_balance_import_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: 'Import Opening Balances',
		fields: [
			{
				fieldname: 'info_section',
				fieldtype: 'HTML',
				options: `<div class="alert alert-info">
					<strong>This will import opening balances from E-Boekhouden:</strong>
					<ul>
						<li><strong>Receivables/Payables:</strong> Uses ERPNext's Opening Invoice Creation Tool</li>
						<li><strong>Other Accounts:</strong> Creates Journal Entries for bank, assets, equity accounts</li>
						<li>Automatically detects and prevents duplicate imports</li>
						<li>Uses proper ERPNext naming conventions (OPB-YYYY-00001)</li>
					</ul>
					<p class="mt-2"><strong>Note:</strong> This is a one-time import. Duplicate opening balances are automatically prevented.</p>
				</div>`
			},
			{
				label: 'Preview Only',
				fieldname: 'dry_run',
				fieldtype: 'Check',
				default: 0,
				description: 'Check to see what would be imported without making changes'
			}
		],
		primary_action_label: 'Import Opening Balances',
		primary_action(values) {
			dialog.hide();
			start_opening_balance_import(frm, values);
		}
	});

	dialog.show();
}

function start_opening_balance_import(frm, options) {
	// Configure for opening balance import only
	frm.set_value('migrate_accounts', 0);
	frm.set_value('migrate_cost_centers', 0);
	frm.set_value('migrate_customers', 0);
	frm.set_value('migrate_suppliers', 0);
	frm.set_value('migrate_transactions', 0);
	frm.set_value('dry_run', options.dry_run ? 1 : 0);

	// Save document first
	frm.save().then(() => {
		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.import_opening_balances_only',
			args: {
				migration_name: frm.doc.name
			},
			callback(r) {
				if (r.message && r.message.success) {
					const result = r.message.result;

					// Show results
					let message = options.dry_run
						? '<strong>Opening Balance Preview:</strong><br><br>'
						: '<strong>Opening Balance Import Completed!</strong><br><br>';

					message += '<strong>Summary:</strong><br>';
					message += `• Total imported: ${result.imported}<br>`;

					if (result.debug_info && result.debug_info.length > 0) {
						message += '<br><strong>Details:</strong><br>';
						result.debug_info.forEach(info => {
							message += `• ${info}<br>`;
						});
					}

					if (result.errors && result.errors.length > 0) {
						message += '<br><strong>Errors:</strong><br>';
						result.errors.forEach(error => {
							message += `• ${error}<br>`;
						});
					}

					frappe.msgprint({
						title: options.dry_run ? __('Opening Balance Preview') : __('Opening Balance Import Complete'),
						message,
						indicator: result.errors && result.errors.length > 0 ? 'orange' : 'green',
						wide: true
					});

					if (!options.dry_run) {
						// Reload and check if progress tracking is needed
						frm.reload_doc().then(() => {
							if (frm.doc.migration_status === 'In Progress') {
								show_migration_progress(frm);
							}
						});
					}
				} else {
					frappe.msgprint({
						title: __('Import Failed'),
						message: r.message ? r.message.error : 'Unknown error',
						indicator: 'red'
					});
				}
			}
		});
	}).catch(err => {
		frappe.msgprint({
			title: __('Save Failed'),
			message: __('Failed to save migration document: ') + err.message,
			indicator: 'red'
		});
	});
}

function add_tools_dropdown(frm) {
	// Add debugging and REST API tools

	// Debug Connection - moved to frm.add_custom_button
	frm.add_custom_button(__('Debug Connection'), () => {
		frappe.call({
			method: 'verenigingen.api.test_eboekhouden_connection.test_eboekhouden_connection',
			freeze: true,
			freeze_message: __('Testing connection...'),
			callback(r) {
				if (r.message && r.message.success) {
					frappe.msgprint({
						title: __('Connection Test Successful'),
						message: __(`Successfully connected to E-Boekhouden API.<br><br>Details:<br>${r.message.message}`),
						indicator: 'green'
					});
				} else {
					frappe.msgprint({
						title: __('Connection Test Failed'),
						message: __(`Failed to connect: ${r.message ? r.message.message : 'Unknown error'}`),
						indicator: 'red'
					});
				}
			}
		});
	}, __('Tools'));

	// Add Data Quality Check
	frm.add_custom_button(__('Check Data Quality'), () => {
		frappe.show_alert({
			message: __('Analyzing data quality...'),
			indicator: 'blue'
		});

		frappe.call({
			method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.check_migration_data_quality',
			args: {
				migration_name: frm.doc.name
			},
			freeze: true,
			freeze_message: __('Analyzing imported data quality...'),
			callback(r) {
				if (r.message && r.message.success) {
					show_data_quality_report(frm, r.message.report);
				} else {
					frappe.msgprint({
						title: __('Quality Check Failed'),
						message: r.message ? r.message.error : 'Unknown error',
						indicator: 'red'
					});
				}
			}
		});
	}, __('Tools'));

	// Add REST API migration button
	frm.add_custom_button(__('Fetch ALL Mutations (REST API)'), () => {
		frappe.confirm(
			__('This will fetch ALL historical mutations using the REST API by iterating through mutation IDs. This may take several minutes. Continue?'),
			() => {
				// Show a dialog with options
				const d = new frappe.ui.Dialog({
					title: 'REST API Full Migration',
					fields: [
						{
							label: 'Start ID',
							fieldname: 'start_id',
							fieldtype: 'Int',
							default: 17,
							description: 'Lowest mutation ID (default: 17)'
						},
						{
							label: 'End ID',
							fieldname: 'end_id',
							fieldtype: 'Int',
							default: 7500,
							description: 'Highest mutation ID (estimated: 7420)'
						},
						{
							label: 'Test Mode',
							fieldname: 'test_mode',
							fieldtype: 'Check',
							default: 1,
							description: 'If checked, only fetch first 100 mutations for testing'
						}
					],
					primary_action_label: 'Start Migration',
					primary_action(values) {
						d.hide();

						const start_id = values.start_id;
						const end_id = values.test_mode ? Math.min(values.start_id + 100, values.end_id) : values.end_id;

						frappe.call({
							method: 'verenigingen.utils.test_rest_migration.test_rest_mutation_fetch',
							args: {
								start_id,
								end_id
							},
							freeze: true,
							freeze_message: __('Fetching mutations from REST API...'),
							callback(r) {
								if (r.message && !r.message.error) {
									let msg = '<b>REST API Migration Results:</b><br><br>';
									msg += `Total Checked: ${r.message.summary.total_checked}<br>`;
									msg += `Found: ${r.message.summary.total_found}<br>`;
									msg += `Not Found: ${r.message.summary.total_not_found}<br>`;
									msg += `Errors: ${r.message.summary.total_errors}<br><br>`;

									msg += '<b>Type Distribution:</b><br>';
									for (const [type, count] of Object.entries(r.message.summary.type_distribution)) {
										msg += `${type}: ${count}<br>`;
									}

									if (r.message.sample_mutations && r.message.sample_mutations.length > 0) {
										msg += '<br><b>Sample Mutations:</b><br>';
										r.message.sample_mutations.forEach(m => {
											msg += `ID ${m.id}: ${m.date} - ${m.description}<br>`;
										});
									}

									frappe.msgprint({
										title: __('REST API Fetch Complete'),
										message: msg,
										indicator: 'green',
										wide: true
									});
								} else {
									frappe.msgprint({
										title: __('REST API Fetch Failed'),
										message: r.message ? r.message.error : 'Unknown error',
										indicator: 'red'
									});
								}
							}
						});
					}
				});
				d.show();
			}
		);
	}, __('Tools'));
}

function show_data_quality_report(frm, report) {
	// Display data quality report in a comprehensive dialog
	let report_html = '<div class="data-quality-report">';

	// Header
	report_html += `
		<div style="margin-bottom: 20px;">
			<h4>Data Quality Report</h4>
			<p style="color: #666;">Generated: ${frappe.datetime.str_to_user(report.timestamp)}</p>
			<p style="color: #666;">Company: ${report.company}</p>
		</div>
	`;

	// Issues Summary
	if (report.issues && report.issues.length > 0) {
		report_html += '<div style="margin-bottom: 20px;">';
		report_html += `<h5 style="color: #d32f2f;">Issues Found (${report.issues.length})</h5>`;
		report_html += '<ul style="list-style-type: disc; padding-left: 20px;">';
		report.issues.forEach(issue => {
			report_html += '<li style="margin-bottom: 10px;">';
			report_html += `<strong>${issue.type}:</strong> ${issue.description}`;
			if (issue.count) {
				report_html += ` <span style="color: #666;">(${issue.count} records)</span>`;
			}
			if (issue.examples && issue.examples.length > 0) {
				report_html += '<ul style="margin-top: 5px; font-size: 0.9em; color: #666;">';
				issue.examples.forEach(example => {
					report_html += `<li>${example}</li>`;
				});
				report_html += '</ul>';
			}
			report_html += '</li>';
		});
		report_html += '</ul>';
		report_html += '</div>';
	} else {
		report_html += '<div style="margin-bottom: 20px; color: #4caf50;">';
		report_html += '<h5>✓ No Quality Issues Found</h5>';
		report_html += '<p>All imported data appears to be complete and properly mapped.</p>';
		report_html += '</div>';
	}

	// Statistics
	if (report.statistics && Object.keys(report.statistics).length > 0) {
		report_html += '<div style="margin-bottom: 20px;">';
		report_html += '<h5>Import Statistics</h5>';
		report_html += '<table style="width: 100%; border-collapse: collapse;">';
		for (const [key, value] of Object.entries(report.statistics)) {
			report_html += '<tr style="border-bottom: 1px solid #e0e0e0;">';
			report_html += `<td style="padding: 8px;">${key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</td>`;
			report_html += `<td style="padding: 8px; text-align: right; font-weight: bold;">${value}</td>`;
			report_html += '</tr>';
		}
		report_html += '</table>';
		report_html += '</div>';
	}

	// Recommendations
	if (report.recommendations && report.recommendations.length > 0) {
		report_html += '<div style="margin-bottom: 20px;">';
		report_html += '<h5>Recommendations</h5>';
		report_html += '<ol style="padding-left: 20px;">';
		report.recommendations.forEach(rec => {
			// Handle both string and object recommendations
			if (typeof rec === 'string') {
				report_html += `<li style="margin-bottom: 8px;">${rec}</li>`;
			} else if (typeof rec === 'object' && rec !== null) {
				// Format object recommendation
				let recText = '';
				if (rec.priority) {
					recText += `<span class="badge badge-${rec.priority === 'high' ? 'danger' : rec.priority === 'medium' ? 'warning' : 'info'}">${rec.priority.toUpperCase()}</span> `;
				}
				if (rec.action) {
					recText += `<strong>${rec.action}</strong>`;
				}
				if (rec.description) {
					recText += `: ${rec.description}`;
				}
				if (rec.impact) {
					recText += ` <em>(${rec.impact})</em>`;
				}
				report_html += `<li style="margin-bottom: 8px;">${recText || JSON.stringify(rec)}</li>`;
			}
		});
		report_html += '</ol>';
		report_html += '</div>';
	}

	report_html += '</div>';

	// Show in dialog
	const dialog = new frappe.ui.Dialog({
		title: __('Data Quality Report'),
		size: 'large',
		fields: [{
			fieldtype: 'HTML',
			fieldname: 'report_html'
		}],
		primary_action() {
			dialog.hide();
			// Update quality check timestamp
			if (frm.doc.name) {
				frappe.db.set_value('E-Boekhouden Migration', frm.doc.name,
					'last_quality_check', frappe.datetime.now_datetime());
			}
		},
		primary_action_label: __('Close')
	});

	dialog.fields_dict.report_html.$wrapper.html(report_html);
	dialog.show();
}

function handle_import_single_mutation(frm) {
	// Show dialog to enter mutation ID
	const dialog = new frappe.ui.Dialog({
		title: __('Import Single Mutation'),
		fields: [
			{
				fieldtype: 'Data',
				fieldname: 'mutation_id',
				label: __('Mutation ID'),
				reqd: 1,
				description: __('Enter the eBoekhouden mutation ID to import (e.g., 6316)')
			},
			{
				fieldtype: 'Check',
				fieldname: 'overwrite_existing',
				label: __('Overwrite if exists'),
				default: 1,
				description: __('Delete existing journal entry if it already exists')
			}
		],
		primary_action(values) {
			dialog.hide();

			frappe.show_alert({
				message: __('Importing mutation {0}...', [values.mutation_id]),
				indicator: 'blue'
			});

			frappe.call({
				method: 'verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration.import_single_mutation',
				args: {
					migration_name: frm.doc.name,
					mutation_id: values.mutation_id,
					overwrite_existing: values.overwrite_existing
				},
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Successfully imported mutation {0}', [values.mutation_id]),
							indicator: 'green'
						});

						// Show results
						const result = r.message;
						let message = '<strong>Import Results:</strong><br>';
						message += `Mutation ID: ${result.mutation_id}<br>`;
						message += `Document Type: ${result.document_type}<br>`;
						message += `Document Name: ${result.document_name}<br>`;

						if (result.debug_info && result.debug_info.length > 0) {
							message += '<br><strong>Debug Info:</strong><br>';
							result.debug_info.forEach(info => {
								message += `• ${info}<br>`;
							});
						}

						frappe.msgprint({
							title: __('Import Complete'),
							message,
							indicator: 'green'
						});
					} else {
						frappe.show_alert({
							message: __('Failed to import mutation {0}', [values.mutation_id]),
							indicator: 'red'
						});

						if (r.message && r.message.error) {
							frappe.msgprint({
								title: __('Import Error'),
								message: r.message.error,
								indicator: 'red'
							});
						}
					}
				},
				error(r) {
					frappe.show_alert({
						message: __('Error importing mutation {0}', [values.mutation_id]),
						indicator: 'red'
					});
				}
			});
		},
		primary_action_label: __('Import Mutation')
	});

	dialog.show();
}
