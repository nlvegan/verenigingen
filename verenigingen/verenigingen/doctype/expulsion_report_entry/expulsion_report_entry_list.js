/**
 * @fileoverview Expulsion Report Entry List View - JavaScript Configuration
 *
 * This file manages the list view behavior for expulsion report entries, providing comprehensive
 * oversight and governance tools for sensitive disciplinary actions within the organization.
 *
 * BUSINESS PURPOSE:
 * Ensures proper governance and compliance for disciplinary actions:
 * - Track expulsion decisions with full audit trails
 * - Monitor appeal processes and status changes
 * - Support board-level governance and oversight
 * - Generate compliance reports for regulatory requirements
 * - Maintain organizational accountability and transparency
 *
 * GOVERNANCE FEATURES:
 * - Status tracking with visual indicators (Active: red, Under Appeal: orange, Reversed: green)
 * - Appeals process integration with workflow management
 * - Compliance verification and board review tracking
 * - Chapter-specific reporting and analysis
 * - Export capabilities for governance documentation
 *
 * EXPULSION CATEGORIES:
 * - Policy Violation (Red): Breach of organizational policies
 * - Disciplinary Action (Orange): Behavioral or conduct issues
 * - Expulsion (Dark Red): Most severe disciplinary measure
 *
 * ADMINISTRATIVE TOOLS:
 * - Governance Report Generator: Comprehensive period-based reporting
 * - Excel Export: Detailed data export for analysis
 * - Bulk Compliance Verification: Efficient board review processing
 * - Appeal Filing: Direct integration with appeals workflow
 *
 * COMPLIANCE MONITORING:
 * - Automatic compliance checking indicators
 * - Board review date tracking
 * - Appeal status monitoring
 * - Chapter involvement documentation
 * - Approval chain verification
 *
 * REPORTING CAPABILITIES:
 * - Period-based governance reports with summary statistics
 * - Chapter-specific analysis and filtering
 * - Appeals data integration for comprehensive oversight
 * - Compliance issue identification and tracking
 * - Visual dashboard with key metrics
 *
 * SECURITY CONSIDERATIONS:
 * - Controlled access to sensitive disciplinary information
 * - Audit trail maintenance for all actions
 * - Board-level approval requirements
 * - Protected member information with proper linking
 *
 * @author Frappe Technologies Pvt. Ltd.
 * @since 2025
 * @category Governance / Compliance
 * @requires frappe.listview_settings
 * @requires verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry
 */

frappe.listview_settings['Expulsion Report Entry'] = {
	get_indicator(doc) {
		if (doc.status === 'Active') {
			return [__('Active'), 'red', 'status,=,Active'];
		} else if (doc.status === 'Under Appeal') {
			return [__('Under Appeal'), 'orange', 'status,=,Under Appeal'];
		} else if (doc.status === 'Reversed') {
			return [__('Reversed'), 'green', 'status,=,Reversed'];
		}
		return [__(doc.status), 'gray'];
	},

	onload(listview) {
		// Add menu items
		listview.page.add_menu_item(__('Generate Governance Report'), () => {
			show_governance_report_dialog(listview);
		});

		listview.page.add_menu_item(__('Export to Excel'), () => {
			export_expulsion_report(listview);
		});

		// Add action button for bulk compliance verification
		listview.page.add_action_item(__('Mark Compliance Verified'), () => {
			bulk_verify_compliance(listview);
		});
	},

	formatters: {
		member_name(value, df, doc) {
			return `<a href="/app/member/${doc.member_id}">${value}</a>`;
		},

		expulsion_type(value) {
			const type_colors = {
				'Policy Violation': 'red',
				'Disciplinary Action': 'orange',
				Expulsion: 'darkred'
			};

			const color = type_colors[value] || 'gray';
			return `<span style="color: ${color}; font-weight: bold;">${value}</span>`;
		},

		chapter_involved(value, df, doc) {
			if (!value) { return '-'; }
			return `<a href="/app/chapter/${value}">${value}</a>`;
		},

		under_appeal(value) {
			if (value) {
				return '<span class="indicator orange">Yes</span>';
			}
			return '<span class="indicator gray">No</span>';
		},

		compliance_checked(value) {
			if (value) {
				return '<i class="fa fa-check text-success"></i>';
			}
			return '<i class="fa fa-times text-muted"></i>';
		}
	},

	button: {
		show(doc) {
			return doc.status === 'Active' && !doc.under_appeal;
		},
		get_label() {
			return __('File Appeal');
		},
		get_description(doc) {
			return __('File an appeal for this expulsion');
		},
		action(doc) {
			// Navigate to create appeal
			frappe.new_doc('Termination Appeals Process', {
				member: doc.member_id,
				member_name: doc.member_name,
				expulsion_entry: doc.name
			});
		}
	}
};

