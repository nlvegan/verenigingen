/**
 * @fileoverview Direct Debit Batch DocType Frontend Controller for Verenigingen Association Management
 *
 * This controller manages the Direct Debit Batch DocType interface, handling SEPA direct debit
 * batch processing for automated payment collection from association members. It orchestrates
 * the complete workflow from invoice aggregation to bank submission and payment reconciliation.
 *
 * @description Business Context:
 * Direct Debit Batches are used to collect membership fees, donations, and other payments
 * automatically from members who have provided SEPA mandates. The system ensures compliance
 * with European banking regulations and Dutch financial requirements while providing
 * efficient payment processing for the association.
 *
 * @description Key Features:
 * - SEPA direct debit batch creation and management
 * - Mandate validation and compliance checking
 * - SEPA XML file generation for bank submission
 * - Payment processing status tracking
 * - Return processing and error handling
 * - Integration with ERPNext invoicing system
 * - Compliance with Dutch banking standards
 *
 * @description Workflow Stages:
 * 1. Draft: Batch creation and invoice loading
 * 2. Generated: SEPA file generation and validation
 * 3. Submitted: Bank submission and processing
 * 4. Processed: Payment completion and reconciliation
 * 5. Failed/Returned: Error handling and retry logic
 *
 * @description Integration Points:
 * - Links to Sales Invoice for payment collection
 * - Connects to SEPA Mandate for authorization validation
 * - Integrates with Payment Entry for accounting
 * - Coordinates with Member DocType for payment methods
 * - Links to banking systems for file submission
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API
 * @requires sepa-utils.js - SEPA processing utilities
 * @requires payment-utils.js - Payment processing utilities
 *
 * @example
 * // Controller is loaded automatically for Direct Debit Batch forms
 * frappe.ui.form.on('Direct Debit Batch', {
 *   refresh: function(frm) {
 *     // Batch form initialization and status-based UI
 *   }
 * });
 */

/**
 * Main Direct Debit Batch DocType Form Controller
 *
 * Handles the complete SEPA direct debit batch lifecycle including creation,
 * validation, file generation, bank submission, and payment reconciliation.
 */
