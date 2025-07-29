// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports['Members Without Active Memberships'] = {
	'filters': [
		{
			'fieldname': 'include_terminated',
			'label': __('Include Terminated Members'),
			'fieldtype': 'Check',
			'default': 0,
			'description': 'Include members with status \'Terminated\''
		},
		{
			'fieldname': 'include_suspended',
			'label': __('Include Suspended Members'),
			'fieldtype': 'Check',
			'default': 1,
			'description': 'Include members with status \'Suspended\''
		},
		{
			'fieldname': 'member_status',
			'label': __('Member Status'),
			'fieldtype': 'Select',
			'options': 'Active\nPending\nSuspended\nTerminated',
			'description': 'Filter by specific member status'
		},
		{
			'fieldname': 'include_dues_schedule_info',
			'label': __('Include Dues Schedule Information'),
			'fieldtype': 'Check',
			'default': 0,
			'description': 'Add columns showing dues schedule status, next invoice date, and coverage gaps'
		},
		// Chapter filter disabled - field is computed/HTML
		// {
		// 	"fieldname": "chapter",
		// 	"label": __("Chapter"),
		// 	"fieldtype": "Link",
		// 	"options": "Chapter",
		// 	"description": "Filter by specific chapter"
		// }
	],

	'formatter': function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Color code based on member status and last membership status
		if (column.fieldname == 'member_status') {
			if (value == 'Terminated') {
				value = `<span style="color: red;">${value}</span>`;
			} else if (value == 'Suspended') {
				value = `<span style="color: orange;">${value}</span>`;
			} else if (value == 'Pending') {
				value = `<span style="color: blue;">${value}</span>`;
			}
		}

		if (column.fieldname == 'last_membership_status') {
			if (value == 'Cancelled') {
				value = `<span style="color: red;">${value}</span>`;
			} else if (value == 'Expired') {
				value = `<span style="color: orange;">${value}</span>`;
			}
		}

		// Format dues schedule status
		if (column.fieldname == 'dues_schedule_status') {
			if (value == 'None') {
				value = `<span style="color: red;">${value}</span>`;
			} else if (value == 'Active') {
				value = `<span style="color: green;">${value}</span>`;
			}
		}

		// Format days overdue
		if (column.fieldname == 'days_overdue' && value && value > 0) {
			if (value > 7) {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else {
				value = `<span style="color: orange;">${value}</span>`;
			}
		}

		return value;
	}
};
