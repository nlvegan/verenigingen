/**
 * @fileoverview Volunteer Interest Analysis Report
 * @description Advanced analytics for volunteer recruitment and engagement optimization
 *
 * Business Context:
 * Provides comprehensive analysis of member volunteer interests, enabling
 * targeted recruitment campaigns and optimal volunteer-opportunity matching.
 * Critical for maximizing volunteer engagement and organizational capacity.
 *
 * Key Features:
 * - Multi-dimensional filtering by chapter, availability, and experience
 * - Bulk volunteer record creation for interested members
 * - Automated coordinator communication with targeted reports
 * - Interest pattern analysis for recruitment optimization
 *
 * Report Capabilities:
 * - Chapter-specific volunteer interest breakdown
 * - Experience level distribution analysis
 * - Availability pattern identification
 * - Gap analysis between interests and opportunities
 *
 * Workflow Integration:
 * - Direct volunteer record creation from interested members
 * - Email integration with chapter coordinators
 * - Automated welcome sequences for new volunteers
 * - Customizable communication templates
 *
 * Strategic Value:
 * - Identifies volunteer recruitment opportunities
 * - Optimizes resource allocation across chapters
 * - Enables proactive volunteer engagement
 * - Supports data-driven volunteer program development
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module VolunteerInterestAnalysis
 * @requires frappe.query_reports, frappe.ui.Dialog
 */

frappe.query_reports['Volunteer Interest Analysis'] = {
	filters: [
		{
			fieldname: 'chapter',
			label: __('Chapter'),
			fieldtype: 'Link',
			options: 'Chapter'
		},
		{
			fieldname: 'availability',
			label: __('Availability'),
			fieldtype: 'Select',
			options: [
				'',
				'Occasional',
				'Monthly',
				'Weekly',
				'Project-based'
			]
		},
		{
			fieldname: 'experience_level',
			label: __('Experience Level'),
			fieldtype: 'Select',
			options: [
				'',
				'Beginner',
				'Intermediate',
				'Experienced',
				'Expert'
			]
		},
		{
			fieldname: 'has_volunteer_record',
			label: __('Has Volunteer Record'),
			fieldtype: 'Check',
			default: 0
		},
		{
			fieldname: 'active_only',
			label: __('Active Members Only'),
			fieldtype: 'Check',
			default: 1
		}
	],

	onload(report) {
		// Add button to create volunteer records
		report.page.add_inner_button(__('Create Volunteer Records'), () => {
			create_volunteer_records(report);
		});

		// Add export to coordinator button
		report.page.add_inner_button(__('Email to Coordinators'), () => {
			email_to_coordinators(report);
		});
	}
};

function create_volunteer_records(report) {
	// Get members without volunteer records
	const members_without_records = report.data.filter(row => !row.volunteer_id);

	if (members_without_records.length === 0) {
		frappe.msgprint(__('All interested members already have volunteer records'));
		return;
	}

	const d = new frappe.ui.Dialog({
		title: __('Create Volunteer Records'),
		fields: [
			{
				fieldname: 'info',
				fieldtype: 'HTML',
				options: `<p>${__('{0} members need volunteer records created', [members_without_records.length])}</p>`
			},
			{
				fieldname: 'initial_status',
				label: __('Initial Status'),
				fieldtype: 'Select',
				options: ['New', 'Onboarding'],
				default: 'New',
				reqd: 1
			},
			{
				fieldname: 'send_welcome_email',
				label: __('Send Welcome Email'),
				fieldtype: 'Check',
				default: 1
			}
		],
		primary_action_label: __('Create Records'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.api.volunteer_management.bulk_create_volunteer_records',
				args: {
					member_names: members_without_records.map(m => m.name),
					initial_status: values.initial_status,
					send_email: values.send_welcome_email
				},
				callback(r) {
					if (r.message) {
						frappe.msgprint(__('{0} volunteer records created', [r.message.created]));
						report.refresh();
					}
				}
			});
			d.hide();
		}
	});

	d.show();
}

function email_to_coordinators(report) {
	// Group data by chapter
	const chapter_data = {};

	report.data.forEach(row => {
		const chapter = row.current_chapter || 'Unassigned';
		if (!chapter_data[chapter]) {
			chapter_data[chapter] = [];
		}
		chapter_data[chapter].push(row);
	});

	const d = new frappe.ui.Dialog({
		title: __('Email Volunteer Interest Report'),
		fields: [
			{
				fieldname: 'chapters',
				label: __('Chapters to Include'),
				fieldtype: 'Table MultiSelect',
				options: Object.keys(chapter_data).map(ch => ({ label: ch, value: ch })),
				reqd: 1
			},
			{
				fieldname: 'email_template',
				label: __('Email Template'),
				fieldtype: 'Link',
				options: 'Email Template',
				default: 'volunteer_interest_report'
			},
			{
				fieldname: 'additional_message',
				label: __('Additional Message'),
				fieldtype: 'Text Editor'
			}
		],
		primary_action_label: __('Send'),
		primary_action(values) {
			frappe.call({
				method: 'verenigingen.api.volunteer_management.send_interest_report',
				args: {
					chapters: values.chapters,
					template: values.email_template,
					message: values.additional_message
				},
				callback(r) {
					if (r.message) {
						frappe.msgprint(__('Reports sent to {0} coordinators', [r.message.sent_count]));
					}
				}
			});
			d.hide();
		}
	});

	d.show();
}
