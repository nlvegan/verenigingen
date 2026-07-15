// Copyright (c) 2026, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('Member Import', {
	refresh(frm) {
		frm.clear_custom_buttons();

		// Validate CSV button
		if (
			frm.doc.docstatus === 0 &&
			frm.doc.csv_file &&
			!['Validating', 'In Progress', 'Queued'].includes(frm.doc.import_status)
		) {
			frm.add_custom_button(__('Validate CSV'), () => {
				frm.call({
					method: 'validate_import_file',
					args: { import_doc_name: frm.doc.name },
					freeze: true,
					freeze_message: __('Validating CSV file...'),
					callback(r) {
						if (r.message) {
							if (r.message.status === 'success') {
								frappe.show_alert({
									message: __('Validation successful'),
									indicator: 'green'
								});
							} else {
								frappe.show_alert({
									message: r.message.message || __('Validation failed'),
									indicator: 'red'
								});
							}
							frm.reload_doc();
						}
					}
				});
			});
		}

		// Process Import button
		if (frm.doc.docstatus === 0 && frm.doc.import_status === 'Ready for Import') {
			frm.add_custom_button(__('Process Import'), () => {
				let msg = __('This will create Member records from the CSV data.');
				if (frm.doc.test_mode) {
					msg += ` ${__('Test mode is ON — only the first 25 rows will be processed.')}`;
				}
				frappe.confirm(msg, () => {
					frm.save('Submit');
				});
			}).addClass('btn-primary');
		}

		// Auto-refresh during processing
		if (['Queued', 'In Progress'].includes(frm.doc.import_status)) {
			setTimeout(() => {
				frm.reload_doc();
			}, 5000);
		}

		// Status intro messages
		if (!frm.doc.csv_file) {
			frm.set_intro(
				__(
					"1. Upload a CSV file exported from Procurios<br>2. Click 'Validate CSV' to check the data<br>3. Review the preview and click 'Process Import'"
				)
			);
		} else if (frm.doc.import_status === 'Pending') {
			frm.set_intro(__("File selected. Click 'Validate CSV' to check the data."));
		} else if (frm.doc.import_status === 'Validating') {
			frm.set_intro(__('Processing file...'), 'blue');
		} else if (frm.doc.import_status === 'Failed') {
			frm.set_intro(__('Validation failed. Check the Error Log below.'), 'red');
		} else if (frm.doc.import_status === 'Ready for Import') {
			let msg = __("Ready to import! Review the preview data below, then click 'Process Import'.");
			if (frm.doc.test_mode) {
				msg += ` ${__('<br><strong>Test mode is ON</strong> — only the first 25 rows will be processed.')}`;
			}
			frm.set_intro(msg, 'green');
		} else if (frm.doc.import_status === 'Completed') {
			frm.set_intro(
				__('Import completed. {0} members created, {1} skipped.', [
					frm.doc.members_created,
					frm.doc.members_skipped
				]),
				'green'
			);
		} else if (['Queued', 'In Progress'].includes(frm.doc.import_status)) {
			frm.set_intro(
				__('Import in progress... {0}% complete ({1}/{2} rows)', [
					frm.doc.progress_percentage || 0,
					frm.doc.rows_processed || 0,
					frm.doc.total_rows || 0
				]),
				'blue'
			);
		}
	},

	csv_file(frm) {
		if (frm.doc.csv_file) {
			frm.set_value('import_status', 'Pending');
			frm.set_intro(__("File selected. Click 'Validate CSV' to check the data."));
		}
	}
});