frappe.ui.form.on('Direct Debit Batch', {
	/**
	 * Form Refresh Event Handler
	 *
	 * Configures the batch processing interface based on current status and workflow stage.
	 * Manages status indicators, action buttons, and validation controls for SEPA processing.
	 *
	 * @description Status-Based UI Configuration:
	 * - Draft: Shows invoice loading and mandate validation controls
	 * - Generated: Enables SEPA file generation and download
	 * - Submitted: Provides bank submission and processing controls
	 * - Processed: Shows completion status and reconciliation options
	 *
	 * @description SEPA Compliance Features:
	 * - Validates mandate authorization and validity
	 * - Ensures proper SEPA XML format generation
	 * - Manages payment processing deadlines and constraints
	 * - Handles return processing and error recovery
	 *
	 * @param {Object} frm - Frappe Form object containing batch document
	 * @param {string} frm.doc.status - Current batch processing status
	 * @param {boolean} frm.doc.sepa_file_generated - SEPA file generation flag
	 * @param {Array} frm.doc.invoices - Collection of invoices in the batch
	 *
	 * @example
	 * // Status-based button configuration:
	 * // Draft: "Load Unpaid Invoices", "Validate Mandates"
	 * // Generated: "Generate SEPA File", "Download SEPA File"
	 * // Submitted: "Submit to Bank", "Process Returns"
	 */
	refresh: function(frm) {
		// Add status indicator with color
		if (frm.doc.status) {
			const status_colors = {
				'Draft': 'gray',
				'Generated': 'blue',
				'Submitted': 'orange',
				'Processed': 'green',
				'Failed': 'red',
				'Cancelled': 'gray',
				'Partially Processed': 'yellow'
			};
			frm.page.set_indicator(__(frm.doc.status), status_colors[frm.doc.status] || 'gray');
		}

		// Set field properties based on status
		set_field_properties(frm);

		// Add batch summary section
		add_batch_summary(frm);

		// Add action buttons based on status
		if(frm.doc.docstatus === 0) {
			// Draft state
			frm.add_custom_button(__('Load Unpaid Invoices'), function() {
				load_unpaid_invoices(frm);
			}, __('Get Items'));

			frm.add_custom_button(__('Validate Mandates'), function() {
				validate_mandates(frm);
			});
		}

		if(frm.doc.docstatus === 1 && !frm.doc.sepa_file_generated) {
			frm.add_custom_button(__('Generate SEPA File'), function() {
				generate_sepa_file_dialog(frm);
			}, __('Actions')).addClass('btn-primary');
		}

		if(frm.doc.docstatus === 1 && frm.doc.sepa_file_generated && frm.doc.status !== 'Processed') {
			frm.add_custom_button(__('Submit to Bank'), function() {
				submit_to_bank_dialog(frm);
			}, __('Actions')).addClass('btn-primary');

			frm.add_custom_button(__('Download SEPA File'), function() {
				window.open(frm.doc.sepa_file);
			});
		}

		if(frm.doc.docstatus === 1 && frm.doc.status === 'Submitted') {
			frm.add_custom_button(__('Process Returns'), function() {
				process_returns_dialog(frm);
			}, __('Actions'));

			frm.add_custom_button(__('Mark as Processed'), function() {
				mark_as_processed_dialog(frm);
			}, __('Actions')).addClass('btn-primary');
		}

		// Add quick filters for invoice table
		if (frm.doc.invoices && frm.doc.invoices.length > 0) {
			add_invoice_filters(frm);
		}
	},

	onload: function(frm) {
		// Set field properties when form loads
		set_field_properties(frm);

		// Set up real-time updates
		setup_realtime_updates(frm);

		// Add custom CSS for better UI
		add_custom_styles(frm);

		// Set query filters
		frm.set_query('invoice', 'invoices', function() {
			return {
				filters: {
					'status': ['in', ['Unpaid', 'Overdue']],
					'docstatus': 1
				}
			};
		});
	},

	batch_type: function(frm) {
		// Update help text and warnings based on batch type
		const batch_info = {
			'FRST': {
				help: __('First collection - Use for new mandates'),
				warning: __('Ensure all mandates are properly signed before using FRST')
			},
			'RCUR': {
				help: __('Recurring collection - Use for existing mandates'),
				warning: null
			},
			'OOFF': {
				help: __('One-off collection - Single payment only'),
				warning: __('Mandates will not be reusable after this collection')
			},
			'FNAL': {
				help: __('Final collection - Last payment before mandate cancellation'),
				warning: __('Mandates will be cancelled after this collection')
			}
		};

		const info = batch_info[frm.doc.batch_type];
		if (info) {
			frm.set_df_property('batch_type', 'description', info.help);
			if (info.warning) {
				frappe.msgprint({
					title: __('Important'),
					message: info.warning,
					indicator: 'orange'
				});
			}
		}
	},

	batch_date: function(frm) {
		// Validate collection date (must be at least 2 business days in future)
		if (frm.doc.batch_date) {
			const today = frappe.datetime.get_today();
			const batch_date = frm.doc.batch_date;
			const days_diff = frappe.datetime.get_diff(batch_date, today);

			if (days_diff < 2) {
				frappe.msgprint({
					title: __('Warning'),
					message: __('Collection date should be at least 2 business days in the future'),
					indicator: 'orange'
				});
			}
		}
	},

	generate_sepa_file: function(frm) {
		// Handle button field trigger for SEPA file generation
		if (frm.doc.docstatus !== 1) {
			frappe.msgprint(__('Please submit the batch before generating SEPA file'));
			return;
		}

		// Use the dialog approach for consistency
		generate_sepa_file_dialog(frm);
	}
});

// Child table events
frappe.ui.form.on('Direct Debit Invoice', {
	invoices_add: function(frm, cdt, cdn) {
		// Auto-populate mandate info when invoice is selected
		const row = locals[cdt][cdn];
		if (row.invoice) {
			frappe.call({
				method: 'verenigingen.api.sepa_batch_ui.get_invoice_mandate_info',
				args: { invoice: row.invoice },
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, 'iban', r.message.iban);
						frappe.model.set_value(cdt, cdn, 'bic', r.message.bic);
						frappe.model.set_value(cdt, cdn, 'mandate_reference', r.message.mandate_reference);
						frappe.model.set_value(cdt, cdn, 'mandate_date', r.message.mandate_date);
					}
				}
			});
		}
	},

	invoices_remove: function(frm) {
		// Update totals when invoice is removed
		update_batch_totals(frm);
	},

	amount: function(frm) {
		// Update totals when amount changes
		update_batch_totals(frm);
	}
});

