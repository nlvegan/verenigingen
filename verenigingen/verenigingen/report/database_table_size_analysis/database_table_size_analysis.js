// Copyright (c) 2025, Molekuul and contributors
// For license information, please see license.txt

frappe.query_reports["Database Table Size Analysis"] = {
	"filters": [
		{
			"fieldname": "table_type",
			"label": __("Table Type"),
			"fieldtype": "Select",
			"options": ["", "DocType", "Child Table", "System", "Other"],
			"default": ""
		},
		{
			"fieldname": "min_size_mb",
			"label": __("Minimum Size (MB)"),
			"fieldtype": "Float",
			"default": 0
		},
		{
			"fieldname": "doctype_filter",
			"label": __("DocType Filter"),
			"fieldtype": "Data",
			"description": __("Filter by DocType name (case-insensitive)")
		}
	],

	"formatter": function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Color code the percentage column
		if (column.fieldname == "percentage") {
			if (data.percentage > 10) {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else if (data.percentage > 5) {
				value = `<span style="color: orange; font-weight: bold;">${value}</span>`;
			} else if (data.percentage > 1) {
				value = `<span style="color: #4C9AFF;">${value}</span>`;
			}
		}

		// Color code total size
		if (column.fieldname == "total_size_mb") {
			if (data.total_size_mb > 100) {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else if (data.total_size_mb > 50) {
				value = `<span style="color: orange; font-weight: bold;">${value}</span>`;
			} else if (data.total_size_mb > 10) {
				value = `<span style="color: #4C9AFF;">${value}</span>`;
			}
		}

		// Add visual bar for percentage
		if (column.fieldname == "table_name" && data.percentage) {
			const barWidth = Math.min(data.percentage * 2, 100);
			const barColor = data.percentage > 10 ? '#ff4757' :
			                 data.percentage > 5 ? '#ffa502' :
			                 '#4C9AFF';

			value = `
				<div style="position: relative;">
					<div style="
						position: absolute;
						left: 0;
						top: 0;
						bottom: 0;
						width: ${barWidth}%;
						background-color: ${barColor};
						opacity: 0.15;
						z-index: 0;
					"></div>
					<div style="position: relative; z-index: 1; padding: 2px 0;">
						${data.table_name}
					</div>
				</div>
			`;
		}

		return value;
	},

	onload: function(report) {
		// Add custom buttons
		report.page.add_inner_button(__('Optimize Tables'), function() {
			frappe.confirm(
				__('This will run OPTIMIZE TABLE on all tables. This may take several minutes. Continue?'),
				function() {
					frappe.call({
						method: 'verenigingen.verenigingen.report.database_table_size_analysis.database_table_size_analysis.optimize_all_tables',
						callback: function(r) {
							if (r.message) {
								frappe.msgprint({
									title: __('Optimization Complete'),
									message: __('Optimized {0} tables', [r.message.optimized_count]),
									indicator: 'green'
								});
								report.refresh();
							}
						}
					});
				}
			);
		}, __('Actions'));

		report.page.add_inner_button(__('Analyze Tables'), function() {
			frappe.call({
				method: 'verenigingen.verenigingen.report.database_table_size_analysis.database_table_size_analysis.analyze_all_tables',
				callback: function(r) {
					if (r.message) {
						frappe.msgprint({
							title: __('Analysis Complete'),
							message: __('Analyzed {0} tables', [r.message.analyzed_count]),
							indicator: 'green'
						});
						report.refresh();
					}
				}
			});
		}, __('Actions'));

		report.page.add_inner_button(__('Export to CSV'), function() {
			report.export_report();
		}, __('Actions'));
	}
};
