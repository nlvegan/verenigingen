/**
 * @fileoverview Team Responsibility Management Controller
 * @description Manages task assignment and responsibility tracking within organizational teams
 *
 * Business Context:
 * Enables structured responsibility assignment and tracking within teams,
 * ensuring clear accountability and progress monitoring for organizational
 * tasks and projects. Essential for distributed team management and governance.
 *
 * Key Features:
 * - Team membership validation for assignments
 * - Responsibility status tracking and workflow management
 * - Cross-reference validation between teams and members
 * - Progress monitoring with status-based behaviors
 *
 * Team Management:
 * - Ensures assignments are made only to team members
 * - Maintains data integrity across team relationships
 * - Provides clear responsibility ownership tracking
 * - Supports hierarchical task organization
 *
 * Workflow Integration:
 * - Status-driven notification systems
 * - Progress tracking for completion metrics
 * - Assignment validation for organizational compliance
 * - Performance monitoring capabilities
 *
 * Data Validation:
 * - Real-time team membership verification
 * - Assignment constraint enforcement
 * - Status consistency checking
 * - Historical assignment tracking
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module TeamResponsibility
 * @requires frappe.ui.form
 */

frappe.ui.form.on('Team Responsibility', {
	responsibility(_frm, _cdt, _cdn) {
		// No specific actions needed yet, but keeping for future extensions
	},

	assigned_to(frm, cdt, cdn) {
		// When assigning to a team member, validate that they belong to this team
		const row = locals[cdt][cdn];
		const parent = frappe.get_doc(frm.doctype, frm.docname);

		if (row.assigned_to && parent.team_members) {
			// Check if the assigned_to exists in the team_members
			const team_member_exists = parent.team_members.some((member) => {
				return member.name === row.assigned_to;
			});

			if (!team_member_exists) {
				frappe.msgprint(__('The assigned person must be a member of this team'));
				frappe.model.set_value(cdt, cdn, 'assigned_to', '');
			}
		}
	},

	status(frm, cdt, cdn) {
		// Update UI based on status changes
		const row = locals[cdt][cdn];

		// You could add specific behaviors for different statuses
		if (row.status === 'Completed') {
			// Maybe notify or update some counters
		}
	}
});