// Helper function to update batch totals
function update_batch_totals(frm) {
	const total_amount = frm.doc.invoices.reduce((sum, invoice) => sum + (invoice.amount || 0), 0);
	frm.set_value('total_amount', total_amount);
	frm.set_value('entry_count', frm.doc.invoices.length);
}

// Helper functions
function add_batch_summary(frm) {
	if (!frm.doc.invoices || frm.doc.invoices.length === 0) return;

	const summary = calculate_batch_summary(frm);

	const summary_html = `
        <div class="row dashboard-section">
            <div class="col-sm-3">
                <div class="stat-card">
                    <div class="stat-label">${__('Total Invoices')}</div>
                    <div class="stat-value">${summary.total_count}</div>
                </div>
            </div>
            <div class="col-sm-3">
                <div class="stat-card">
                    <div class="stat-label">${__('Total Amount')}</div>
                    <div class="stat-value">€${format_currency(summary.total_amount)}</div>
                </div>
            </div>
            <div class="col-sm-3">
                <div class="stat-card success">
                    <div class="stat-label">${__('Ready')}</div>
                    <div class="stat-value">${summary.ready_count}</div>
                    <div class="stat-subtitle">€${format_currency(summary.ready_amount)}</div>
                </div>
            </div>
            <div class="col-sm-3">
                <div class="stat-card warning">
                    <div class="stat-label">${__('Issues')}</div>
                    <div class="stat-value">${summary.issue_count}</div>
                    <div class="stat-subtitle">${summary.issue_count > 0 ? __('Need attention') : __('All good')}</div>
                </div>
            </div>
        </div>
    `;

	// Add or update summary section
	if (!frm.fields_dict.batch_summary_html) {
		frm.set_df_property('section_break_1', 'label', __('Batch Summary'));
		frm.add_field({
			fieldname: 'batch_summary_html',
			fieldtype: 'HTML',
			options: summary_html
		}, 'section_break_1');
	} else {
		$(frm.fields_dict.batch_summary_html.wrapper).html(summary_html);
	}
}

function calculate_batch_summary(frm) {
	let summary = {
		total_count: frm.doc.invoices.length,
		total_amount: 0,
		ready_count: 0,
		ready_amount: 0,
		issue_count: 0
	};

	frm.doc.invoices.forEach(inv => {
		summary.total_amount += inv.amount || 0;

		if (inv.iban && inv.mandate_reference) {
			summary.ready_count++;
			summary.ready_amount += inv.amount || 0;
		} else {
			summary.issue_count++;
		}
	});

	return summary;
}

function add_invoice_filters(frm) {
	// Add filter buttons above the invoice table
	const filter_html = `
        <div class="invoice-filters mb-3">
            <button class="btn btn-xs btn-default filter-btn active" data-filter="all">
                ${__('All')} (${frm.doc.invoices.length})
            </button>
            <button class="btn btn-xs btn-default filter-btn" data-filter="ready">
                ${__('Ready')} (<span class="ready-count">0</span>)
            </button>
            <button class="btn btn-xs btn-default filter-btn" data-filter="issues">
                ${__('Has Issues')} (<span class="issue-count">0</span>)
            </button>
            <button class="btn btn-xs btn-default filter-btn" data-filter="processed">
                ${__('Processed')} (<span class="processed-count">0</span>)
            </button>
        </div>
    `;

	$(frm.fields_dict.invoices.wrapper).prepend(filter_html);

	// Update counts
	update_filter_counts(frm);

	// Add click handlers
	$(frm.fields_dict.invoices.wrapper).find('.filter-btn').on('click', function() {
		const filter = $(this).data('filter');
		apply_invoice_filter(frm, filter);

		// Update active state
		$(this).siblings().removeClass('active');
		$(this).addClass('active');
	});
}

