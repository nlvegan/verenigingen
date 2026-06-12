// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports['Members Without Payment Info'] = {
	filters: [
		{
			fieldname: 'chapter',
			label: __('Chapter'),
			fieldtype: 'Link',
			options: 'Chapter',
			reqd: 0
		}
	]
};
