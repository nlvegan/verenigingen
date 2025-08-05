/**
 * @fileoverview MT940 Import DocType Controller for Verenigingen Association Management
 *
 * This controller manages the import and processing of MT940 bank statement files,
 * providing comprehensive bank transaction import capabilities with extensive
 * debugging and validation tools for financial data integration.
 *
 * @description Business Context:
 * MT940 Import enables automated processing of standardized bank statement files
 * in the MT940 format, commonly used by European banks for statement data exchange:
 * - Automated bank transaction import from MT940 files
 * - Duplicate detection and prevention mechanisms
 * - Bank account reconciliation and validation
 * - Company assignment based on bank account configuration
 * - Comprehensive debugging and troubleshooting tools
 * - Integration with ERPNext financial modules
 *
 * @description Key Features:
 * - MT940 file format parsing and validation
 * - Bank transaction creation with proper account mapping
 * - Duplicate transaction detection with sophisticated algorithms
 * - Debug modes for troubleshooting import issues
 * - Statement date range extraction and validation
 * - Status tracking throughout import lifecycle
 * - Integration with Bank Transaction management
 *
 * @description Integration Points:
 * - Bank Account management for account validation
 * - Bank Transaction creation for financial records
 * - Company assignment for proper financial allocation
 * - File attachment system for statement storage
 * - Duplicate detection algorithms for data integrity
 * - Financial reporting integration for statement analysis
 *
 * @description Technical Features:
 * - MT940 format compliance and parsing
 * - Error handling with detailed diagnostic information
 * - Progress tracking and status reporting
 * - Comprehensive debug utilities for troubleshooting
 * - Statement validation and integrity checks
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.ui.form
 * @requires frappe.call
 * @requires frappe.ui.Dialog
 * @requires frappe.db
 *
 * @example
 * // The controller automatically handles:
 * // - MT940 file upload and processing workflow
 * // - Bank account validation and company assignment
 * // - Debug utilities for troubleshooting import issues
 * // - Transaction viewing and reconciliation tools
 */

// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('MT940 Import', {
	refresh(frm) {
		// Add custom buttons
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Process Import'), () => {
				// Submit the document to trigger import
				frm.submit();
			}).addClass('btn-primary');

			frm.add_custom_button(__('Test/Debug'), () => {
				// Call debug function
				if (!frm.doc.mt940_file || !frm.doc.bank_account) {
					frappe.msgprint(__('Please select a bank account and upload an MT940 file first.'));
					return;
				}

				frappe.call({
					method: 'verenigingen.verenigingen.doctype.mt940_import.mt940_import.debug_import',
					args: {
						bank_account: frm.doc.bank_account,
						file_url: frm.doc.mt940_file
					},
					callback(r) {
						if (r.message) {
							let html = '<div class="debug-results">';
							html += '<h4>Debug Results</h4>';
							html += `<pre>${JSON.stringify(r.message, null, 2)}</pre>`;
							html += '</div>';

							const dialog = new frappe.ui.Dialog({
								title: 'MT940 Debug Results',
								fields: [{
									fieldtype: 'HTML',
									options: html
								}]
							});
							dialog.show();
						}
					}
				});
			});

			frm.add_custom_button(__('Debug Duplicates'), () => {
				// Call duplicate detection debug function - use same approach as existing debug
				if (!frm.doc.mt940_file || !frm.doc.bank_account) {
					frappe.msgprint(__('Please select a bank account and upload an MT940 file first.'));
					return;
				}

				frappe.call({
					method: 'verenigingen.verenigingen.doctype.mt940_import.mt940_import.debug_duplicates',
					args: {
						bank_account: frm.doc.bank_account,
						file_url: frm.doc.mt940_file
					},
					callback(r) {
						if (r.message) {
							let html = '<div class="duplicate-debug-results">';
							html += '<h4>Duplicate Detection Analysis</h4>';
							html += `<pre>${JSON.stringify(r.message, null, 2)}</pre>`;
							html += '</div>';

							const dialog = new frappe.ui.Dialog({
								title: 'Duplicate Detection Debug',
								fields: [{
									fieldtype: 'HTML',
									options: html
								}]
							});
							dialog.show();
						}
					}
				});
			});
		}

		// Show import results if completed
		if (frm.doc.import_status === 'Completed') {
			frm.add_custom_button(__('View Bank Transactions'), () => {
				// Use statement date range if available, otherwise fall back to creation date
				const filters = {
					bank_account: frm.doc.bank_account
				};

				if (frm.doc.statement_from_date && frm.doc.statement_to_date) {
					// Use the actual statement date range
					filters['date'] = ['between', [frm.doc.statement_from_date, frm.doc.statement_to_date]];
				} else {
					// Fallback to creation date range
					filters['creation'] = ['>', frappe.datetime.add_days(frm.doc.creation, -1)];
				}

				frappe.set_route('List', 'Bank Transaction', filters);
			});
		}

		// Set help text
		frm.set_intro(__('Upload an MT940 bank statement file to import bank transactions. The file will be processed when you submit this document.'));
	},

	bank_account(frm) {
		// Auto-set company when bank account is selected
		if (frm.doc.bank_account) {
			frappe.db.get_value('Bank Account', frm.doc.bank_account, 'company')
				.then(r => {
					if (r.message && r.message.company) {
						frm.set_value('company', r.message.company);
					}
				});
		}
	}
});