function show_governance_report_dialog(listview) {
	const dialog = new frappe.ui.Dialog({
		title: __('Generate Governance Report'),
		fields: [
			{
				fieldtype: 'Date',
				fieldname: 'from_date',
				label: __('From Date'),
				default: frappe.datetime.add_months(frappe.datetime.get_today(), -3)
			},
			{
				fieldtype: 'Date',
				fieldname: 'to_date',
				label: __('To Date'),
				default: frappe.datetime.get_today()
			},
			{
				fieldtype: 'Link',
				fieldname: 'chapter',
				label: __('Chapter'),
				options: 'Chapter',
				description: __('Leave blank for all chapters')
			},
			{
				fieldtype: 'Check',
				fieldname: 'include_appeals',
				label: __('Include Appeals Data'),
				default: 1
			}
		],
		primary_action_label: __('Generate Report'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry.generate_expulsion_governance_report',
				args: {
					date_range: `${values.from_date},${values.to_date}`,
					chapter: values.chapter,
					include_appeals: values.include_appeals
				},
				callback(r) {
					if (r.message) {
						// Show report in a new dialog or route to report viewer
						show_governance_report_results(r.message);
						dialog.hide();
					}
				}
			});
		}
	});

	dialog.show();
}

function export_expulsion_report(listview) {
	// Get selected items or all filtered items
	const selected = listview.get_checked_items();
	const filters = selected.length > 0
		? { name: ['in', selected.map(item => item.name)] }
		: listview.filter_area.get();

	frappe.call({
		method: 'frappe.desk.query_report.export_query',
		args: {
			title: __('Expulsion Report'),
			doctype: 'Expulsion Report Entry',
			file_format_type: 'Excel',
			filters,
			fields: [
				'name', 'member_name', 'member_id', 'expulsion_date',
				'expulsion_type', 'chapter_involved', 'status',
				'under_appeal', 'initiated_by', 'approved_by'
			]
		}
	});
}

function bulk_verify_compliance(listview) {
	const selected = listview.get_checked_items();

	if (!selected.length) {
		frappe.msgprint(__('Please select expulsion entries to verify'));
		return;
	}

	frappe.confirm(
		__('Mark {0} entries as compliance verified?', [selected.length]),
		() => {
			frappe.call({
				method: 'frappe.client.set_value',
				args: {
					doctype: 'Expulsion Report Entry',
					name: selected.map(item => item.name),
					fieldname: {
						compliance_checked: 1,
						board_review_date: frappe.datetime.get_today()
					}
				},
				callback() {
					listview.refresh();
					frappe.show_alert({
						message: __('Compliance verified for {0} entries', [selected.length]),
						indicator: 'green'
					}, 5);
				}
			});
		}
	);
}

function show_governance_report_results(data) {
	// Create a dialog to show the report results
	const html = generate_governance_report_html(data);

	const report_dialog = new frappe.ui.Dialog({
		title: __('Governance Report Results'),
		size: 'extra-large',
		fields: [
			{
				fieldtype: 'HTML',
				options: html
			}
		],
		primary_action_label: __('Download PDF'),
		primary_action() {
			// Generate PDF version
			frappe.msgprint(__('PDF generation to be implemented'));
		}
	});

	report_dialog.show();
}

function generate_governance_report_html(data) {
	return `
        <div class="governance-report">
            <h3>Expulsion Governance Report</h3>
            <p><strong>Period:</strong> ${data.report_period}</p>
            <p><strong>Generated:</strong> ${data.report_generated}</p>

            <div class="row mt-4">
                <div class="col-md-3 text-center">
                    <div class="card">
                        <div class="card-body">
                            <h4>${data.summary.total_expulsions}</h4>
                            <p>Total Expulsions</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 text-center">
                    <div class="card">
                        <div class="card-body">
                            <h4>${data.summary.under_appeal}</h4>
                            <p>Under Appeal</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 text-center">
                    <div class="card">
                        <div class="card-body">
                            <h4>${data.summary.chapters_involved}</h4>
                            <p>Chapters Involved</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 text-center">
                    <div class="card">
                        <div class="card-body">
                            <h4>${data.compliance_issues.length}</h4>
                            <p>Compliance Issues</p>
                        </div>
                    </div>
                </div>
            </div>

            ${data.compliance_issues.length > 0 ? `
                <div class="mt-4">
                    <h4>Compliance Issues</h4>
                    <ul>
                        ${data.compliance_issues.map(issue =>
		`<li class="text-${issue.severity === 'High' ? 'danger' : 'warning'}">
                                ${issue.issue}: ${issue.count} occurrences
                            </li>`
	).join('')}
                    </ul>
                </div>
            ` : ''}
        </div>
    `;
}
