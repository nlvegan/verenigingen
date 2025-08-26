/**
 * @fileoverview Team DocType Controller - Organizational Team Management and Coordination
 *
 * This module provides the controller framework for managing organizational teams within
 * the association structure. Teams represent functional groups that work on specific
 * projects, committees, or operational areas, complementing the chapter-based geographic
 * organization with purpose-driven collaborative structures.
 *
 * Key Features:
 * - Team creation and lifecycle management
 * - Member assignment and role definition
 * - Project and task coordination capabilities
 * - Integration with volunteer management systems
 * - Resource allocation and budget tracking
 * - Communication and collaboration tools
 *
 * Business Value:
 * - Enables project-based organization beyond geographic chapters
 * - Facilitates cross-chapter collaboration on shared initiatives
 * - Supports specialized working groups and committees
 * - Provides structure for volunteer skill development
 * - Enables resource tracking and project accountability
 * - Supports strategic initiative coordination
 *
 * Technical Architecture:
 * - Standard Frappe DocType form controller framework
 * - Integration with volunteer and member management
 * - Coordination with chapter-based organizational structure
 * - Support for project management workflows
 * - Foundation for team collaboration tools
 *
 * Organizational Integration:
 * - Complements chapter-based geographic organization
 * - Supports matrix organizational structures
 * - Enables skill-based volunteer assignment
 * - Facilitates cross-functional project teams
 * - Provides framework for committee management
 *
 * Future Enhancements:
 * - Team member role management and permissions
 * - Project timeline and milestone tracking
 * - Resource allocation and budget management
 * - Communication channel integration
 * - Performance metrics and reporting
 * - Integration with external collaboration tools
 *
 * @author Verenigingen Development Team
 * @version 1.1.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires verenigingen.verenigingen.doctype.volunteer (Volunteer management)
 * @requires verenigingen.verenigingen.doctype.member (Member integration)
 * @requires verenigingen.verenigingen.doctype.chapter (Organizational coordination)
 *
 * @example
 * // Team configuration workflow:
 * // 1. Create team with purpose and scope definition
 * // 2. Assign team leader and core members
 * // 3. Define roles and responsibilities
 * // 4. Set up project goals and timelines
 * // 5. Configure communication and collaboration tools
 *
 * @see {@link verenigingen.verenigingen.doctype.volunteer} Volunteer Management
 * @see {@link verenigingen.verenigingen.doctype.chapter} Chapter Organization
 * @see {@link verenigingen.verenigingen.doctype.team_member} Team Member Management
 */

// Copyright (c) 2025, Foppe de Haan and contributors
// For license information, please see license.txt

/**
 * @namespace TeamController
 * @description Form controller for Team DocType with role profile management
 *
 * Key Features:
 * - Role profile configuration and assignment
 * - Database-driven role profile mapping
 * - Automatic role profile application to team members
 * - Role-specific profile override capabilities
 */

/**
 * Team DocType Controller - Role Profile Integration
 *
 * Handles team role profile configuration and member assignment with
 * automatic role profile application based on database-driven configuration.
 */
frappe.ui.form.on('Team', {
	/**
	 * @method refresh
	 * @description Initializes team management interface with role profile functionality
	 * @param {Object} frm - Frappe form object
	 */
	refresh(frm) {
		setup_team_role_profile_ui(frm);
		setup_team_buttons(frm);
		setup_team_member_grid(frm);
	},

	/**
	 * @method enable_role_specific_profiles
	 * @description Handles toggle for role-specific profile configuration
	 * @param {Object} frm - Form object
	 */
	enable_role_specific_profiles(frm) {
		handle_role_specific_profiles_toggle(frm);
	},

	/**
	 * @method default_role_profile
	 * @description Validates default role profile selection
	 * @param {Object} frm - Form object
	 */
	default_role_profile(frm) {
		validate_default_role_profile(frm);
	}
});

/**
 * Team Role Profile Assignment Child Table Handler
 */
frappe.ui.form.on('Team Role Profile Assignment', {
	/**
	 * @method team_role
	 * @description Validates team role selection and checks for duplicates
	 */
	team_role(frm, cdt, cdn) {
		validate_team_role_assignment(frm, cdt, cdn);
	},

	/**
	 * @method role_profile
	 * @description Validates role profile selection for team role
	 */
	role_profile(frm, cdt, cdn) {
		validate_role_profile_assignment(frm, cdt, cdn);
	}
});

