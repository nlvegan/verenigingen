// Copyright (c) 2025, R.S.P. and contributors
// For license information, please see license.txt

frappe.ui.form.on('MT940 Import', {
	refresh: function(frm) {
		// Add custom buttons
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Process Import'), function() {
				// Submit the document to trigger import
				frm.submit();
			}).addClass('btn-primary');

			frm.add_custom_button(__('Test/Debug'), function() {
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
					callback: function(r) {
						if (r.message) {
							let html = '<div class="debug-results">';
							html += '<h4>Debug Results</h4>';
							html += '<pre>' + JSON.stringify(r.message, null, 2) + '</pre>';
							html += '</div>';

							let dialog = new frappe.ui.Dialog({
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

			frm.add_custom_button(__('Debug Duplicates'), function() {
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
					callback: function(r) {
						if (r.message) {
							let html = '<div class="duplicate-debug-results">';
							html += '<h4>Duplicate Detection Analysis</h4>';
							html += '<pre>' + JSON.stringify(r.message, null, 2) + '</pre>';
							html += '</div>';

							let dialog = new frappe.ui.Dialog({
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
			frm.add_custom_button(__('View Bank Transactions'), function() {
				// Use statement date range if available, otherwise fall back to creation date
				let filters = {
					'bank_account': frm.doc.bank_account
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

	bank_account: function(frm) {
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
