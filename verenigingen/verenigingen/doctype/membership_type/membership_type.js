/**
 * @fileoverview Membership Type DocType Controller - Membership Category Management and Configuration
 *
 * This module provides comprehensive management capabilities for membership types and categories,
 * including billing configuration, dues schedule integration, auto-renewal settings, and
 * administrative controls. Supports flexible membership structures with customizable billing
 * periods and automated template generation for streamlined membership administration.
 *
 * Key Features:
 * - Automated dues schedule template creation and integration
 * - Flexible billing period configuration (monthly, quarterly, yearly, custom)
 * - Default membership type designation with conflict resolution
 * - Auto-renewal capability management
 * - Membership navigation and reporting integration
 * - Real-time validation and business rule enforcement
 *
 * Business Value:
 * - Streamlined membership category administration
 * - Automated billing schedule creation reduces manual setup
 * - Flexible billing options accommodate diverse member preferences
 * - Default type management ensures consistent member onboarding
 * - Integrated navigation improves administrative efficiency
 * - Business rule validation prevents configuration conflicts
 *
 * Technical Architecture:
 * - Frappe DocType form controller with event-driven triggers
 * - Integration with Membership Dues Schedule doctype
 * - Real-time field validation and conditional display logic
 * - Backend API integration for template generation
 * - Cross-reference navigation to related documents
 *
 * Administrative Features:
 * - Dues schedule template auto-generation
 * - Membership listing filtered by type
 * - Billing period validation and field management
 * - Default type conflict detection and resolution
 * - Auto-renewal requirement enforcement
 *
 * @author Verenigingen Development Team
 * @version 1.8.0
 * @since 1.0.0
 *
 * @requires frappe
 * @requires verenigingen.verenigingen.doctype.membership_type.membership_type (Python backend)
 * @requires verenigingen.verenigingen.doctype.membership_dues_schedule
 * @requires verenigingen.verenigingen.doctype.membership
 *
 * @example
 * // Configure standard annual membership
 * // Set billing_period: 'Yearly'
 * // Enable allow_auto_renewal: true
 * // Set default_for_new_members: true (will handle conflicts automatically)
 *
 * @see {@link verenigingen.verenigingen.doctype.membership_dues_schedule} Dues Schedule Integration
 * @see {@link verenigingen.verenigingen.doctype.membership} Member Assignments
 */

/**
 * @namespace MembershipTypeController
 * @description Form controller for Membership Type DocType with comprehensive management features
 */