// ==================== UI SETUP FUNCTIONS ====================

/**
 * Setup Team Role Profile UI Components
 * @param {Object} frm - Form object
 */
function setup_team_role_profile_ui(frm) {
	// Set conditional visibility for role-specific profiles table
	frm.toggle_display('role_specific_profiles', frm.doc.enable_role_specific_profiles);

	// Add helpful descriptions
	if (frm.doc.enable_role_specific_profiles) {
		frm.set_df_property('role_specific_profiles', 'description',
			__('Configure different role profiles for different team roles. This overrides the default role profile for specific roles.'));
	}
}

/**
 * Setup Team Action Buttons
 * @param {Object} frm - Form object
 */
function setup_team_buttons(frm) {
	if (!frm.doc.__islocal && frm.doc.status === 'Active') {
		// Add role profile management button
		frm.add_custom_button(__('Manage Role Profiles'), () => {
			show_role_profile_management_dialog(frm);
		}, __('Team Management'));

		// Add member role assignment button
		frm.add_custom_button(__('Apply Role Profiles to Members'), () => {
			apply_role_profiles_to_team_members(frm);
		}, __('Team Management'));
	}
}

/**
 * Setup Team Member Grid with Role Profile Integration
 * @param {Object} frm - Form object
 */
function setup_team_member_grid(frm) {
	if (frm.fields_dict.team_members && frm.fields_dict.team_members.grid) {
		// Add role profile column to team members grid if not present
		const grid = frm.fields_dict.team_members.grid;

		// Refresh grid to show role profile assignments
		grid.refresh();

		// Set up member field query
		grid.get_field('member').get_query = function () {
			return {
				filters: {
					status: ['in', ['Active', 'New']]
				}
			};
		};
	}
}

// ==================== EVENT HANDLERS ====================

/**
 * Handle Role-Specific Profiles Toggle
 * @param {Object} frm - Form object
 */
function handle_role_specific_profiles_toggle(frm) {
	frm.toggle_display('role_specific_profiles', frm.doc.enable_role_specific_profiles);

	if (frm.doc.enable_role_specific_profiles) {
		frappe.show_alert({
			message: __('You can now configure different role profiles for different team roles'),
			indicator: 'blue'
		}, 5);

		// Refresh the child table
		frm.refresh_field('role_specific_profiles');
	} else {
		// Clear role-specific profiles if disabled
		if (frm.doc.role_specific_profiles && frm.doc.role_specific_profiles.length > 0) {
			frappe.confirm(__('This will clear all role-specific profile assignments. Continue?'), () => {
				frm.clear_table('role_specific_profiles');
				frm.refresh_field('role_specific_profiles');
			});
		}
	}
}

/**
 * Validate Default Role Profile
 * @param {Object} frm - Form object
 */
function validate_default_role_profile(frm) {
	if (frm.doc.default_role_profile) {
		// Validate that the role profile exists and is active
		frappe.db.get_value('Role Profile', frm.doc.default_role_profile, 'disabled', (r) => {
			if (r && r.disabled) {
				frappe.msgprint({
					title: __('Invalid Role Profile'),
					message: __('The selected role profile is disabled. Please choose an active role profile.'),
					indicator: 'orange'
				});
				frm.set_value('default_role_profile', '');
			}
		});
	}
}

/**
 * Validate Team Role Assignment
 * @param {Object} frm - Form object
 * @param {string} cdt - Child DocType
 * @param {string} cdn - Child document name
 */
function validate_team_role_assignment(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.team_role) { return; }

	// Check for duplicate role assignments
	const existing_assignment = frm.doc.role_specific_profiles.find(r =>
		r.name !== cdn && r.team_role === row.team_role
	);

	if (existing_assignment) {
		frappe.msgprint({
			title: __('Duplicate Role Assignment'),
			message: __('This team role already has a role profile assignment. Please choose a different role.'),
			indicator: 'red'
		});
		frappe.model.set_value(cdt, cdn, 'team_role', '');
		return;
	}

	// Auto-suggest description based on role
	if (row.team_role && !row.description) {
		frappe.model.set_value(cdt, cdn, 'description',
			__('Role profile assignment for {0} role', [row.team_role]));
	}
}

