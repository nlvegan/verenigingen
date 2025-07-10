// Report configuration for Overdue Member Payments
frappe.query_reports['Overdue Member Payments'] = {
	'filters': [
		{
			'fieldname': 'chapter',
			'label': __('Chapter'),
			'fieldtype': 'Link',
			'options': 'Chapter'
		},
		{
			'fieldname': 'from_date',
			'label': __('From Date'),
			'fieldtype': 'Date',
			'default': frappe.datetime.add_months(frappe.datetime.get_today(), -3)
		},
		{
			'fieldname': 'to_date',
			'label': __('To Date'),
			'fieldtype': 'Date',
			'default': frappe.datetime.get_today()
		},
		{
			'fieldname': 'membership_type',
			'label': __('Membership Type'),
			'fieldtype': 'Link',
			'options': 'Membership Type'
		},
		{
			'fieldname': 'days_overdue',
			'label': __('Minimum Days Overdue'),
			'fieldtype': 'Int',
			'description': __('Show only payments overdue for at least X days')
		},
		{
			'fieldname': 'critical_only',
			'label': __('Critical Only (>60 days)'),
			'fieldtype': 'Check',
			'default': 0
		},
		{
			'fieldname': 'urgent_only',
			'label': __('Urgent Only (>30 days)'),
			'fieldtype': 'Check',
			'default': 0
		}
	],

	'formatter': function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname == 'days_overdue') {
			if (value > 60) {
				value = `<span style="color: red; font-weight: bold">${value}</span>`;
			} else if (value > 30) {
				value = `<span style="color: orange; font-weight: bold">${value}</span>`;
			} else if (value > 14) {
				value = `<span style="color: #ff9500">${value}</span>`;
			}
		}

		if (column.fieldname == 'total_overdue') {
			if (value > 100) {
				value = `<span style="color: red; font-weight: bold">${value}</span>`;
			} else if (value > 50) {
				value = `<span style="color: orange">${value}</span>`;
			}
		}

		if (column.fieldname == 'overdue_count') {
			if (value > 3) {
				value = `<span style="color: red; font-weight: bold">${value}</span>`;
			} else if (value > 1) {
				value = `<span style="color: orange">${value}</span>`;
			}
		}

		return value;
	},

	onload: function(report) {
		// Check for URL parameters to auto-set filters
		const urlParams = new URLSearchParams(window.location.search);
		const preset = urlParams.get('preset');

		if (preset === 'critical') {
			report.set_filter_value('critical_only', 1);
			report.refresh();
		} else if (preset === 'urgent') {
			report.set_filter_value('urgent_only', 1);
			report.refresh();
		} else if (preset === 'days' && urlParams.get('days')) {
			const days = parseInt(urlParams.get('days'));
			if (days > 0) {
				report.set_filter_value('days_overdue', days);
				report.refresh();
			}
		}

		// Add role-based chapter filter for non-admin users
		frappe.call({
			method: 'verenigingen.api.membership_application_review.get_user_chapter_access',
			callback: function(r) {
				if (r.message && r.message.restrict_to_chapters && r.message.chapters.length === 1) {
					// Auto-set chapter filter if user only has access to one chapter
					report.set_filter_value('chapter', r.message.chapters[0]);
					report.refresh();
				} else if (r.message && r.message.restrict_to_chapters && r.message.chapters.length > 1) {
					// Add info message about user's chapter access
					const chapter_names = r.message.chapters.join(', ');
					report.page.set_indicator(__('Filtered to your chapters: {0}', [chapter_names]), 'blue');
				}
			}
		});

		// Add custom button to send payment reminders
		report.page.add_inner_button(__('Send Payment Reminders'), function() {
			show_payment_reminder_dialog(report);
		});

		// Add button to create payment entries
		report.page.add_inner_button(__('Record Payments'), function() {
			show_payment_recording_dialog(report);
		});

		// Add button to export for external collection
		report.page.add_inner_button(__('Export for Collection'), function() {
			export_for_collection(report);
		});

		// Add button for bulk actions
		report.page.add_inner_button(__('Bulk Actions'), function() {
			show_bulk_payment_actions_dialog(report);
		});
	}
};

