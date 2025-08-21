/**
 * @fileoverview Mijnrood CSV Import DocType Controller for Verenigingen Association Management
 *
 * This controller manages the import and processing of member data from CSV files,
 * providing comprehensive member import capabilities with validation and preview.
 *
 * @description Business Context:
 * Mijnrood CSV Import enables bulk import of member data from standardized CSV files:
 * - Automated member data import from CSV files
 * - Field mapping and validation
 * - Preview functionality before import
 * - Error detection and reporting
 * - Test mode for safe validation
 * - Integration with Member management
 *
 * @description Key Features:
 * - CSV file format parsing and validation
 * - Dutch field header mapping support
 * - Member record creation with proper field mapping
 * - Address creation and linking
 * - Payment method configuration
 * - Mollie subscription data import
 * - Test mode for validation without creating records
 *
 * @author Verenigingen Development Team
 * @version 2025-08-14
 * @since 1.0.0
 */

// Copyright (c) 2025, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on('Mijnrood CSV Import', {
	refresh(frm) {
		// Add custom buttons based on status
		if (frm.doc.docstatus === 0) {
			// Add validation button (only if not already validating or processing)
			if (frm.doc.csv_file && frm.doc.name && !['Validating', 'In Progress'].includes(frm.doc.import_status)) {
				frm.add_custom_button(__('Validate CSV'), () => {
					// Prevent multiple clicks
					frm.set_value('import_status', 'Validating');
					frappe.show_alert(__('Validating file...'));
					frappe.call({
						method: 'verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.validate_import_file',
						args: {
							import_doc_name: frm.doc.name
						},
						callback(r) {
							if (r.message && r.message.status === 'success') {
								frappe.show_alert({
									message: r.message.message,
									indicator: 'green'
								});
								frm.reload_doc();
							} else {
								frappe.msgprint({
									title: __('Validation Failed'),
									message: r.message.message || 'Unknown error occurred',
									indicator: 'red'
								});
								frm.reload_doc();
							}
						},
						error(r) {
							frappe.msgprint({
								title: __('Error'),
								message: __('Failed to validate file. Please try again.'),
								indicator: 'red'
							});
						}
					});
				});
			}

			// Add process import button if ready
			if (frm.doc.import_status === 'Ready for Import') {
				frm.add_custom_button(__('Process Import'), () => {
					if (frm.doc.test_mode) {
						frappe.confirm(
							__('Test mode is enabled. This will validate the import without creating records. Continue?'),
							() => {
								frm.save('Submit');
							}
						);
					} else {
						frappe.confirm(
							__('This will create/update member records. Are you sure you want to proceed?'),
							() => {
								frm.save('Submit');
							}
						);
					}
				}).addClass('btn-primary');

				// Add toggle test mode button
				frm.add_custom_button(__('Toggle Test Mode'), () => {
					frm.set_value('test_mode', !frm.doc.test_mode);
				});
			}

			// Add download template button
			frm.add_custom_button(__('Download Template'), () => {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.get_import_template',
					callback(r) {
						if (r.message) {
							// Create downloadable file
							const blob = new Blob([r.message.content], { type: 'text/csv' });
							const url = window.URL.createObjectURL(blob);
							const a = document.createElement('a');
							a.href = url;
							a.download = r.message.filename;
							document.body.appendChild(a);
							a.click();
							window.URL.revokeObjectURL(url);
							document.body.removeChild(a);
						}
					}
				});
			});
		}

		// Show results if completed
		if (frm.doc.import_status === 'Completed') {
			frm.add_custom_button(__('View Created Members'), () => {
				// Filter members created around this import date
				const filters = {
					creation: ['>', frappe.datetime.add_days(frm.doc.import_date, -1)]
				};

				frappe.set_route('List', 'Member', filters);
			});
		}

		// Set help text and warnings based on status
		if (!frm.doc.csv_file) {
			frm.set_intro(__('1. Upload a CSV or Excel file with member data to begin.'), 'blue');
		} else if (!frm.doc.import_status || frm.doc.import_status === 'Pending') {
			// Show file name to confirm selection
			const fileName = frm.doc.csv_file.split('/').pop() || frm.doc.csv_file;
			frm.set_intro(__('File selected: {0}. Click "Validate CSV" to process and validate the file.', [fileName]), 'orange');
		} else if (frm.doc.import_status === 'Validating') {
			frm.set_intro(__('Processing file... Please wait.'), 'blue');
		} else if (frm.doc.import_status === 'Failed') {
			frm.set_intro(__('Validation failed. Check the Error Log below for details.'), 'red');
		} else if (frm.doc.import_status === 'Ready for Import') {
			if (frm.doc.test_mode) {
				frm.set_intro(__('Ready to import in test mode (no records will be created). Review preview data below.'), 'green');
			} else {
				frm.set_intro(__('Ready to import! This will create actual member records. Review preview data below.'), 'orange');
			}
		} else if (frm.doc.import_status === 'Completed') {
			frm.set_intro(__('Import completed successfully!'), 'green');
		}

		// Auto-refresh status for long-running imports
		if (frm.doc.import_status === 'In Progress') {
			setTimeout(() => {
				frm.reload_doc();
			}, 5000);
		}
	},

	csv_file(frm) {
		// Handle file selection (both upload and library selection)
		if (frm.doc.csv_file) {
			// Reset import status when file changes
			frm.set_value('import_status', 'Pending');

			// Show file name in the field label for better UX
			const fileName = frm.doc.csv_file.split('/').pop() || frm.doc.csv_file;
			frm.set_df_property('csv_file', 'description', __('Selected file: {0}', [fileName]));

			// Update intro to show next step
			frm.set_intro(__('File selected. Click "Validate CSV" to process the file.'), 'blue');

			// Refresh form to update button states
			setTimeout(() => {
				frm.refresh();
			}, 100);
		} else {
			// Clear status if file is removed
			frm.set_value('import_status', '');
			frm.set_df_property('csv_file', 'description', '');
			frm.set_intro(__('Please upload or select a CSV file to begin.'), 'blue');
		}
	},

	test_mode(frm) {
		// Update intro when test mode changes
		if (frm.doc.test_mode) {
			frm.set_intro(__('Test mode enabled. Import will validate data without creating records.'), 'blue');
		} else if (frm.doc.import_status === 'Ready for Import') {
			frm.set_intro(__('Test mode disabled. Import will create actual member records.'), 'orange');
		}
	},

	import_status(frm) {
		// Update form state based on status
		if (frm.doc.import_status === 'Failed') {
			frm.set_intro(__('Import validation failed. Check the error log for details.'), 'red');
		} else if (frm.doc.import_status === 'Ready for Import') {
			frm.set_intro(__('Ready to import. Review preview data below.'), 'green');
		} else if (frm.doc.import_status === 'Completed') {
			frm.set_intro(__('Import completed successfully!'), 'green');
		}
	}
});

// Add custom CSS for better preview display
frappe.ui.form.on('Mijnrood CSV Import', {
	onload(_frm) {
		// Add custom CSS for preview formatting
		if (!document.querySelector('#member-import-styles')) {
			const style = document.createElement('style');
			style.id = 'member-import-styles';
			style.textContent = `
                .member-csv-preview {
                    max-height: 400px;
                    overflow-y: auto;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    padding: 10px;
                    background-color: #f9f9f9;
                }
                .member-csv-preview pre {
                    margin: 0;
                    white-space: pre-wrap;
                    font-size: 12px;
                }
                .import-status-pending { color: #ffa500; }
                .import-status-ready { color: #28a745; }
                .import-status-failed { color: #dc3545; }
                .import-status-completed { color: #28a745; }
            `;
			document.head.appendChild(style);
		}
	}
});
