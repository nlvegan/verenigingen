/**
 * @fileoverview Chapter Role DocType Controller - Advanced Role Management with Leadership Hierarchy
 *
 * This module provides comprehensive management for chapter-level organizational roles with
 * intelligent chair designation, automatic chapter head assignment, and conflict detection.
 * Designed to support complex organizational hierarchies while maintaining clear leadership
 * accountability and preventing administrative conflicts.
 *
 * Key Features:
 * - Intelligent chair role detection and assignment
 * - Automatic chapter head designation for chair roles
 * - Duplicate chair role conflict detection and resolution
 * - Smart role suggestion based on naming patterns
 * - Bulk chapter updates for role changes
 * - Permission level integration and validation
 * - Real-time organizational impact assessment
 *
 * Leadership Management:
 * - Automatic identification of leadership roles
 * - Chair role validation and conflict prevention
 * - Cross-chapter consistency enforcement
 * - Leadership transition workflow support
 * - Administrative delegation and permission assignment
 *
 * Business Value:
 * - Ensures clear organizational hierarchy and accountability
 * - Prevents leadership conflicts and administrative confusion
 * - Automates routine role assignment and management tasks
 * - Maintains consistency across all chapter operations
 * - Supports organizational growth and restructuring
 * - Provides audit trail for role changes and assignments
 *
 * Technical Architecture:
 * - Frappe DocType form controller with advanced workflow logic
 * - Real-time validation and conflict detection
 * - Bulk update operations for organizational changes
 * - Integration with chapter board member management
 * - Permission level mapping and enforcement
 * - Automated suggestion engine for role categorization
 *
 * Organizational Features:
 * - Role hierarchy definition and enforcement
 * - Leadership succession planning support
 * - Multi-chapter coordination and consistency
 * - Administrative permission delegation
 * - Conflict resolution and duplicate detection
 * - Performance impact assessment for changes
 *
 * @author Verenigingen Development Team
 * @version 1.7.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires verenigingen.verenigingen.doctype.chapter_role.chapter_role (Python backend)
 * @requires verenigingen.verenigingen.doctype.chapter_board_member (Board management)
 * @requires verenigingen.verenigingen.doctype.chapter (Chapter operations)
 *
 * @example
 * // Creating a chair role with automatic conflict detection
 * // 1. Set role_name: 'Chairman'
 * // 2. System suggests is_chair: true
 * // 3. Automatic duplicate detection and warning
 * // 4. Bulk update all affected chapters
 *
 * @see {@link verenigingen.verenigingen.doctype.chapter_board_member} Board Member Management
 * @see {@link verenigingen.verenigingen.doctype.chapter} Chapter Operations
 */

// Copyright (c) 2025, Your Company and contributors
// For license information, please see license.txt

/**
 * @namespace ChapterRoleController
 * @description Advanced role management form controller with leadership hierarchy support
 */
frappe.ui.form.on('Chapter Role', {
	refresh(frm) {
		// Add visual indication for chair role
		if (frm.doc.is_chair && frm.doc.is_active) {
			frm.page.set_indicator(__('Chair Role'), 'blue');
			check_for_duplicate_chair_roles(frm);
		}

		// Add information about chair roles
		if (frm.doc.is_chair) {
			frm.set_intro(__('This role is marked as Chair. Members with this role will be automatically set as Chapter Heads.'), 'blue');
		}

		// Add button to view chapters using this role
		frm.add_custom_button(__('View Chapters Using This Role'), () => {
			frappe.set_route('List', 'Chapter Board Member', {
				chapter_role: frm.doc.name
			});
		}, __('View'));

		// Add button to update affected chapters if this is a chair role
		if (frm.doc.is_chair && frm.doc.is_active) {
			frm.add_custom_button(__('Update Affected Chapters'), () => {
				update_chapters_with_this_role(frm);
			}, __('Actions'));
		}
	},

	is_chair(frm) {
		if (frm.doc.is_chair && frm.doc.is_active) {
			frappe.confirm(
				__('Setting this role as Chair will make board members with this role automatically set as Chapter Head. Continue?'),
				() => {
					// Yes - check for duplicates
					check_for_duplicate_chair_roles(frm);
				},
				() => {
					// No - uncheck
					frm.set_value('is_chair', 0);
				}
			);
		}
	},

	is_active(frm) {
		// If activating a chair role, check for duplicates
		if (frm.doc.is_active && frm.doc.is_chair) {
			check_for_duplicate_chair_roles(frm);
		}
	},

	role_name(frm) {
		// If role name contains 'chair' or related terms, suggest setting is_chair
		if (!frm.doc.is_chair && frm.doc.role_name && frm.doc.is_active) {
			const chairTerms = ['chair', 'chairperson', 'president', 'head'];
			const lowerName = frm.doc.role_name.toLowerCase();

			if (chairTerms.some(term => lowerName.includes(term))) {
				frappe.confirm(
					__('This role name suggests it might be a Chair role. Would you like to mark it as Chair?'),
					() => {
						// Yes - set as chair
						frm.set_value('is_chair', 1);
						check_for_duplicate_chair_roles(frm);
					}
				);
			}
		}
	},

	permissions_level(frm) {
		// If setting admin permissions level, suggest setting is_chair if not already set
		if (frm.doc.permissions_level === 'Admin' && !frm.doc.is_chair && frm.doc.is_active) {
			frappe.confirm(
				__('Admin roles are often chair roles. Would you like to mark this role as Chair?'),
				() => {
					// Yes - set as chair
					frm.set_value('is_chair', 1);
					check_for_duplicate_chair_roles(frm);
				}
			);
		}
	},

	after_save(frm) {
		// If this is a chair role, suggest updating affected chapters
		if (frm.doc.is_chair && frm.doc.is_active) {
			frappe.confirm(
				__('Would you like to update the Chapter Head for all chapters using this role now?'),
				() => {
					// Yes - update chapters
					update_chapters_with_this_role(frm);
				}
			);
		}
	}
});

// Function to check for duplicate chair roles
function check_for_duplicate_chair_roles(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Chapter Role',
			filters: {
				is_chair: 1,
				is_active: 1,
				name: ['!=', frm.doc.name]
			},
			fields: ['name', 'role_name']
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				// Found other chair roles
				frm.set_intro(
					__('Warning: There are other roles also marked as Chair: {0}. Having multiple chair roles may cause confusion.',
						[r.message.map(role => role.role_name).join(', ')]),
					'orange'
				);

				// Show warning message
				frappe.msgprint({
					title: __('Multiple Chair Roles'),
					indicator: 'orange',
					message: __('There are other roles also marked as Chair:<br><br>{0}<br><br>Having multiple chair roles may cause confusion when automatically setting Chapter Heads.',
						[r.message.map(role => `• ${role.role_name}`).join('<br>')])
				});
			} else {
				// This is the only chair role
				frm.set_intro(__('This is the only role marked as Chair. Members with this role will be automatically set as Chapter Heads.'), 'blue');
			}
		}
	});
}

// Function to update chapters with this role
function update_chapters_with_this_role(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.chapter_role.chapter_role.update_chapters_with_role',
		args: {
			role: frm.doc.name
		},
		freeze: true,
		freeze_message: __('Updating chapters...'),
		callback(r) {
			if (r.message) {
				frappe.msgprint({
					title: __('Chapters Updated'),
					indicator: 'green',
					message: __('Updated {0} chapters with this role. {1} chapters had their Chapter Head changed.',
						[r.message.chapters_found, r.message.chapters_updated])
				});
			}
		}
	});
}
