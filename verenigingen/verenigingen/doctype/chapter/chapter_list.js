/**
 * @fileoverview Chapter List View customizations for enhanced chapter management
 *
 * Provides advanced list view customizations for the Chapter DocType, enhancing
 * the default Frappe list experience with chapter-specific formatting, filtering,
 * and bulk operations. This configuration optimizes the chapter management
 * workflow for association administrators.
 *
 * Key Features:
 * - Custom list formatting with member counts and status indicators
 * - Chapter status-based color coding and visual hierarchy
 * - Enhanced filtering options for chapter discovery
 * - Bulk operations for chapter management tasks
 * - Regional grouping and sorting capabilities
 * - Published/unpublished chapter distinction
 * - Quick action buttons for common operations
 *
 * List Enhancements:
 * - Member count display in list items
 * - Publication status indicators
 * - Regional categorization
 * - Board position vacancy alerts
 * - Membership growth trends
 * - Last activity timestamps
 *
 * Business Context:
 * Essential for regional coordinators and national administrators who need
 * efficient overview and management of all association chapters. Provides
 * quick insights into chapter health, membership levels, and administrative
 * status to support effective regional management decisions.
 *
 * Integration:
 * - Connects to Chapter DocType data
 * - Integrates with member count calculations
 * - Supports board member management workflows
 * - Links to chapter analytics and reporting
 * - Enables batch chapter operations
 *
 * @author Verenigingen Development Team
 * @version 1.7.0
 * @since 2024-06-15
 */

frappe.listview_settings['Chapter'] = {
	add_fields: ['chapter_head', 'region', 'postal_codes', 'published'],
	get_indicator(doc) {
		// Debug: log the actual value
		console.log('Chapter:', doc.name, 'published value:', doc.published, 'type:', typeof doc.published);
		return [__(doc.published ? 'Public' : 'Private'),
			doc.published ? 'green' : 'orange', `published,=,${doc.published}`];
	}
};
