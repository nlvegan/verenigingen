/**
 * @fileoverview Team Members Report Configuration
 *
 * This report provides a comprehensive view of team members within the Verenigingen
 * application. It displays member details, roles, and responsibilities for specific
 * teams, helping with team management and oversight.
 *
 * Business Context:
 * - Teams organize volunteers and members for specific projects or functions
 * - Team leaders need visibility into their team composition
 * - HR functions require team member reporting for coordination
 * - Volunteer coordinators need to understand team structures
 *
 * Report Features:
 * - Filterable by team selection
 * - Displays member information and roles
 * - Shows team responsibilities and assignments
 * - Supports team management workflows
 *
 * Usage:
 * 1. Select a team from the filter dropdown
 * 2. View all members assigned to that team
 * 3. Review roles and responsibilities
 * 4. Export data for external team management tools
 *
 * @module verenigingen/report/team_members/team_members
 * @version 1.0.0
 * @since 2024
 * @see {@link ../../doctype/team/team.js|Team DocType}
 * @see {@link ../../doctype/team_member/team_member.js|Team Member DocType}
 */

frappe.query_reports['Team Members'] = {
	filters: [
		{
			fieldname: 'team',
			label: __('Team'),
			fieldtype: 'Link',
			options: 'Team',
			reqd: 1
		}
	]
};
