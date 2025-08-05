/**
 * @fileoverview Brand Settings DocType Controller for Verenigingen Association Management
 *
 * This controller manages brand settings and theming configuration for the association,
 * including integration with the Owl Theme system for consistent visual branding
 * across the platform.
 *
 * @description Business Context:
 * Brand Settings allows associations to customize their visual identity including:
 * - Primary, secondary, and accent colors
 * - Background color schemes
 * - Theme integration with external systems
 * - Real-time color preview functionality
 * - CSS regeneration for theme changes
 *
 * @description Key Features:
 * - Owl Theme integration for consistent theming
 * - Real-time color preview with visual feedback
 * - Automatic CSS regeneration and deployment
 * - Theme status monitoring and validation
 * - Color scheme management with live preview
 *
 * @description Integration Points:
 * - Owl Theme system for external theme management
 * - CSS compilation and deployment pipeline
 * - Brand identity validation and consistency checks
 * - Theme settings persistence and synchronization
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires frappe.ui.form
 * @requires jQuery
 *
 * @example
 * // The controller automatically handles form events:
 * // - refresh: Adds theme integration buttons and color preview
 * // - is_active: Manages button visibility based on status
 * // - Color field changes: Updates live preview automatically
 */

// Copyright (c) 2025, Verenigingen and contributors
// For license information, please see license.txt

frappe.ui.form.on('Brand Settings', {
	refresh(frm) {
		// Add Owl Theme integration buttons
		if (frm.doc.is_active) {
			frm.add_custom_button(__('Sync to Owl Theme'), () => {
				sync_to_owl_theme(frm);
			}, __('Owl Theme'));

			frm.add_custom_button(__('Check Owl Theme Status'), () => {
				check_owl_theme_status(frm);
			}, __('Owl Theme'));

			frm.add_custom_button(__('Force Rebuild CSS'), () => {
				force_rebuild_css(frm);
			}, __('Debug'));
		}

		// Add color preview
		if (frm.doc.name) {
			add_color_preview(frm);
		}
	},

	is_active(frm) {
		// Refresh form when active status changes to show/hide buttons
		if (frm.doc.is_active) {
			frm.refresh();
		}
	},

	// Auto-preview color changes
	primary_color(frm) { update_color_preview(frm); },
	secondary_color(frm) { update_color_preview(frm); },
	accent_color(frm) { update_color_preview(frm); },
	background_primary_color(frm) { update_color_preview(frm); },
	background_secondary_color(frm) { update_color_preview(frm); }
});

/**
 * Synchronizes Brand Settings to Owl Theme System
 *
 * Transfers the current brand settings configuration to the Owl Theme system,
 * enabling consistent theming across all platform components and external integrations.
 *
 * @description Business Logic:
 * - Validates current brand settings completeness
 * - Transfers color scheme and theme configuration to Owl Theme
 * - Triggers CSS regeneration for immediate visual updates
 * - Provides user feedback on synchronization status
 *
 * @description Integration Details:
 * - Calls backend method for theme synchronization
 * - Handles success/error states with appropriate user messaging
 * - Ensures theme consistency across system components
 *
 * @param {Object} frm - Frappe form instance containing brand settings
 *
 * @example
 * // Called when user clicks "Sync to Owl Theme" button
 * sync_to_owl_theme(frm);
 * // Results in theme synchronization and user notification
 *
 * @see {@link check_owl_theme_status} For checking integration status
 * @see {@link force_rebuild_css} For manual CSS regeneration
 */
function sync_to_owl_theme(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.sync_brand_settings_to_owl_theme',
		callback(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __('Success'),
					message: r.message.message,
					indicator: 'green'
				});
			} else {
				frappe.msgprint({
					title: __('Error'),
					message: r.message ? r.message.message : 'Unknown error occurred',
					indicator: 'red'
				});
			}
		}
	});
}

/**
 * Checks Owl Theme Integration Status
 *
 * Retrieves and displays comprehensive status information about the Owl Theme
 * integration, including installation status, configuration validity, and
 * current synchronization state.
 *
 * @description Diagnostic Information:
 * - Owl Theme installation verification
 * - Theme settings configuration status
 * - Active brand settings identification
 * - Integration error detection and reporting
 *
 * @description User Experience:
 * - Formatted status dialog with detailed information
 * - Color-coded indicators for quick status assessment
 * - Error highlighting for troubleshooting guidance
 *
 * @param {Object} frm - Frappe form instance for context
 *
 * @example
 * // Called when user clicks "Check Owl Theme Status" button
 * check_owl_theme_status(frm);
 * // Displays comprehensive integration status dialog
 *
 * @see {@link sync_to_owl_theme} For synchronization functionality
 */
function check_owl_theme_status(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.check_owl_theme_integration',
		callback(r) {
			if (r.message) {
				const status = r.message;
				const message = `
					<div style="font-size: 14px;">
						<p><strong>Owl Theme Installed:</strong> ${status.installed ? 'Yes' : 'No'}</p>
						${status.installed ? `
							<p><strong>Settings Exist:</strong> ${status.owl_settings_exists ? 'Yes' : 'No'}</p>
							<p><strong>Active Brand Settings:</strong> ${status.active_brand_settings ? status.active_brand_settings.settings_name : 'None'}</p>
						` : ''}
						<p><strong>Status:</strong> ${status.message}</p>
						${status.error ? `<p style="color: red;"><strong>Error:</strong> ${status.error}</p>` : ''}
					</div>
				`;

				frappe.msgprint({
					title: __('Owl Theme Integration Status'),
					message,
					indicator: status.installed ? 'blue' : 'orange'
				});
			}
		}
	});
}

