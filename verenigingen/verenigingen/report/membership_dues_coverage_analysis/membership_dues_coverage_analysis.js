// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.query_reports['Membership Dues Coverage Analysis'] = {
	'filters': [
		{
			'fieldname': 'member',
			'label': __('Member'),
			'fieldtype': 'Link',
			'options': 'Member',
			'width': '80'
		},
		{
			'fieldname': 'chapter',
			'label': __('Chapter'),
			'fieldtype': 'Link',
			'options': 'Chapter',
			'width': '80'
		},
		{
			'fieldname': 'billing_frequency',
			'label': __('Billing Frequency'),
			'fieldtype': 'Select',
			'options': '\nDaily\nMonthly\nQuarterly\nAnnual\nCustom',
			'width': '80'
		},
		{
			'fieldname': 'gap_severity',
			'label': __('Gap Severity'),
			'fieldtype': 'Select',
			'options': '\nMinor\nModerate\nSignificant\nCritical',
			'width': '80'
		},
		{
			'fieldname': 'from_date',
			'label': __('From Date'),
			'fieldtype': 'Date',
			'default': frappe.datetime.add_months(frappe.datetime.get_today(), -12),
			'width': '80'
		},
		{
			'fieldname': 'to_date',
			'label': __('To Date'),
			'fieldtype': 'Date',
			'default': frappe.datetime.get_today(),
			'width': '80'
		},
		{
			'fieldname': 'show_only_gaps',
			'label': __('Show Only Members with Gaps'),
			'fieldtype': 'Check',
			'default': 0
		},
		{
			'fieldname': 'show_only_catchup_required',
			'label': __('Show Only Catch-up Required'),
			'fieldtype': 'Check',
			'default': 0
		}
	],

	'formatter': function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Color-code coverage percentage
		if (column.fieldname == 'coverage_percentage') {
			if (flt(data.coverage_percentage) < 50) {
				value = `<span style="color: #d73502">${value}</span>`;
			} else if (flt(data.coverage_percentage) < 80) {
				value = `<span style="color: #ff8c00">${value}</span>`;
			} else if (flt(data.coverage_percentage) < 100) {
				value = `<span style="color: #ffa500">${value}</span>`;
			} else {
				value = `<span style="color: #2e8b57">${value}</span>`;
			}
		}

		// Color-code gap days
		if (column.fieldname == 'gap_days') {
			if (flt(data.gap_days) > 90) {
				value = `<span style="color: #d73502; font-weight: bold">${value}</span>`;
			} else if (flt(data.gap_days) > 30) {
				value = `<span style="color: #ff8c00; font-weight: bold">${value}</span>`;
			} else if (flt(data.gap_days) > 7) {
				value = `<span style="color: #ffa500">${value}</span>`;
			}
		}

		// Color-code catch-up required
		if (column.fieldname == 'catchup_required') {
			if (data.catchup_required) {
				value = '<span style="color: #d73502">✓</span>';
			} else {
				value = '<span style="color: #2e8b57">-</span>';
			}
		}

		// Highlight outstanding amounts
		if (column.fieldname == 'outstanding_amount') {
			if (flt(data.outstanding_amount) > 0) {
				value = `<span style="color: #d73502; font-weight: bold">${value}</span>`;
			}
		}

		// Format current gaps with severity colors
		if (column.fieldname == 'current_gaps') {
			if (data.current_gaps && data.current_gaps !== 'No gaps') {
				if (data.current_gaps.includes('Critical')) {
					value = `<span style="color: #d73502">${value}</span>`;
				} else if (data.current_gaps.includes('Significant')) {
					value = `<span style="color: #ff8c00">${value}</span>`;
				} else if (data.current_gaps.includes('Moderate')) {
					value = `<span style="color: #ffa500">${value}</span>`;
				}
			} else {
				value = `<span style="color: #2e8b57">${value}</span>`;
			}
		}

		return value;
	},

	'onload': function(report) {
		// Add custom buttons
		report.page.add_inner_button(__('Generate Catch-up Invoices'), function() {
			generate_catchup_invoices(report);
		});

		report.page.add_inner_button(__('Export Gap Analysis'), function() {
			export_gap_analysis(report);
		});

		report.page.add_inner_button(__('Coverage Timeline'), function() {
			show_coverage_timeline(report);
		});
	}
};