function update_filter_counts(frm) {
	let counts = { ready: 0, issues: 0, processed: 0 };

	frm.doc.invoices.forEach(inv => {
		if (inv.status === 'Successful' || inv.status === 'Failed') {
			counts.processed++;
		} else if (inv.iban && inv.mandate_reference) {
			counts.ready++;
		} else {
			counts.issues++;
		}
	});

	$(frm.fields_dict.invoices.wrapper).find('.ready-count').text(counts.ready);
	$(frm.fields_dict.invoices.wrapper).find('.issue-count').text(counts.issues);
	$(frm.fields_dict.invoices.wrapper).find('.processed-count').text(counts.processed);
}

function apply_invoice_filter(frm, filter) {
	const rows = $(frm.fields_dict.invoices.wrapper).find('.grid-row');

	rows.each(function(idx) {
		const row_data = frm.doc.invoices[idx];
		let show = true;

		if (filter === 'ready') {
			show = row_data.iban && row_data.mandate_reference;
		} else if (filter === 'issues') {
			show = !row_data.iban || !row_data.mandate_reference;
		} else if (filter === 'processed') {
			show = row_data.status === 'Successful' || row_data.status === 'Failed';
		}

		$(this).toggle(show);
	});
}

function load_unpaid_invoices(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Load Unpaid Invoices'),
		fields: [
			{
				fieldname: 'date_range',
				label: __('Due Date Range'),
				fieldtype: 'Select',
				options: [
					{ value: 'overdue', label: __('Overdue Only') },
					{ value: 'due_this_week', label: __('Due This Week') },
					{ value: 'due_this_month', label: __('Due This Month') },
					{ value: 'all', label: __('All Unpaid') }
				],
				default: 'overdue'
			},
			{
				fieldname: 'membership_type',
				label: __('Membership Type'),
				fieldtype: 'Link',
				options: 'Membership Type'
			},
			{
				fieldname: 'limit',
				label: __('Maximum Invoices'),
				fieldtype: 'Int',
				default: 100
			}
		],
		primary_action_label: __('Load Invoices'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.api.sepa_batch_ui.load_unpaid_invoices',
				args: values,
				callback: function(r) {
					if (r.message && r.message.length > 0) {
						// Set defaults if new batch
						if (!frm.doc.batch_description) {
							frm.set_value('batch_date', values.collection_date || frappe.datetime.get_today());
							frm.set_value('batch_description', `Membership payments batch - ${frappe.datetime.get_today()}`);
							frm.set_value('batch_type', 'RCUR');
							frm.set_value('currency', 'EUR');
						}

						// Add invoices to batch
						r.message.forEach(inv => {
							const exists = frm.doc.invoices.find(i => i.invoice === inv.invoice);
							if (!exists) {
								frm.add_child('invoices', inv);
							}
						});
						frm.refresh_field('invoices');

						// Update totals after adding invoices
						const total_amount = frm.doc.invoices.reduce((sum, invoice) => sum + (invoice.amount || 0), 0);
						frm.set_value('total_amount', total_amount);
						frm.set_value('entry_count', frm.doc.invoices.length);

						frm.dirty();

						frappe.show_alert({
							message: __('Loaded {0} invoices', [r.message.length]),
							indicator: 'green'
						});

						dialog.hide();
						add_batch_summary(frm);
					} else {
						frappe.msgprint(__('No unpaid invoices found matching criteria'));
					}
				}
			});
		}
	});

	dialog.show();
}

