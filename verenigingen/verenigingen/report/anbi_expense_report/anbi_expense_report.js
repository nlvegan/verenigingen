// Copyright (c) 2025, NVV and contributors
// For license information, please see license.txt

frappe.query_reports["ANBI Expense Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: frappe.defaults.get_user_default("fiscal_year"),
			reqd: 1,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Bold the total row
		if (data && data.is_total) {
			value = "<b>" + value + "</b>";
		}

		// Color code the percentage column
		if (column.fieldname === "percentage" && data && !data.is_total) {
			if (data.account_number === "61") {
				// Doelstelling - green if >= 70%
				if (data.percentage >= 70) {
					value =
						'<span style="color: green; font-weight: bold;">' +
						value +
						"</span>";
				}
			} else if (data.account_number === "63") {
				// Beheer - orange warning if > 15%
				if (data.percentage > 15) {
					value =
						'<span style="color: orange; font-weight: bold;">' +
						value +
						"</span>";
				}
			}
		}

		return value;
	},
};
