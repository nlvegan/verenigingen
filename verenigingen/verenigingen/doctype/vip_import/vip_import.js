/**
 * @fileoverview VIP Import DocType Controller for Verenigingen Association Management
 *
 * This controller manages the import of volunteer data from VIP (Volunteer Information Portal)
 * CSV exports, creating/updating Volunteer records linked to existing Members.
 *
 * @description Business Context:
 * VIP Import enables bulk import of volunteer data from VIP exports:
 * - Automated volunteer data import from CSV files
 * - Member matching by ID or email
 * - Volunteer record creation/update
 * - Status mapping from VIP to Volunteer statuses
 * - External ID storage for future API bridging
 *
 * @author Verenigingen Development Team
 * @version 2025-12-07
 */

frappe.ui.form.on('VIP Import', {
	refresh(frm) {
		// Set intro message based on status
		frm.set_intro('');
		set_status_message(frm);

		// Add custom buttons based on status
		if (frm.doc.docstatus === 0) {
			// Add validation button
			if (
				frm.doc.csv_file &&
				frm.doc.name &&
				!['Validating', 'In Progress', 'Queued'].includes(frm.doc.import_status)
			) {
				frm.add_custom_button(__('Validate CSV'), () => {
					validate_csv(frm);
				});
			}

			// Add process import button if ready
			if (frm.doc.import_status === 'Ready for Import') {
				frm.add_custom_button(
					__('Process Import'),
					() => {
						process_import(frm);
					},
					__('Actions')
				).addClass('btn-primary');
			}

			// Add download template button
			frm.add_custom_button(
				__('Download Template'),
				() => {
					download_template();
				},
				__('Actions')
			);
		}

		// Auto-refresh during processing
		if (['In Progress', 'Queued'].includes(frm.doc.import_status)) {
			setTimeout(() => {
				frm.reload_doc();
			}, 5000);
		}

		// Show preview data if available
		if (frm.doc.preview_data) {
			render_preview(frm);
		}

		// Show results if completed
		if (frm.doc.import_status === 'Completed') {
			show_completion_message(frm);
		}
	},

	csv_file(frm) {
		// Reset status when file changes
		if (frm.doc.csv_file && frm.doc.import_status !== 'Pending') {
			frm.set_value('import_status', 'Pending');
			frm.set_value('preview_data', '');
			frm.save();
		}
	}
});

/**
 * Set status message based on import status
 */
function set_status_message(frm) {
	const status = frm.doc.import_status;

	if (!status || status === 'Pending') {
		if (!frm.doc.csv_file) {
			frm.set_intro(__('Please upload a VIP export CSV file to begin.'), 'blue');
		} else {
			frm.set_intro(__('File uploaded. Click "Validate CSV" to check the data.'), 'blue');
		}
	} else if (status === 'Validating') {
		frm.set_intro(__('Validating CSV file...'), 'blue');
	} else if (status === 'Ready for Import') {
		frm.set_intro(
			__('Validation successful! Review the preview below and click "Process Import" when ready.'),
			'orange'
		);
	} else if (status === 'Queued') {
		frm.set_intro(__('Import is queued and will start shortly...'), 'blue');
	} else if (status === 'In Progress') {
		const progress = frm.doc.progress_percentage || 0;
		frm.set_intro(
			__('Import in progress: {0}% complete ({1} of {2} rows processed)', [
				progress.toFixed(1),
				frm.doc.rows_processed || 0,
				frm.doc.total_rows || 0
			]),
			'blue'
		);
	} else if (status === 'Completed') {
		frm.set_intro(__('Import completed successfully!'), 'green');
	} else if (status === 'Failed') {
		frm.set_intro(__('Import failed. Check the error log below for details.'), 'red');
	}
}

/**
 * Validate the CSV file
 */
function validate_csv(frm) {
	frm.set_value('import_status', 'Validating');
	frappe.show_alert(__('Validating file...'));

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.vip_import.vip_import.validate_import_file',
		args: {
			import_doc_name: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: __('Validation successful! {0} valid rows found.', [r.message.preview.valid_rows]),
					indicator: 'green'
				});
				frm.reload_doc();
			} else {
				frappe.msgprint({
					title: __('Validation Failed'),
					message: r.message.error || __('Unknown error occurred'),
					indicator: 'red'
				});
				frm.reload_doc();
			}
		},
		error() {
			frappe.msgprint({
				title: __('Error'),
				message: __('Failed to validate file. Please try again.'),
				indicator: 'red'
			});
			frm.reload_doc();
		}
	});
}

/**
 * Process the import (submit the document)
 */
function process_import(frm) {
	const message = frm.doc.test_mode
		? __('Test mode is enabled. This will only process the first 25 rows. Continue?')
		: __('This will create/update volunteer records. Are you sure you want to proceed?');

	frappe.confirm(message, () => {
		frm.save('Submit');
	});
}

/**
 * Download the CSV template
 */
function download_template() {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.vip_import.vip_import.get_import_template',
		callback(r) {
			if (r.message) {
				const blob = new Blob([r.message], { type: 'text/csv' });
				const url = window.URL.createObjectURL(blob);
				const a = document.createElement('a');
				a.href = url;
				a.download = 'vip_import_template.csv';
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				window.URL.revokeObjectURL(url);
			}
		}
	});
}

