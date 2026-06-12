/**
 * @fileoverview IBAN Masking Utility for Verenigingen Association Management
 *
 * This utility masks IBANs in the UI for privacy/security while keeping
 * them visible to authorized users (Accounts Manager and System Manager).
 *
 * @description Business Context:
 * IBANs are sensitive financial data that should not be displayed to all users.
 * Non-privileged users see masked IBANs (e.g., "NL91****4300") while
 * Accounts Managers can see the full IBAN for administrative purposes.
 *
 * @description Key Features:
 * - Role-based IBAN visibility control
 * - Automatic masking on form load
 * - Original value preservation for form submission
 * - Auto-setup for SEPA Mandate and Member forms
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API
 *
 * @example
 * // Manual usage in custom forms:
 * frappe.ui.form.on('Custom DocType', {
 *   refresh: function(frm) {
 *     verenigingen.iban.applyMasking(frm, 'iban_field');
 *   },
 *   before_save: function(frm) {
 *     verenigingen.iban.restoreOriginal(frm, 'iban_field');
 *   }
 * });
 */

frappe.provide('verenigingen.iban');

/**
 * IBAN Masking Utility Object
 *
 * Provides IBAN masking functionality with role-based access control.
 */
verenigingen.iban = {
	/**
	 * Mask an IBAN, showing only first 4 and last 4 characters.
	 *
	 * @description Masking Format:
	 * Takes an IBAN like "NL91ABNA0417164300" and returns "NL91****4300".
	 * The first 4 characters (country code + check digits) and last 4
	 * characters are visible, with asterisks in between.
	 *
	 * @param {string} iban - The IBAN to mask
	 * @returns {string} Masked IBAN or original if too short
	 *
	 * @example
	 * verenigingen.iban.mask('NL91ABNA0417164300');
	 * // Returns: 'NL91****4300'
	 *
	 * @example
	 * verenigingen.iban.mask('NL91 ABNA 0417 1643 00');
	 * // Returns: 'NL91****4300' (spaces removed first)
	 */
	mask(iban) {
		if (!iban || iban.length < 8) {
			return iban;
		}
		// Remove spaces for consistent masking
		const cleanIban = iban.replace(/\s/g, '');
		const first = cleanIban.substring(0, 4);
		const last = cleanIban.substring(cleanIban.length - 4);
		return `${first}****${last}`;
	},

	/**
	 * Check if current user can see unmasked IBANs.
	 *
	 * @description Authorization Check:
	 * Returns true for users with Accounts Manager or System Manager roles.
	 * These roles are considered authorized to view full banking details
	 * for administrative and financial management purposes.
	 *
	 * @returns {boolean} True if user can view full IBAN
	 *
	 * @example
	 * if (verenigingen.iban.canViewFull()) {
	 *   // Show full IBAN
	 * } else {
	 *   // Show masked IBAN
	 * }
	 */
	canViewFull() {
		return frappe.user_roles.includes('Accounts Manager') || frappe.user_roles.includes('System Manager');
	},

	/**
	 * Apply masking to an IBAN field based on user role.
	 *
	 * @description Masking Behavior:
	 * For non-privileged users:
	 * - Stores the original IBAN value for form submission
	 * - Replaces the displayed value with a masked version
	 * - Makes the field read-only to prevent editing masked value
	 *
	 * For privileged users (Accounts Manager, System Manager):
	 * - No changes made, full IBAN remains visible and editable
	 *
	 * @param {Object} frm - Frappe Form object
	 * @param {string} fieldname - Name of the IBAN field to mask
	 *
	 * @example
	 * frappe.ui.form.on('SEPA Mandate', {
	 *   refresh: function(frm) {
	 *     verenigingen.iban.applyMasking(frm, 'iban');
	 *   }
	 * });
	 */
	applyMasking(frm, fieldname) {
		if (!verenigingen.iban.canViewFull()) {
			const value = frm.doc[fieldname];
			if (value) {
				// Store original for form submission
				frm._original_iban = frm._original_iban || {};
				frm._original_iban[fieldname] = value;

				// Set display value to masked version (without triggering dirty)
				frm.doc[fieldname] = verenigingen.iban.mask(value);
				frm.refresh_field(fieldname);

				// Make field read-only for masked users
				frm.set_df_property(fieldname, 'read_only', 1);
			}
		}
	},

	/**
	 * Restore original IBAN before save.
	 *
	 * @description Restore Behavior:
	 * Call this in before_save to ensure the correct (unmasked) value
	 * is submitted to the server. This prevents saving masked values
	 * to the database.
	 *
	 * @param {Object} frm - Frappe Form object
	 * @param {string} fieldname - Name of the IBAN field to restore
	 *
	 * @example
	 * frappe.ui.form.on('SEPA Mandate', {
	 *   before_save: function(frm) {
	 *     verenigingen.iban.restoreOriginal(frm, 'iban');
	 *   }
	 * });
	 */
	restoreOriginal(frm, fieldname) {
		if (frm._original_iban && frm._original_iban[fieldname]) {
			frm.doc[fieldname] = frm._original_iban[fieldname];
		}
	},

	/**
	 * Auto-setup masking for common DocTypes.
	 *
	 * @description Auto-Configuration:
	 * Automatically registers form event handlers for SEPA Mandate
	 * and Member DocTypes to apply IBAN masking on form load and
	 * restore original values before save.
	 *
	 * This is called on page load to ensure masking is always active.
	 *
	 * @private
	 */
	setup() {
		// Auto-apply to SEPA Mandate forms
		frappe.ui.form.on('SEPA Mandate', {
			refresh(frm) {
				verenigingen.iban.applyMasking(frm, 'iban');
			},
			before_save(frm) {
				verenigingen.iban.restoreOriginal(frm, 'iban');
			}
		});

		// Auto-apply to Member forms if they have IBAN field
		frappe.ui.form.on('Member', {
			refresh(frm) {
				if (frm.fields_dict.iban) {
					verenigingen.iban.applyMasking(frm, 'iban');
				}
			},
			before_save(frm) {
				if (frm.fields_dict.iban) {
					verenigingen.iban.restoreOriginal(frm, 'iban');
				}
			}
		});
	}
};

// Initialize on ready
$(document).ready(() => {
	verenigingen.iban.setup();
});
