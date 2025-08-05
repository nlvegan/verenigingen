/**
 * @fileoverview Members Without Chapter report JavaScript for interactive assignment
 *
 * Provides interactive functionality for the Members Without Chapter report,
 * enabling administrators to efficiently assign unassigned members to appropriate
 * chapters directly from the report interface. This module transforms the static
 * report into an actionable member management tool.
 *
 * Key Features:
 * - Interactive chapter assignment buttons in report rows
 * - Automatic chapter suggestion based on member data
 * - Manual chapter selection dialog for complex cases
 * - Real-time report refresh after assignments
 * - Bulk assignment capabilities for efficiency
 * - Assignment confirmation and error handling
 *
 * Assignment Workflows:
 * - Suggested assignments based on postal codes or member preferences
 * - Manual assignment dialog with published chapter selection
 * - Confirmation dialogs to prevent accidental assignments
 * - Success/error feedback with appropriate messaging
 * - Automatic report refresh to reflect changes
 *
 * Business Context:
 * Critical for maintaining clean member-chapter relationships and ensuring
 * all active members have appropriate chapter assignments. Helps administrators
 * quickly process new members or fix chapter assignment gaps, supporting
 * effective regional member management and chapter participation tracking.
 *
 * Integration:
 * - Connects to Member and Chapter DocTypes for assignment operations
 * - Uses member management API for secure assignment processing
 * - Integrates with chapter filtering and selection systems
 * - Supports real-time report updates and data refresh
 * - Links to broader member administration workflows
 *
 * @author Verenigingen Development Team
 * @version 1.5.0
 * @since 2024-05-25
 */

frappe.query_reports['Members Without Chapter'] = {
	onload(report) {
		// Event delegation for assign chapter buttons
		$(document).on('click', '.assign-chapter-btn', function (e) {
			e.preventDefault();
			e.stopPropagation();

			const memberName = $(this).data('member');
			const chapterName = $(this).data('chapter');

			frappe.confirm(
				`Are you sure you want to assign ${memberName} to ${chapterName}?`,
				() => {
					assignMemberToChapter(memberName, chapterName, report);
				}
			);
		});

		// Event delegation for manual assign buttons
		$(document).on('click', '.manual-assign-btn', function (e) {
			e.preventDefault();
			e.stopPropagation();

			const memberName = $(this).data('member');
			showManualAssignDialog(memberName, report);
		});
	}
};

function assignMemberToChapter(memberName, chapterName, report) {
	frappe.call({
		method: 'verenigingen.api.member_management.assign_member_to_chapter',
		args: {
			member_name: memberName,
			chapter_name: chapterName
		},
		callback(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					message: `${memberName} has been assigned to ${chapterName}`,
					indicator: 'green'
				});
				// Refresh the report
				if (report && report.refresh) {
					report.refresh();
				}
			} else {
				frappe.msgprint({
					message: r.message?.error || 'Failed to assign member to chapter',
					indicator: 'red'
				});
			}
		},
		error(r) {
			frappe.msgprint({
				message: 'Error assigning member to chapter',
				indicator: 'red'
			});
		}
	});
}

function showManualAssignDialog(memberName, report) {
	// Get available chapters
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Chapter',
			filters: {
				published: 1
			},
			fields: ['name', 'region'],
			order_by: 'name'
		},
		callback(r) {
			if (r.message) {
				const chapters = r.message;
				const options = chapters.map(ch => ({
					label: ch.region ? `${ch.name} - ${ch.region}` : ch.name,
					value: ch.name
				}));

				const dialog = new frappe.ui.Dialog({
					title: `Assign ${memberName} to Chapter`,
					fields: [
						{
							fieldtype: 'Select',
							fieldname: 'chapter',
							label: 'Select Chapter',
							options,
							reqd: 1
						}
					],
					primary_action_label: 'Assign',
					primary_action(values) {
						assignMemberToChapter(memberName, values.chapter, report);
						dialog.hide();
					}
				});

				dialog.show();
			}
		}
	});
}
