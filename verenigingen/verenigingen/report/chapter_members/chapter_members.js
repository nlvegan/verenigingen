frappe.query_reports['Chapter Members'] = {
	'filters': [
		{
			'fieldname': 'chapter',
			'label': __('Chapter'),
			'fieldtype': 'Link',
			'options': 'Chapter',
			'reqd': 1,
			'get_query': function() {
				// Only show chapters that user has access to
				return {
					'query': 'verenigingen.api.member_portal.get_user_chapters'
				};
			}
		},
		{
			'fieldname': 'status',
			'label': __('Status'),
			'fieldtype': 'Select',
			'options': [
				'',
				'Pending',
				'Active',
				'Inactive'
			],
			'default': ''
		}
	],

	'formatter': function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Highlight pending members
		if (column.fieldname == 'status' && value == 'Pending') {
			value = `<span style="color: #ff9800; font-weight: bold;">${value}</span>`;
		}
		// Highlight inactive members
		else if (column.fieldname == 'status' && value == 'Inactive') {
			value = `<span style="color: #f44336; font-weight: bold;">${value}</span>`;
		}
		// Active members in green
		else if (column.fieldname == 'status' && value == 'Active') {
			value = `<span style="color: #4caf50; font-weight: bold;">${value}</span>`;
		}

		return value;
	}
};
