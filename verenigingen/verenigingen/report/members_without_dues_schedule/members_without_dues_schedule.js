// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["Members Without Dues Schedule"] = {
	"filters": [
		{
			"fieldname": "include_terminated",
			"label": __("Include Terminated Members"),
			"fieldtype": "Check",
			"default": 0,
			"description": "Include members with status 'Terminated'"
		},
		{
			"fieldname": "include_suspended",
			"label": __("Include Suspended Members"),
			"fieldtype": "Check",
			"default": 0,
			"description": "Include members with status 'Suspended'"
		},
		{
			"fieldname": "member_status",
			"label": __("Member Status"),
			"fieldtype": "Select",
			"options": "\nActive\nPending\nSuspended\nTerminated",
			"description": "Filter by specific member status (optional)"
		},
		{
			"fieldname": "problems_only",
			"label": __("Problems Only"),
			"fieldtype": "Check",
			"default": 0,
			"description": "Show only members with schedule issues or no schedules"
		},
		{
			"fieldname": "critical_only",
			"label": __("Critical Issues Only"),
			"fieldtype": "Check",
			"default": 0,
			"description": "Show only critical issues (>7 days overdue)"
		}
	],

	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Color code member status
		if (column.fieldname == "member_status") {
			if (value == "Terminated") {
				value = `<span style="color: red; font-weight: bold;">${value}</span>`;
			} else if (value == "Suspended") {
				value = `<span style="color: orange; font-weight: bold;">${value}</span>`;
			} else if (value == "Pending") {
				value = `<span style="color: blue;">${value}</span>`;
			}
		}

		// Highlight overdue days
		if (column.fieldname == "days_overdue" && value && value > 0) {
			if (value > 14) {
				value = `<span style="color: red; font-weight: bold; background-color: #ffebee; padding: 2px 6px; border-radius: 3px;">${value}</span>`;
			} else if (value > 7) {
				value = `<span style="color: orange; font-weight: bold; background-color: #fff3e0; padding: 2px 6px; border-radius: 3px;">${value}</span>`;
			} else {
				value = `<span style="color: #f57c00; background-color: #fff8e1; padding: 2px 6px; border-radius: 3px;">${value}</span>`;
			}
		}

		// Format currency with better visibility
		if (column.fieldname == "dues_rate" && value) {
			value = `<span style="font-weight: bold;">€${parseFloat(value).toFixed(2)}</span>`;
		}

		return value;
	},

	onload: function(report) {
		// Add custom buttons for bulk actions
		report.page.add_inner_button(__("Coverage Analysis"), function() {
			frappe.call({
				method: "verenigingen.verenigingen.report.members_without_dues_schedule.members_without_dues_schedule.get_coverage_gap_analysis",
				callback: function(r) {
					if (r.message && r.message.success) {
						let analysis = r.message.analysis;
						let summary = analysis.summary;

						let message = `
							<div style="margin-bottom: 15px;">
								<h4>Coverage Analysis Summary</h4>
								<ul>
									<li><strong>Total Daily Schedules:</strong> ${analysis.total_daily_schedules}</li>
									<li><strong>Healthy:</strong> <span style="color: green;">${summary.healthy_count}</span></li>
									<li><strong>With Issues:</strong> <span style="color: orange;">${summary.gap_count}</span></li>
									<li><strong>Critical:</strong> <span style="color: red;">${summary.critical_count}</span></li>
									<li><strong>Health Percentage:</strong> ${summary.health_percentage}%</li>
								</ul>
							</div>
						`;

						if (summary.critical_count > 0) {
							message += `
								<div>
									<h5 style="color: red;">Critical Issues Found:</h5>
									<ul>
							`;
							analysis.critical_gaps.forEach(function(gap) {
								message += `<li><strong>${gap.member}:</strong> ${gap.issues.join(', ')}</li>`;
							});
							message += `</ul></div>`;
						}

						frappe.msgprint({
							title: __("Coverage Gap Analysis"),
							message: message,
							indicator: summary.critical_count > 0 ? 'red' : (summary.gap_count > 0 ? 'orange' : 'green')
						});
					} else {
						frappe.msgprint({
							title: __("Error"),
							message: r.message ? r.message.error : "Failed to get analysis",
							indicator: 'red'
						});
					}
				}
			});
		});

		report.page.add_inner_button(__("Fix Selected Issues"), function() {
			let data = report.data;
			if (!data || data.length === 0) {
				frappe.msgprint(__("No data available"));
				return;
			}

			// Get members with issues
			let problematic_members = data.filter(function(row) {
				return row.days_overdue > 0 || row.dues_schedule_status.includes("No Schedule");
			});

			if (problematic_members.length === 0) {
				frappe.msgprint(__("No issues found to fix"));
				return;
			}

			frappe.confirm(
				__("This will attempt to fix schedule issues for {0} members. Continue?", [problematic_members.length]),
				function() {
					let member_list = problematic_members.map(row => row.member_id);

					frappe.call({
						method: "verenigingen.verenigingen.report.members_without_dues_schedule.members_without_dues_schedule.fix_member_schedule_issues",
						args: {
							member_list: member_list
						},
						callback: function(r) {
							if (r.message && r.message.success) {
								let result = r.message;
								frappe.msgprint({
									title: __("Batch Fix Results"),
									message: `
										<div>
											<p><strong>Processed:</strong> ${result.total_processed} members</p>
											<p><strong>Fixed:</strong> <span style="color: green;">${result.success_count}</span></p>
											<p><strong>Failed:</strong> <span style="color: red;">${result.total_processed - result.success_count}</span></p>
										</div>
									`,
									indicator: result.success_count === result.total_processed ? 'green' : 'orange'
								});

								// Refresh the report
								report.refresh();
							} else {
								frappe.msgprint({
									title: __("Error"),
									message: r.message ? r.message.error : "Failed to fix issues",
									indicator: 'red'
								});
							}
						}
					});
				}
			);
		});
	}
};
