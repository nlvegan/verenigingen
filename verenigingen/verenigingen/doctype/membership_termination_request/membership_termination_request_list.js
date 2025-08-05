/**
 * @fileoverview Membership Termination Request List View - JavaScript Configuration
 *
 * This file manages the list view behavior for membership termination requests, providing
 * comprehensive workflow management for voluntary departures and disciplinary actions.
 *
 * BUSINESS PURPOSE:
 * Supports member lifecycle management through structured termination processes:
 * - Handle voluntary membership terminations with proper documentation
 * - Manage disciplinary actions including policy violations and expulsions
 * - Provide audit trails for sensitive membership decisions
 * - Support bulk processing for administrative efficiency
 * - Generate compliance reports for organizational governance
 *
 * TERMINATION CATEGORIES:
 * - Voluntary: Member-initiated departures (blue indicator)
 * - Disciplinary: Policy violations, disciplinary actions, expulsions (red indicator)
 * - Administrative: System-initiated or regulatory terminations
 *
 * WORKFLOW STATES:
 * - Draft (Blue): Initial creation, incomplete information
 * - Pending (Yellow): Awaiting review and approval
 * - Approved (Green): Approved for execution
 * - Rejected (Red): Denied termination request
 * - Executed (Gray): Completed termination process
 *
 * ADVANCED FEATURES:
 * - Status-based conditional buttons for workflow progression
 * - Bulk processing capabilities for approved terminations
 * - Expulsion report generation with detailed audit information
 * - Chapter-specific filtering and reporting
 * - Integration with member status management systems
 *
 * ADMINISTRATIVE TOOLS:
 * - Expulsion Report: Comprehensive reporting of disciplinary actions
 * - Bulk Processing: Efficient execution of multiple approved terminations
 * - Status Tracking: Visual indicators for quick status assessment
 * - Audit Trail: Complete history of termination decisions and approvals
 *
 * SECURITY CONSIDERATIONS:
 * - Requires explicit confirmation for bulk processing
 * - Filters only approved items for bulk execution
 * - Maintains detailed approval chain documentation
 * - Supports chapter-based access control and reporting
 *
 * @author Frappe Technologies Pvt. Ltd.
 * @since 2025
 * @category Membership Management
 * @requires frappe.listview_settings
 * @requires verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request
 */

frappe.listview_settings['Membership Termination Request'] = {
	get_indicator(doc) {
		const status_colors = {
			Draft: 'blue',
			Pending: 'yellow',
			Approved: 'green',
			Rejected: 'red',
			Executed: 'gray'
		};

		return [__(doc.status), status_colors[doc.status] || 'gray', `status,=,${doc.status}`];
	},

	onload(listview) {
		// Add custom buttons to list view
		listview.page.add_menu_item(__('Generate Expulsion Report'), () => {
			show_expulsion_report_dialog();
		});

		listview.page.add_menu_item(__('Bulk Process Terminations'), () => {
			show_bulk_process_dialog(listview);
		});
	},

	button: {
		show(doc) {
			return doc.status === 'Pending';
		},
		get_label() {
			return __('Review');
		},
		get_description(doc) {
			return __('Review and approve/reject this termination request');
		},
		action(doc) {
			frappe.set_route('Form', 'Membership Termination Request', doc.name);
		}
	},

	formatters: {
		termination_type(value) {
			const disciplinary_types = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
			if (disciplinary_types.includes(value)) {
				return `<span class="indicator red">${value}</span>`;
			}
			return `<span class="indicator blue">${value}</span>`;
		}
	}
};

function show_expulsion_report_dialog() {
	const dialog = new frappe.ui.Dialog({
		title: __('Generate Expulsion Report'),
		fields: [
			{
				fieldtype: 'DateRange',
				fieldname: 'date_range',
				label: __('Date Range'),
				description: __('Select date range for expulsion report')
			},
			{
				fieldtype: 'Link',
				fieldname: 'chapter',
				label: __('Chapter'),
				options: 'Chapter',
				description: __('Filter by specific chapter (optional)')
			}
		],
		primary_action_label: __('Generate Report'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.generate_expulsion_report',
				args: {
					date_range: values.date_range,
					chapter: values.chapter
				},
				callback(r) {
					if (r.message && r.message.length) {
						show_expulsion_report_results(r.message);
						dialog.hide();
					} else {
						frappe.msgprint(__('No expulsion records found for the selected criteria'));
					}
				}
			});
		}
	});

	dialog.show();
}

function show_expulsion_report_results(data) {
	let html = '<div class="expulsion-report">';
	html += `<h4>${__('Expulsion Report')}</h4>`;
	html += '<table class="table table-bordered table-condensed">';
	html += '<thead><tr>';
	html += `<th>${__('Member')}</th>`;
	html += `<th>${__('Expulsion Date')}</th>`;
	html += `<th>${__('Type')}</th>`;
	html += `<th>${__('Chapter')}</th>`;
	html += `<th>${__('Status')}</th>`;
	html += `<th>${__('Initiated By')}</th>`;
	html += `<th>${__('Approved By')}</th>`;
	html += '</tr></thead><tbody>';

	data.forEach((record) => {
		html += '<tr>';
		html += `<td><a href="/app/member/${record.member_id}">${record.member_name}</a></td>`;
		html += `<td>${frappe.datetime.str_to_user(record.expulsion_date)}</td>`;
		html += `<td><span class="indicator red">${record.expulsion_type}</span></td>`;
		html += `<td>${record.chapter_involved || '-'}</td>`;
		html += `<td>${record.status}</td>`;
		html += `<td>${record.initiated_by}</td>`;
		html += `<td>${record.approved_by}</td>`;
		html += '</tr>';
	});

	html += '</tbody></table></div>';

	const report_dialog = new frappe.ui.Dialog({
		title: __('Expulsion Report Results'),
		size: 'extra-large',
		fields: [
			{
				fieldtype: 'HTML',
				options: html
			}
		],
		primary_action_label: __('Export to Excel'),
		primary_action() {
			// Export functionality would go here
			frappe.msgprint(__('Export functionality to be implemented'));
		}
	});

	report_dialog.show();
}

function show_bulk_process_dialog(listview) {
	// Get selected items
	const selected_items = listview.get_checked_items();

	if (!selected_items.length) {
		frappe.msgprint(__('Please select termination requests to process'));
		return;
	}

	// Filter to only show approved items
	const approved_items = selected_items.filter(item => item.status === 'Approved');

	if (!approved_items.length) {
		frappe.msgprint(__('Please select approved termination requests to process'));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __('Bulk Process Terminations'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `<p><strong>${__('Selected Items:')}</strong> ${approved_items.length}</p>
                         <p>${__('This will execute all selected approved termination requests.')}</p>`
			},
			{
				fieldtype: 'Check',
				fieldname: 'confirm_bulk_process',
				label: __('I confirm that I want to execute these terminations'),
				reqd: 1
			}
		],
		primary_action_label: __('Execute All'),
		primary_action(values) {
			if (!values.confirm_bulk_process) {
				frappe.msgprint(__('Please confirm the bulk process'));
				return;
			}

			// Process each approved item
			let processed = 0;
			const total = approved_items.length;

			approved_items.forEach((item, index) => {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.execute_termination',
					args: {
						request_name: item.name
					},
					callback(r) {
						processed++;
						if (processed === total) {
							// All done
							frappe.show_alert({
								message: __('Processed {0} termination requests', [total]),
								indicator: 'green'
							}, 5);
							listview.refresh();
							dialog.hide();
						}
					}
				});
			});
		}
	});

	dialog.show();
}