/**
 * Render preview data
 */
function render_preview(frm) {
	if (!frm.doc.preview_data) {
		return;
	}

	try {
		const preview = JSON.parse(frm.doc.preview_data);

		let html = `
			<div class="vip-import-preview" style="margin-top: 15px;">
				<h5>${__('Import Preview')}</h5>
				<div class="row">
					<div class="col-md-3">
						<div class="stat-box">
							<div class="stat-value">${preview.total_rows}</div>
							<div class="stat-label">${__('Total Rows')}</div>
						</div>
					</div>
					<div class="col-md-3">
						<div class="stat-box text-success">
							<div class="stat-value">${preview.valid_rows}</div>
							<div class="stat-label">${__('Valid Rows')}</div>
						</div>
					</div>
					<div class="col-md-3">
						<div class="stat-box text-danger">
							<div class="stat-value">${preview.error_rows}</div>
							<div class="stat-label">${__('Error Rows')}</div>
						</div>
					</div>
					<div class="col-md-3">
						<div class="stat-box text-muted">
							<div class="stat-value">${preview.skipped_rows}</div>
							<div class="stat-label">${__('Skipped Rows')}</div>
						</div>
					</div>
				</div>
		`;

		// Status breakdown
		if (preview.status_breakdown && Object.keys(preview.status_breakdown).length > 0) {
			html += `
				<div style="margin-top: 15px;">
					<h6>${__('Status Breakdown')}</h6>
					<ul class="list-unstyled">
			`;
			for (const [status, count] of Object.entries(preview.status_breakdown)) {
				// Escape status to prevent XSS
				html += `<li><strong>${frappe.utils.escape_html(status)}:</strong> ${frappe.utils.escape_html(String(count))}</li>`;
			}
			html += '</ul></div>';
		}

		// Identifier coverage
		html += `
			<div style="margin-top: 15px;">
				<h6>${__('Identifier Coverage')}</h6>
				<ul class="list-unstyled">
					<li><strong>${__('With Member ID')}:</strong> ${preview.with_member_id}</li>
					<li><strong>${__('With Organization Email')}:</strong> ${preview.with_organization_email}</li>
					<li><strong>${__('With Personal Email')}:</strong> ${preview.with_personal_email}</li>
				</ul>
			</div>
		`;

		// Sample errors
		if (preview.sample_errors && preview.sample_errors.length > 0) {
			html += `
				<div style="margin-top: 15px;">
					<h6 class="text-danger">${__('Sample Errors')}</h6>
					<ul class="list-unstyled text-danger">
			`;
			for (const error of preview.sample_errors) {
				html += `<li><small>${frappe.utils.escape_html(error)}</small></li>`;
			}
			html += '</ul></div>';
		}

		html += '</div>';

		// Add styles
		html += `
			<style>
				.vip-import-preview .stat-box {
					text-align: center;
					padding: 15px;
					background: var(--fg-color);
					border-radius: 8px;
					margin-bottom: 10px;
				}
				.vip-import-preview .stat-value {
					font-size: 24px;
					font-weight: bold;
				}
				.vip-import-preview .stat-label {
					font-size: 12px;
					color: var(--text-muted);
				}
			</style>
		`;

		// Find the preview section and render
		const $preview_section = frm.fields_dict.preview_data.$wrapper.parent();
		$preview_section.find('.vip-import-preview').remove();
		$preview_section.prepend(html);
	} catch (e) {
		console.error('Error rendering preview:', e);
	}
}

/**
 * Show completion message with results
 */
function show_completion_message(frm) {
	const created = frm.doc.volunteers_created || 0;
	const updated = frm.doc.volunteers_updated || 0;
	const skipped = frm.doc.volunteers_skipped || 0;
	const not_found = frm.doc.members_not_found || 0;
	const members_created = frm.doc.members_created || 0;

	let message = `
		<div class="alert alert-success">
			<h5>${__('Import Complete')}</h5>
			<ul class="list-unstyled mb-0">
				<li><strong>${__('Volunteers Created')}:</strong> ${created}</li>
				<li><strong>${__('Volunteers Updated')}:</strong> ${updated}</li>
				<li><strong>${__('Volunteers Skipped')}:</strong> ${skipped}</li>
	`;

	if (members_created > 0) {
		message += `<li><strong>${__('Members Created')}:</strong> ${members_created}</li>`;
	}

	if (not_found > 0) {
		message += `<li class="text-warning"><strong>${__('Members Not Found')}:</strong> ${not_found}</li>`;
	}

	message += '</ul></div>';

	// Actually surface the completion summary to the user (it was built but
	// never displayed, so the import-result counts were silently discarded).
	frappe.msgprint({
		title: __('Import Complete'),
		message,
		indicator: 'green'
	});

	// Add view volunteers button
	if (created > 0 || updated > 0) {
		frm.add_custom_button(__('View Volunteers'), () => {
			frappe.set_route('List', 'Volunteer');
		});
	}
}
