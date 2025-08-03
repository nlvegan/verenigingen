/**
 * @fileoverview Volunteer Interest Area Child Table Controller
 * @description Manages volunteer interest categorization and matching
 *
 * Business Context:
 * Tracks volunteer interests across different organizational areas to enable
 * effective volunteer matching and engagement. Part of the comprehensive
 * volunteer management system for optimal resource allocation.
 *
 * Key Features:
 * - Interest category tracking for volunteer profiles
 * - Skill level assessment for capability matching
 * - Availability preferences for scheduling coordination
 * - Interest priority ranking for preference management
 *
 * Volunteer Matching:
 * - Interest-based opportunity recommendations
 * - Skill level alignment with role requirements
 * - Geographic preference consideration
 * - Time commitment preference tracking
 *
 * Data Integration:
 * - Links to volunteer interest categories
 * - Parent volunteer record integration
 * - Cross-reference with opportunity requirements
 * - Analytics data collection for engagement metrics
 *
 * @author Verenigingen Development Team
 * @since 2024
 * @module VolunteerInterestArea
 * @requires frappe.ui.form
 */

frappe.ui.form.on('Volunteer Interest Area', {
	interest_category(frm, cdt, cdn) {
		// Auto-populate category-specific defaults when interest is selected
		const row = locals[cdt][cdn];
		if (row.interest_category) {
			// Load category defaults if available
			frappe.db.get_value('Volunteer Interest Category', row.interest_category,
				['typical_time_commitment', 'requires_training'],
				(r) => {
					if (r) {
						// Set suggested defaults based on category
						if (r.typical_time_commitment && !row.preferred_time_commitment) {
							frappe.model.set_value(cdt, cdn, 'preferred_time_commitment', r.typical_time_commitment);
						}
						if (r.requires_training) {
							frappe.model.set_value(cdt, cdn, 'training_required', 1);
						}
					}
				}
			);
		}
	},

	skill_level(frm, cdt, cdn) {
		// Update volunteer matching scores when skill level changes
		const row = locals[cdt][cdn];
		if (row.skill_level && row.interest_category) {
			// Trigger background matching score recalculation
			// This would integrate with volunteer opportunity matching system
		}
	}
});