function show_payment_reminder_dialog(report) {
	let data = report.data || [];

	if (data.length === 0) {
		frappe.msgprint(__('No overdue payments to process'));
		return;
	}

	let d = new frappe.ui.Dialog({
		title: __('Send Payment Reminders'),
		fields: [
			{
				fieldname: 'reminder_type',
				label: __('Reminder Type'),
				fieldtype: 'Select',
				options: ['Friendly Reminder', 'Urgent Notice', 'Final Notice'],
				reqd: 1,
				default: 'Friendly Reminder'
			},
			{
				fieldname: 'include_payment_link',
				label: __('Include Payment Link'),
				fieldtype: 'Check',
				default: 1
			},
			{
				fieldname: 'custom_message',
				label: __('Custom Message'),
				fieldtype: 'Text',
				description: __('Additional message to include in the reminder')
			},
			{
				fieldname: 'send_to_chapters',
				label: __('Also Notify Chapters'),
				fieldtype: 'Check',
				default: 0,
				description: __('Send copy to chapter board members')
			}
		],
		primary_action_label: __('Send Reminders'),
		primary_action: function(values) {
			frappe.call({
				method: 'verenigingen.api.payment_processing.send_overdue_payment_reminders',
				args: {
					reminder_type: values.reminder_type,
					include_payment_link: values.include_payment_link,
					custom_message: values.custom_message,
					send_to_chapters: values.send_to_chapters,
					filters: report.get_filter_values()
				},
				callback: function(r) {
					if (r.message) {
						frappe.msgprint(__('Sent {0} payment reminders', [r.message.count]));
					}
				}
			});
			d.hide();
		}
	});

	d.show();
}

function show_payment_recording_dialog(report) {
	let data = report.data || [];

	if (data.length === 0) {
		frappe.msgprint(__('No overdue payments found'));
		return;
	}

	let d = new frappe.ui.Dialog({
		title: __('Record Payments'),
		fields: [
			{
				fieldname: 'payment_method',
				label: __('Payment Method'),
				fieldtype: 'Select',
				options: ['Bank Transfer', 'Cash', 'Credit Card', 'SEPA Direct Debit', 'Other'],
				reqd: 1
			},
			{
				fieldname: 'payment_date',
				label: __('Payment Date'),
				fieldtype: 'Date',
				reqd: 1,
				default: frappe.datetime.get_today()
			},
			{
				fieldname: 'reference_number',
				label: __('Reference Number'),
				fieldtype: 'Data',
				description: __('Bank reference or transaction ID')
			},
			{
				fieldname: 'notes',
				label: __('Notes'),
				fieldtype: 'Text'
			}
		],
		primary_action_label: __('Record Payments'),
		primary_action: function(values) {
			// This would open a detailed payment recording interface
			frappe.msgprint(__('Payment recording interface would open here'));
			d.hide();
		}
	});

	d.show();
}

function export_for_collection(report) {
	let data = report.data || [];

	if (data.length === 0) {
		frappe.msgprint(__('No data to export'));
		return;
	}

	frappe.call({
		method: 'verenigingen.api.payment_processing.export_overdue_payments',
		args: {
			filters: report.get_filter_values(),
			format: 'CSV'
		},
		callback: function(r) {
			if (r.message) {
				// Download the generated file
				window.open(r.message.file_url, '_blank');
				frappe.msgprint(__('Export completed. {0} records exported.', [r.message.count]));
			}
		}
	});
}

function show_bulk_payment_actions_dialog(report) {
	let data = report.data || [];

	if (data.length === 0) {
		frappe.msgprint(__('No overdue payments to process'));
		return;
	}

	let d = new frappe.ui.Dialog({
		title: __('Bulk Payment Actions'),
		fields: [
			{
				fieldname: 'action',
				label: __('Action'),
				fieldtype: 'Select',
				options: [
					'Send Payment Reminders',
					'Suspend Memberships',
					'Create Payment Plan',
					'Mark for Collection Agency',
					'Apply Late Fees'
				],
				reqd: 1
			},
			{
				fieldname: 'apply_to',
				label: __('Apply To'),
				fieldtype: 'Select',
				options: ['All Visible Records', 'Critical Only (>60 days)', 'Urgent Only (>30 days)'],
				reqd: 1,
				default: 'All Visible Records'
			},
			{
				fieldname: 'confirmation',
				label: __('I understand this action will affect multiple members'),
				fieldtype: 'Check',
				reqd: 1
			}
		],
		primary_action_label: __('Execute'),
		primary_action: function(values) {
			if (!values.confirmation) {
				frappe.msgprint(__('Please confirm you understand this action'));
				return;
			}

			frappe.confirm(
				__('Are you sure you want to execute this bulk action?'),
				function() {
					frappe.call({
						method: 'verenigingen.api.payment_processing.execute_bulk_payment_action',
						args: {
							action: values.action,
							apply_to: values.apply_to,
							filters: report.get_filter_values()
						},
						callback: function(r) {
							if (r.message) {
								frappe.msgprint(__('Bulk action completed. {0} records processed.', [r.message.count]));
								report.refresh();
							}
						}
					});
				}
			);
			d.hide();
		}
	});

	d.show();
}
