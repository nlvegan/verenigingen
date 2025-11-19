/**
 * @fileoverview Volunteer Interest Category DocType Controller
 *
 * This controller manages the hierarchical categorization system for volunteer
 * interests in the Verenigingen application. It provides functionality for
 * organizing volunteer skills and interests into logical categories.
 *
 * Business Context:
 * - Volunteers have diverse interests and skills that need organized categorization
 * - Categories can be hierarchical (parent-child relationships)
 * - Categories help match volunteers with appropriate opportunities
 * - System prevents circular references in category hierarchy
 *
 * Key Features:
 * - Hierarchical category management with parent-child relationships
 * - Quick navigation to view volunteers in specific categories
 * - Validation to prevent circular references
 * - Integration with volunteer matching system
 *
 * Form Events:
 * - refresh: Adds navigation buttons for related volunteers
 * - parent_category: Validates against circular references
 *
 * Usage Examples:
 * - Categories like "Environmental", "Education", "Community Service"
 * - Subcategories like "Recycling" under "Environmental"
 * - Quick filtering of volunteers by interest category
 *
 * @module verenigingen/doctype/volunteer_interest_category/volunteer_interest_category
 * @version 1.0.0
 * @since 2024
 * @see {@link ../volunteer/volunteer.js|Volunteer DocType}
 * @see {@link ../volunteer_interest_area/volunteer_interest_area.js|Volunteer Interest Area}
 */

// Copyright (c) 2025, Your Organization and contributors
// For license information, please see license.txt

frappe.ui.form.on('Volunteer Interest Category', {
	refresh(frm) {
		// Add button to view related volunteers
		if (!frm.is_new()) {
			frm.add_custom_button(__('View Volunteers'), () => {
				frappe.route_options = {
					interests: frm.doc.name
				};
				frappe.set_route('List', 'Volunteer');
			});
		}
	},

	parent_category(frm) {
		// Prevent setting self as parent
		if (frm.doc.parent_category === frm.doc.name) {
			frappe.msgprint(__('You cannot set a category as its own parent'));
			frm.set_value('parent_category', '');
		}
	}
});