frappe.ui.form.on('Membership Type', {
	/**
	 * @method refresh
	 * @description Initializes form interface with context-sensitive buttons and navigation
	 *
	 * Sets up the membership type form interface with intelligent button placement
	 * based on current configuration state. Provides direct access to related
	 * documents and administrative functions for streamlined workflow management.
	 *
	 * Interface Elements:
	 * - Dues schedule template creation/viewing (context-dependent)
	 * - Related memberships navigation and filtering
	 * - Administrative action buttons grouped logically
	 *
	 * @param {Object} frm - Frappe form object with document data and methods
	 * @since 1.0.0
	 */
	refresh: function(frm) {
		// Add button to create dues schedule template
		if (!frm.doc.dues_schedule_template) {
			frm.add_custom_button(__('Create Dues Schedule Template'), function() {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.membership_type.membership_type.create_dues_schedule_template',
					args: {
						'membership_type_name': frm.doc.name
					},
					callback: function(r) {
						if (r.message) {
							frm.refresh();
						}
					}
				});
			}, __('Actions'));
		}

		// Add button to view linked dues schedule template
		if (frm.doc.dues_schedule_template) {
			frm.add_custom_button(__('Dues Schedule Template'), function() {
				frappe.set_route('Form', 'Membership Dues Schedule', frm.doc.dues_schedule_template);
			}, __('View'));
		}

		// Add button to view memberships of this type
		frm.add_custom_button(__('Memberships'), function() {
			frappe.set_route('List', 'Membership', {'membership_type': frm.doc.name});
		}, __('View'));
	},

	/**
	 * @method billing_period
	 * @description Manages billing period configuration with conditional field visibility
	 *
	 * Handles dynamic form behavior for billing period settings, including
	 * conditional display and validation of custom billing period options.
	 * Ensures data integrity by clearing invalid custom values when switching
	 * to standard billing periods.
	 *
	 * Business Logic:
	 * - Standard periods: Monthly, Quarterly, Yearly (predefined intervals)
	 * - Custom period: User-defined billing interval in months
	 * - Field validation ensures custom period is specified when required
	 * - Automatic cleanup prevents orphaned custom values
	 *
	 * @param {Object} frm - Frappe form object
	 * @since 1.0.0
	 */
	billing_period: function(frm) {
		// Toggle custom period field
		frm.toggle_reqd('billing_period_in_months', frm.doc.billing_period === 'Custom');
		frm.toggle_display('billing_period_in_months', frm.doc.billing_period === 'Custom');

		// Clear the field if not custom
		if (frm.doc.billing_period !== 'Custom') {
			frm.set_value('billing_period_in_months', null);
		}
	},

	/**
	 * @method allow_auto_renewal
	 * @description Enforces business rule relationship between auto-renewal and default status
	 *
	 * Implements critical business logic ensuring that default membership types
	 * must support auto-renewal functionality. Prevents configuration conflicts
	 * that could disrupt member onboarding and retention processes.
	 *
	 * Business Rules:
	 * - Default membership types must allow auto-renewal
	 * - Disabling auto-renewal automatically removes default status
	 * - User notification explains the business requirement
	 * - Maintains data consistency across membership configurations
	 *
	 * @param {Object} frm - Frappe form object
	 * @since 1.2.0
	 */
	allow_auto_renewal: function(frm) {
		// If auto renewal is disabled, uncheck default for new members
		if (!frm.doc.allow_auto_renewal && frm.doc.default_for_new_members) {
			frm.set_value('default_for_new_members', 0);
			frappe.msgprint(__('Auto-renewal must be allowed for the default membership type'), __('Warning'));
		}
	},

	/**
	 * @method default_for_new_members
	 * @description Manages exclusive default membership type designation with conflict resolution
	 *
	 * Implements singleton pattern for default membership type designation,
	 * ensuring only one membership type can be marked as default at any time.
	 * Provides user-friendly conflict resolution through confirmation dialog
	 * with clear options for resolving conflicts.
	 *
	 * Conflict Resolution Process:
	 * 1. Detect existing default membership type
	 * 2. Present user with clear conflict resolution options
	 * 3. Transfer default status or revert current change
	 * 4. Maintain referential integrity throughout process
	 * 5. Refresh form to reflect final state
	 *
	 * Business Impact:
	 * - Ensures consistent member onboarding experience
	 * - Prevents configuration conflicts in automated processes
	 * - Provides clear administrative control over default behavior
	 *
	 * @param {Object} frm - Frappe form object
	 * @since 1.0.0
	 */
	default_for_new_members: function(frm) {
		// Only one membership type can be default
		if (frm.doc.default_for_new_members) {
			frappe.call({
				method: 'frappe.client.get_list',
				args: {
					doctype: 'Membership Type',
					filters: {
						'default_for_new_members': 1,
						'name': ['!=', frm.doc.name]
					},
					fields: ['name']
				},
				callback: function(r) {
					if (r.message && r.message.length) {
						frappe.confirm(
							__('"{0}" is already set as default membership type. Do you want to make this the default instead?', [r.message[0].name]),
							function() {
								// Yes - keep this as default
								frappe.call({
									method: 'frappe.client.set_value',
									args: {
										doctype: 'Membership Type',
										name: r.message[0].name,
										fieldname: 'default_for_new_members',
										value: 0
									},
									callback: function() {
										frm.refresh();
									}
								});
							},
							function() {
								// No - revert this change
								frm.set_value('default_for_new_members', 0);
								frm.refresh_field('default_for_new_members');
							}
						);
					}
				}
			});
		}
	}
});
