// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('Chapter Join Request', {
	refresh(frm) {
		// Set up the form view
		frm.set_df_property('member', 'read_only', !frm.is_new());
		frm.set_df_property('chapter', 'read_only', !frm.is_new());

		// Add quick navigation buttons
		if (!frm.is_new()) {
			if (frm.doc.member) {
				frm.add_custom_button(__('View Member'), () => {
					frappe.set_route('Form', 'Member', frm.doc.member);
				}, __('View'));
			}

			if (frm.doc.chapter) {
				frm.add_custom_button(__('View Chapter'), () => {
					frappe.set_route('Form', 'Chapter', frm.doc.chapter);
				}, __('View'));
			}
		}

		// Add action buttons for pending requests
		if (frm.doc.docstatus === 1 && frm.doc.status === 'Pending') {
			// Check if user has permission to approve/reject
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request.has_chapter_approval_permission',
				args: {
					chapter_name: frm.doc.chapter
				},
				callback(r) {
					if (r.message) {
						// Add Approve button
						frm.add_custom_button(__('Approve'), () => {
							frappe.prompt({
								label: __('Approval Notes'),
								fieldname: 'notes',
								fieldtype: 'Small Text',
								reqd: false,
								description: __('Optional notes about this approval')
							}, (values) => {
								frappe.call({
									method: 'verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request.approve_join_request',
									args: {
										request_name: frm.doc.name,
										notes: values.notes
									},
									callback(response) {
										if (response.message && response.message.success) {
											frappe.msgprint(__('Chapter join request approved successfully'));
											frm.reload_doc();
										} else {
											frappe.msgprint(__('Failed to approve request: ') + (response.message?.error || 'Unknown error'));
										}
									}
								});
							}, __('Approve Chapter Join Request'), __('Approve'));
						}, __('Actions')).addClass('btn-success');

						// Add Reject button
						frm.add_custom_button(__('Reject'), () => {
							frappe.prompt({
								label: __('Rejection Reason'),
								fieldname: 'reason',
								fieldtype: 'Small Text',
								reqd: true,
								description: __('Please provide a reason for rejecting this request')
							}, (values) => {
								frappe.call({
									method: 'verenigingen.verenigingen.doctype.chapter_join_request.chapter_join_request.reject_join_request',
									args: {
										request_name: frm.doc.name,
										reason: values.reason
									},
									callback(response) {
										if (response.message && response.message.success) {
											frappe.msgprint(__('Chapter join request rejected'));
											frm.reload_doc();
										} else {
											frappe.msgprint(__('Failed to reject request: ') + (response.message?.error || 'Unknown error'));
										}
									}
								});
							}, __('Reject Chapter Join Request'), __('Reject'));
						}, __('Actions')).addClass('btn-danger');
					}
				}
			});
		}

		// Add visual status indicator at the top of the form
		if (frm.doc.status !== 'Pending' && frm.doc.reviewed_by) {
			// Create a custom HTML section at the top of the form
			const alert_class = frm.doc.status === 'Approved' ? 'alert-success' : 'alert-danger';
			const icon_class = frm.doc.status === 'Approved' ? 'fa-check-circle' : 'fa-times-circle';

			const review_banner = `
				<div class="alert ${alert_class}" style="margin-bottom: 20px;">
					<h4><i class="fa ${icon_class}"></i> ${__(frm.doc.status)}</h4>
					<hr>
					<p><strong>${__('Reviewed By')}:</strong> ${frm.doc.reviewed_by}</p>
					<p><strong>${__('Review Date')}:</strong> ${frappe.datetime.str_to_user(frm.doc.review_date)}</p>
					${frm.doc.review_notes ? `<p><strong>${__('Notes')}:</strong> ${frappe.utils.escape_html(frm.doc.review_notes)}</p>` : ''}
					${frm.doc.rejection_reason ? `<p><strong>${__('Rejection Reason')}:</strong> ${frappe.utils.escape_html(frm.doc.rejection_reason)}</p>` : ''}
				</div>
			`;

			// Add the banner to the page
			if (!frm.review_banner_added) {
				$(frm.fields_dict['request_details_section'].wrapper).before(review_banner);
				frm.review_banner_added = true;
			}
		}
	},

	before_save(frm) {
		// Ensure status is set for new requests
		if (frm.is_new() && !frm.doc.status) {
			frm.doc.status = 'Pending';
		}
	}
});