/**
 * Adds Interactive Color Preview Section
 *
 * Creates a visual color preview section in the form that displays
 * the current color scheme configuration with real-time updates
 * as users modify color values.
 *
 * @description Visual Components:
 * - Primary, secondary, and accent color swatches
 * - Responsive layout with proper spacing
 * - Labeled color samples for easy identification
 * - Styled container with consistent visual design
 *
 * @description User Experience:
 * - Immediate visual feedback for color changes
 * - Clear labeling of each color purpose
 * - Professional presentation of color scheme
 * - Prevention of duplicate preview sections
 *
 * @param {Object} frm - Frappe form instance to attach preview to
 *
 * @example
 * // Called during form refresh to add color preview
 * add_color_preview(frm);
 * // Creates visual color swatches in the form layout
 *
 * @see {@link update_color_preview} For updating preview colors
 */
function add_color_preview(frm) {
	// Add a color preview section
	if (!frm.fields_dict.color_preview) {
		const preview_html = `
			<div id="brand-color-preview" style="margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 8px;">
				<h4>Color Preview</h4>
				<div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px;">
					<div class="color-sample" data-field="primary_color">
						<div class="color-box" style="width: 60px; height: 40px; border-radius: 4px; border: 1px solid #ccc;"></div>
						<small style="display: block; text-align: center; margin-top: 5px;">Primary</small>
					</div>
					<div class="color-sample" data-field="secondary_color">
						<div class="color-box" style="width: 60px; height: 40px; border-radius: 4px; border: 1px solid #ccc;"></div>
						<small style="display: block; text-align: center; margin-top: 5px;">Secondary</small>
					</div>
					<div class="color-sample" data-field="accent_color">
						<div class="color-box" style="width: 60px; height: 40px; border-radius: 4px; border: 1px solid #ccc;"></div>
						<small style="display: block; text-align: center; margin-top: 5px;">Accent</small>
					</div>
				</div>
			</div>
		`;

		$(frm.layout.wrapper).find('.form-layout').append(preview_html);
		update_color_preview(frm);
	}
}

/**
 * Updates Color Preview Display
 *
 * Synchronizes the visual color preview swatches with the current
 * form values, providing real-time visual feedback as users
 * modify color field values.
 *
 * @description Update Process:
 * - Iterates through all color sample elements
 * - Retrieves current color values from form data
 * - Applies colors to corresponding preview boxes
 * - Uses delayed execution to ensure DOM readiness
 *
 * @description Performance Considerations:
 * - Minimal 100ms timeout for DOM stability
 * - Efficient jQuery selectors for fast updates
 * - Only updates colors that have valid values
 *
 * @param {Object} frm - Frappe form instance containing current color values
 *
 * @example
 * // Called automatically when color fields change
 * update_color_preview(frm);
 * // Updates visual preview to match current form values
 *
 * @see {@link add_color_preview} For initial preview creation
 */
function update_color_preview(frm) {
	// Update color preview boxes
	setTimeout(() => {
		$('#brand-color-preview .color-sample').each(function () {
			const field = $(this).data('field');
			const color = frm.doc[field];
			if (color) {
				$(this).find('.color-box').css('background-color', color);
			}
		});
	}, 100);
}

/**
 * Forces CSS Rebuild and Deployment
 *
 * Triggers an immediate regeneration of the CSS files based on current
 * brand settings, bypassing normal caching mechanisms for debugging
 * and troubleshooting theme-related issues.
 *
 * @description Rebuild Process:
 * - Compiles current brand settings into CSS variables
 * - Generates complete theme stylesheet
 * - Deploys updated CSS to application
 * - Reports compilation statistics and status
 *
 * @description Debug Capabilities:
 * - Bypasses CSS caching for immediate updates
 * - Provides detailed compilation feedback
 * - Reports CSS file size for performance monitoring
 * - Handles compilation errors with detailed messaging
 *
 * @description Use Cases:
 * - Debugging theme compilation issues
 * - Immediate CSS deployment after settings changes
 * - Performance testing of theme compilation
 * - Troubleshooting visual inconsistencies
 *
 * @param {Object} frm - Frappe form instance for context
 *
 * @example
 * // Called when user clicks "Force Rebuild CSS" debug button
 * force_rebuild_css(frm);
 * // Triggers immediate CSS regeneration with detailed feedback
 *
 * @see {@link sync_to_owl_theme} For standard theme synchronization
 */
function force_rebuild_css(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.brand_settings.brand_settings.force_rebuild_css',
		callback(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __('Success'),
					message: `${r.message.message}<br><small>CSS length: ${r.message.css_length} characters</small>`,
					indicator: 'green'
				});
			} else {
				frappe.msgprint({
					title: __('Error'),
					message: r.message ? r.message.message : 'Unknown error occurred',
					indicator: 'red'
				});
			}
		}
	});
}
