// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.query_reports['Chapter Dues Split'] = {
	filters: [
		{
			fieldname: 'from_date',
			label: __('From Date'),
			fieldtype: 'Date',
			default: frappe.datetime.get_today(),
			reqd: 1
		},
		{
			fieldname: 'to_date',
			label: __('To Date'),
			fieldtype: 'Date',
			default: frappe.datetime.get_today(),
			reqd: 1
		},
		{
			fieldname: 'chapter',
			label: __('Chapter'),
			fieldtype: 'Link',
			options: 'Chapter'
		},
		{
			fieldname: 'company',
			label: __('Company'),
			fieldtype: 'Link',
			options: 'Company',
			default: frappe.defaults.get_user_default('Company')
		}
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Highlight chapters with custom splits
		if (column.fieldname === 'uses_custom_split' && data && data.uses_custom_split) {
			value = `<span class="indicator-pill orange">${__('Custom')}</span>`;
		}

		return value;
	},

	onload(report) {
		// Add button to open Chapter Dues Split Page
		report.page.add_inner_button(__('Generate Journal Entries'), () => {
			frappe.set_route('Form', 'Chapter Dues Allocation', 'new');
		});

		// Add button to export data
		report.page.add_inner_button(__('Export Split Data'), () => {
			const filters = report.get_values();
			frappe.call({
				method: 'verenigingen.verenigingen.report.chapter_dues_split.chapter_dues_split.get_data',
				args: {
					filters
				},
				callback(r) {
					if (r.message) {
						frappe.tools.downloadify(r.message, null, 'Chapter Dues Split');
					}
				}
			});
		});
	}
};