function generate_catchup_invoices(report) {
	let selected_members = [];

	// Get selected rows or all rows with catch-up required
	let data = report.data;
	for (let i = 0; i < data.length; i++) {
		if (data[i].catchup_required) {
			selected_members.push({
				member: data[i].member,
				member_name: data[i].member_name,
				catchup_amount: data[i].catchup_amount,
				catchup_periods: data[i].catchup_periods
			});
		}
	}

	if (selected_members.length === 0) {
		frappe.msgprint(__('No members require catch-up invoices.'));
		return;
	}

	// Show confirmation dialog
	let dialog = new frappe.ui.Dialog({
		title: __('Generate Catch-up Invoices'),
		fields: [
			{
				fieldtype: 'HTML',
				fieldname: 'members_html',
				options: `
					<div class="alert alert-info">
						<strong>Members requiring catch-up invoices: ${selected_members.length}</strong>
						<ul>
							${selected_members.map(m =>
		`<li>${m.member_name} (${m.member}) - €${m.catchup_amount}</li>`
	).join('')}
						</ul>
					</div>
				`
			},
			{
				fieldtype: 'Check',
				fieldname: 'confirm_generation',
				label: __('I confirm that I want to generate catch-up invoices for these members'),
				reqd: 1
			}
		],
		primary_action_label: __('Generate Invoices'),
		primary_action: function(values) {
			if (!values.confirm_generation) {
				frappe.msgprint(__('Please confirm the generation of catch-up invoices.'));
				return;
			}

			// Call server method to generate catch-up invoices
			frappe.call({
				method: 'verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis.generate_catchup_invoices',
				args: {
					members: selected_members
				},
				callback: function(r) {
					if (r.message) {
						frappe.msgprint({
							title: __('Catch-up Invoices Generated'),
							message: r.message,
							indicator: 'green'
						});
						report.refresh();
					}
				}
			});

			dialog.hide();
		}
	});

	dialog.show();
}

function export_gap_analysis(report) {
	// Export detailed gap analysis to Excel
	frappe.call({
		method: 'verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis.export_gap_analysis',
		args: {
			filters: report.get_values()
		},
		callback: function(r) {
			if (r.message) {
				// Download the generated file
				window.open(r.message.file_url);
			}
		}
	});
}

function show_coverage_timeline(report) {
	// Show coverage timeline for selected member
	let selected_rows = report.get_checked_items();

	if (selected_rows.length !== 1) {
		frappe.msgprint(__('Please select exactly one member to view coverage timeline.'));
		return;
	}

	let member = selected_rows[0].member;

	// Open coverage timeline dialog
	frappe.call({
		method: 'verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis.get_coverage_timeline_data',
		args: {
			member: member,
			from_date: report.get_values().from_date,
			to_date: report.get_values().to_date
		},
		callback: function(r) {
			if (r.message) {
				show_timeline_dialog(member, r.message);
			}
		}
	});
}

function show_timeline_dialog(member, timeline_data) {
	let dialog = new frappe.ui.Dialog({
		title: __('Coverage Timeline - {0}', [member]),
		size: 'extra-large',
		fields: [
			{
				fieldtype: 'HTML',
				fieldname: 'timeline_chart',
				options: generate_timeline_html(timeline_data)
			}
		]
	});

	dialog.show();
}

function generate_timeline_html(timeline_data) {
	// Generate HTML for timeline visualization
	let html = `
		<div class="coverage-timeline">
			<h4>Coverage Timeline</h4>
			<div class="timeline-container">
	`;

	// Add timeline visualization logic here
	// This would create a visual representation of coverage periods and gaps

	html += `
			</div>
			<div class="timeline-legend">
				<span class="legend-item"><span class="legend-color" style="background: #2e8b57;"></span> Paid Coverage</span>
				<span class="legend-item"><span class="legend-color" style="background: #ffa500;"></span> Outstanding Coverage</span>
				<span class="legend-item"><span class="legend-color" style="background: #d73502;"></span> Coverage Gap</span>
			</div>
		</div>
		<style>
			.coverage-timeline { margin: 20px 0; }
			.timeline-container { border: 1px solid #ddd; min-height: 100px; padding: 10px; }
			.timeline-legend { margin-top: 10px; }
			.legend-item { margin-right: 20px; }
			.legend-color { display: inline-block; width: 15px; height: 15px; margin-right: 5px; vertical-align: middle; }
		</style>
	`;

	return html;
}