function validate_mandates(frm) {
	if (!frm.doc.invoices || frm.doc.invoices.length === 0) {
		frappe.msgprint(__('No invoices to validate'));
		return;
	}

	frappe.show_progress(__('Validating'), 0, frm.doc.invoices.length);
	let processed = 0;
	let clientValidationErrors = [];

	// First do client-side IBAN validation if available
	if (window.IBANValidator) {
		frm.doc.invoices.forEach((inv, idx) => {
			if (inv.iban) {
				const validation = window.IBANValidator.validate(inv.iban);
				if (!validation.valid) {
					clientValidationErrors.push({
						idx: idx,
						invoice: inv.invoice,
						error: validation.error
					});
				}
			}
		});

		// Show client validation errors if any
		if (clientValidationErrors.length > 0) {
			let errorMsg = __('Invalid IBANs found:') + '<br>';
			clientValidationErrors.forEach(err => {
				errorMsg += `<br>Invoice ${err.invoice}: ${err.error}`;
			});
			frappe.msgprint({
				title: __('IBAN Validation Failed'),
				message: errorMsg,
				indicator: 'red'
			});
		}
	}

	frm.doc.invoices.forEach((inv, idx) => {
		frappe.call({
			method: 'verenigingen.api.sepa_batch_ui.validate_invoice_mandate',
			args: {
				invoice: inv.invoice,
				member: inv.member
			},
			callback: function(r) {
				processed++;
				frappe.show_progress(__('Validating'), processed, frm.doc.invoices.length);

				if (r.message) {
					if (r.message.valid) {
						// Format IBAN if validator is available
						let iban = r.message.iban;
						if (window.IBANValidator && iban) {
							const validation = window.IBANValidator.validate(iban);
							if (validation.valid) {
								iban = validation.formatted;
							}
						}

						frappe.model.set_value(inv.doctype, inv.name, 'iban', iban);
						frappe.model.set_value(inv.doctype, inv.name, 'bic', r.message.bic);
						frappe.model.set_value(inv.doctype, inv.name, 'mandate_reference', r.message.mandate_reference);
						frappe.model.set_value(inv.doctype, inv.name, 'mandate_date', r.message.mandate_date);
					} else {
						frappe.model.set_value(inv.doctype, inv.name, 'status', 'Invalid');
						frappe.model.set_value(inv.doctype, inv.name, 'result_message', r.message.error);
					}
				}

				if (processed === frm.doc.invoices.length) {
					frappe.hide_progress();
					frm.refresh_field('invoices');
					add_batch_summary(frm);
					update_filter_counts(frm);
				}
			}
		});
	});
}

function generate_sepa_file_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Generate SEPA File'),
		fields: [
			{
				fieldname: 'collection_date',
				label: __('Collection Date'),
				fieldtype: 'Date',
				default: frm.doc.batch_date,
				reqd: 1,
				description: __('Date when payments will be collected')
			},
			{
				fieldname: 'test_mode',
				label: __('Test Mode'),
				fieldtype: 'Check',
				default: 0,
				description: __('Generate file in test mode (not for production use)')
			}
		],
		primary_action_label: __('Generate'),
		primary_action(values) {
			frm.set_value('batch_date', values.collection_date);

			frappe.call({
				method: 'generate_sepa_xml',
				doc: frm.doc,
				callback: function(r) {
					if (!r.exc) {
						frm.reload_doc();
						frappe.show_alert({
							message: __('SEPA file generated successfully'),
							indicator: 'green'
						});
						dialog.hide();
					}
				}
			});
		}
	});

	dialog.show();
}

function submit_to_bank_dialog(frm) {
	frappe.confirm(
		__('Are you sure you want to submit this batch to the bank? This action cannot be undone.'),
		function() {
			frappe.call({
				method: 'process_batch',
				doc: frm.doc,
				callback: function(r) {
					if (!r.exc) {
						frm.reload_doc();
						frappe.show_alert({
							message: __('Batch submitted to bank successfully'),
							indicator: 'blue'
						});
					}
				}
			});
		}
	);
}

function process_returns_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Process Return File'),
		fields: [
			{
				fieldname: 'return_file',
				label: __('Return File (pain.002)'),
				fieldtype: 'Attach',
				reqd: 1,
				description: __('Upload the return file from your bank')
			}
		],
		primary_action_label: __('Process'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.utils.sepa_reconciliation.process_sepa_return_file',
				args: {
					file_content: values.return_file,
					file_type: 'pain.002'
				},
				callback: function(r) {
					if (r.message) {
						frappe.msgprint(
							__('Processed {0} of {1} returns', [r.message.processed, r.message.total])
						);
						frm.reload_doc();
						dialog.hide();
					}
				}
			});
		}
	});

	dialog.show();
}

