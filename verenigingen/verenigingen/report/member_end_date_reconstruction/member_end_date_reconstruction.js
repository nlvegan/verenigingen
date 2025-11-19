// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports['Member End Date Reconstruction'] = {
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Color code confidence levels
		if (column.fieldname === 'confidence') {
			if (data.confidence === 'High') {
				value = `<span style="color: green; font-weight: bold;">${data.confidence}</span>`;
			} else if (data.confidence === 'Medium') {
				value = `<span style="color: orange;">${data.confidence}</span>`;
			} else if (data.confidence === 'Low' || data.confidence === 'No Data') {
				value = `<span style="color: red;">${data.confidence}</span>`;
			}
		}

		// Highlight status indicators
		if (column.fieldname === 'status_indicator') {
			if (data.status_indicator.includes('Still Active')) {
				value = `<span style="color: orange; font-weight: bold;">${data.status_indicator}</span>`;
			} else if (data.status_indicator.includes('✓')) {
				value = `<span style="color: green;">${data.status_indicator}</span>`;
			}
		}

		return value;
	},

	onload(report) {
		// Add "Apply All High Confidence" button
		report.page.add_inner_button(__('Apply All High Confidence'), () => {
			frappe.confirm(
				__('This will update all terminated members with high-confidence suggested end dates. Continue?'),
				() => {
					frappe.call({
						method: 'verenigingen.verenigingen.report.member_end_date_reconstruction.member_end_date_reconstruction.apply_all_suggestions',
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __(`Updated ${r.message.updated} members`),
									indicator: 'green'
								});
								report.refresh();
							}
						}
					});
				}
			);
		});
	}
};