/**
 * Validate Role Profile Assignment
 * @param {Object} frm - Form object
 * @param {string} cdt - Child DocType
 * @param {string} cdn - Child document name
 */
function validate_role_profile_assignment(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.role_profile) { return; }

	// Validate that the role profile is active
	frappe.db.get_value('Role Profile', row.role_profile, 'disabled', (r) => {
		if (r && r.disabled) {
			frappe.msgprint({
				title: __('Invalid Role Profile'),
				message: __('The selected role profile is disabled. Please choose an active role profile.'),
				indicator: 'orange'
			});
			frappe.model.set_value(cdt, cdn, 'role_profile', '');
		}
	});
}

// ==================== DIALOG FUNCTIONS ====================

/**
 * Show Role Profile Management Dialog
 * @param {Object} frm - Form object
 */
function show_role_profile_management_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Role Profile Management'),
		fields: [
			{
				fieldtype: 'HTML',
				options: generate_role_profile_summary_html(frm)
			},
			{
				fieldtype: 'Section Break'
			},
			{
				label: __('Actions'),
				fieldtype: 'HTML',
				options: `
					<button class="btn btn-primary btn-sm" onclick="cur_dialog.hide(); cur_frm.scroll_to_field('default_role_profile');">
						<i class="fa fa-edit"></i> ${__('Edit Configuration')}
					</button>
					<button class="btn btn-success btn-sm" onclick="apply_role_profiles_to_team_members(cur_frm); cur_dialog.hide();">
						<i class="fa fa-users"></i> ${__('Apply to Members')}
					</button>
				`
			}
		],
		primary_action_label: __('Close'),
		primary_action() {
			d.hide();
		}
	});

	d.show();
}

/**
 * Generate Role Profile Summary HTML
 * @param {Object} frm - Form object
 * @returns {string} HTML content
 */
function generate_role_profile_summary_html(frm) {
	let html = '<div class="role-profile-summary">';

	// Default role profile
	html += `<h5>${__('Default Role Profile')}</h5>`;
	if (frm.doc.default_role_profile) {
		html += `<p class="text-success"><i class="fa fa-check"></i> ${frm.doc.default_role_profile}</p>`;
	} else {
		html += `<p class="text-muted"><i class="fa fa-info-circle"></i> ${__('No default role profile configured')}</p>`;
	}

	// Role-specific profiles
	html += `<h5>${__('Role-Specific Profiles')}</h5>`;
	if (frm.doc.enable_role_specific_profiles && frm.doc.role_specific_profiles?.length > 0) {
		html += '<ul class="list-unstyled">';
		frm.doc.role_specific_profiles.forEach(assignment => {
			html += `<li class="text-info"><i class="fa fa-user"></i> ${assignment.team_role}: ${assignment.role_profile}</li>`;
		});
		html += '</ul>';
	} else {
		html += `<p class="text-muted"><i class="fa fa-info-circle"></i> ${__('No role-specific profiles configured')}</p>`;
	}

	html += '</div>';
	return html;
}

/**
 * Apply Role Profiles to Team Members
 * @param {Object} frm - Form object
 */
function apply_role_profiles_to_team_members(frm) {
	if (!frm.doc.name || frm.doc.__islocal) {
		frappe.msgprint(__('Please save the team first'));
		return;
	}

	frappe.confirm(
		__('This will apply role profiles to all team members based on your configuration. Continue?'),
		() => {
			frappe.call({
				method: 'verenigingen.utils.team_role_profile_manager.bulk_assign_team_role_profiles',
				args: {
					team_name: frm.doc.name
				},
				freeze: true,
				freeze_message: __('Applying role profiles...'),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Role profiles applied successfully to {0} members', [r.message.members_updated || 0]),
							indicator: 'green'
						}, 5);
					} else {
						frappe.msgprint(__('No members were updated. Please check your team configuration.'));
					}
				},
				error(r) {
					frappe.msgprint(__('Error applying role profiles: {0}', [r.message]));
				}
			});
		}
	);
}

// Make apply_role_profiles_to_team_members globally accessible for dialog
window.apply_role_profiles_to_team_members = apply_role_profiles_to_team_members;