function mark_as_processed_dialog(frm) {
	// Show summary of what will happen
	const summary = calculate_batch_summary(frm);

	const dialog = new frappe.ui.Dialog({
		title: __('Mark Batch as Processed'),
		fields: [
			{
				fieldname: 'summary_html',
				fieldtype: 'HTML',
				options: `
                    <div class="alert alert-info">
                        <p>${__('This will create payment entries for all successful collections.')}</p>
                        <ul>
                            <li>${__('Ready for processing')}: <strong>${summary.ready_count}</strong> ${__('invoices')}</li>
                            <li>${__('Total amount')}: <strong>€${format_currency(summary.ready_amount)}</strong></li>
                        </ul>
                    </div>
                `
			},
			{
				fieldname: 'confirm',
				label: __('I confirm that the bank has processed this batch'),
				fieldtype: 'Check',
				reqd: 1
			}
		],
		primary_action_label: __('Process Payments'),
		primary_action(values) {
			if (!values.confirm) return;

			frappe.show_progress(__('Processing Payments'), 0, 100);

			frappe.call({
				method: 'mark_invoices_as_paid',
				doc: frm.doc,
				callback: function(r) {
					frappe.hide_progress();
					if (!r.exc && r.message) {
						frm.reload_doc();
						frappe.msgprint(
							__('Successfully processed {0} payments', [r.message])
						);
						dialog.hide();
					}
				}
			});
		}
	});

	dialog.show();
}

function setup_realtime_updates(frm) {
	if (!frm.is_new()) {
		frappe.realtime.on('dd_batch_update_' + frm.doc.name, function(data) {
			if (data.message) {
				frappe.show_alert({
					message: data.message,
					indicator: data.indicator || 'blue'
				});
			}
			if (data.reload) {
				frm.reload_doc();
			}
		});
	}
}

function add_custom_styles() {
	if (!$('#dd-batch-custom-styles').length) {
		$('<style id="dd-batch-custom-styles">').html(`
            .stat-card {
                background: #f8f9fa;
                border-radius: 8px;
                padding: 20px;
                text-align: center;
                margin-bottom: 15px;
                border: 1px solid #e9ecef;
                transition: all 0.3s ease;
            }
            .stat-card:hover {
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            .stat-card.success {
                border-left: 4px solid #28a745;
            }
            .stat-card.warning {
                border-left: 4px solid #ffc107;
            }
            .stat-label {
                color: #6c757d;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-bottom: 5px;
            }
            .stat-value {
                font-size: 24px;
                font-weight: 600;
                color: #212529;
            }
            .stat-subtitle {
                font-size: 14px;
                color: #6c757d;
                margin-top: 5px;
            }
            .invoice-filters {
                padding: 10px 0;
                border-bottom: 1px solid #e9ecef;
            }
            .filter-btn {
                margin-right: 10px;
            }
            .filter-btn.active {
                background-color: #007bff;
                color: white;
            }
            .dashboard-section {
                margin-bottom: 20px;
            }
        `).appendTo('head');
	}
}

function format_currency(amount) {
	return new Intl.NumberFormat('nl-NL', {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2
	}).format(amount || 0);
}

// Set field properties based on batch status
function set_field_properties(frm) {
	// Disable editing fields after generation or submission
	const is_generated = frm.doc.status === 'Generated' ||
                        frm.doc.status === 'Submitted' ||
                        frm.doc.status === 'Processed';

	// Fields to disable when batch is generated/submitted
	const fields_to_disable = ['batch_date', 'batch_description', 'batch_type', 'currency'];

	// Disable fields based on status
	fields_to_disable.forEach(field => {
		frm.set_df_property(field, 'read_only', is_generated || frm.doc.docstatus === 1);
	});

	// Special handling for invoices table
	frm.set_df_property('invoices', 'read_only', is_generated || frm.doc.docstatus === 1);

	// Disable add row button for invoices if batch is generated/submitted
	if (is_generated || frm.doc.docstatus === 1) {
		frm.set_df_property('invoices', 'cannot_add_rows', true);
		frm.set_df_property('invoices', 'cannot_delete_rows', true);
	} else {
		frm.set_df_property('invoices', 'cannot_add_rows', false);
		frm.set_df_property('invoices', 'cannot_delete_rows', false);
	}
}
