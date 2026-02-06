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
			options: ['', 'Occasional', 'Monthly', 'Weekly', 'Project-based']
		},
		{
			fieldname: 'experience_level',
			label: __('Experience Level'),
			fieldtype: 'Select',
			options: ['', 'Beginner', 'Intermediate', 'Experienced', 'Expert']
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
	]
};
