// Copyright (c) 2025, Verenigingen and contributors
// License: GNU General Public License v3

frappe.query_reports['Volunteer Activity by Tag'] = {
	filters: [
		{
			fieldname: 'tag',
			label: __('Tag'),
			fieldtype: 'Link',
			options: 'Activity Tag',
			reqd: 0
		},
		{
			fieldname: 'chapter',
			label: __('Chapter'),
			fieldtype: 'Link',
			options: 'Chapter',
			reqd: 0
		},
		{
			fieldname: 'activity_type',
			label: __('Activity Type'),
			fieldtype: 'Select',
			options: '\nProject\nEvent\nWorkshop\nTraining\nCampaign\nExternal Board Position\nCouncil/Government Intervention\nExternal Campaign Support\nCommunity Organizing\nMedia/Advocacy\nCoalition Work\nPublic Speaking\nOther',
			reqd: 0
		},
		{
			fieldname: 'activity_scope',
			label: __('Activity Scope'),
			fieldtype: 'Select',
			options: '\nInternal\nExternal\nCollaborative',
			reqd: 0
		},
		{
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: '\nActive\nCompleted\nCancelled\nOn Hold',
			reqd: 0,
			default: ''
		},
		{
			fieldname: 'from_date',
			label: __('From Date'),
			fieldtype: 'Date',
			reqd: 0
		},
		{
			fieldname: 'to_date',
			label: __('To Date'),
			fieldtype: 'Date',
			reqd: 0
		}
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Highlight different activity scopes with colors
		if (column.fieldname === 'activity_scope' && data) {
			if (data.activity_scope === 'External') {
				value = `<span style="color: #5e64ff; font-weight: 500;">${data.activity_scope}</span>`;
			} else if (data.activity_scope === 'Collaborative') {
				value = `<span style="color: #ff6b6b; font-weight: 500;">${data.activity_scope}</span>`;
			} else if (data.activity_scope === 'Internal') {
				value = `<span style="color: #51cf66;">${data.activity_scope}</span>`;
			}
		}

		// Color-code status
		if (column.fieldname === 'status' && data) {
			const status_colors = {
				Active: '#51cf66',
				Completed: '#868e96',
				Cancelled: '#ff6b6b',
				'On Hold': '#ffd43b'
			};
			const color = status_colors[data.status] || '#868e96';
			value = `<span style="color: ${color}; font-weight: 500;">${data.status}</span>`;
		}

		return value;
	}
};
