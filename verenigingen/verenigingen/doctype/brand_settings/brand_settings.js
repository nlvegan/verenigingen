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
		if (frm.doc.name && frm.doc.primary_color) {
			frm.add_custom_button(
				__('Sync to Owl Theme'),
				() => {
					sync_to_owl_theme(frm);
				},
				__('Owl Theme')
			);

			frm.add_custom_button(
				__('Check Owl Theme Status'),
				() => {
					check_owl_theme_status(frm);
				},
				__('Owl Theme')
			);

			frm.add_custom_button(
				__('Force Rebuild CSS'),
				() => {
					force_rebuild_css(frm);
				},
				__('Debug')
			);
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
	primary_color(frm) {
		update_color_preview(frm);
		suggest_button_text_color(frm, 'primary_color', 'primary_button_text_color');
	},
	secondary_color(frm) {
		update_color_preview(frm);
		suggest_button_text_color(frm, 'secondary_color', 'secondary_button_text_color');
	},
	accent_color(frm) {
		update_color_preview(frm);
		suggest_button_text_color(frm, 'accent_color', 'accent_button_text_color');
	},
	background_primary_color(frm) {
		update_color_preview(frm);
	},
	background_secondary_color(frm) {
		update_color_preview(frm);
	}
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
						${
							status.installed
								? `
							<p><strong>Settings Exist:</strong> ${status.owl_settings_exists ? 'Yes' : 'No'}</p>
							<p><strong>Active Brand Settings:</strong> ${status.active_brand_settings ? status.active_brand_settings.settings_name : 'None'}</p>
						`
								: ''
						}
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

/**
 * Suggests Button Text Color Based on WCAG Contrast Guidelines
 *
 * Automatically calculates and suggests an appropriate text color (white or black)
 * for buttons based on the background color to ensure WCAG 2.1 AA compliance
 * with a minimum contrast ratio of 4.5:1.
 *
 * @description Accessibility Standards:
 * - WCAG 2.1 AA compliance (4.5:1 minimum contrast ratio)
 * - Automatic selection between white (#ffffff) and black (#000000)
 * - Real-time calculation as user changes background colors
 * - Visual feedback with contrast ratio display
 *
 * @description Implementation:
 * - Converts hex colors to RGB for luminance calculation
 * - Uses W3C relative luminance formula
 * - Suggests white text for dark backgrounds, black for light backgrounds
 * - Updates field value automatically with user confirmation
 *
 * @param {Object} frm - Frappe form instance
 * @param {string} backgroundField - Name of the background color field
 * @param {string} textField - Name of the text color field to update
 *
 * @example
 * // Called when primary_color changes
 * suggest_button_text_color(frm, 'primary_color', 'primary_button_text_color');
 *
 * @see {@link calculate_contrast_ratio} For contrast calculation logic
 * @see {@link get_relative_luminance} For luminance calculation
 */
function suggest_button_text_color(frm, backgroundField, textField) {
	const backgroundColor = frm.doc[backgroundField];
	if (!backgroundColor) {
		return;
	}

	const suggestedColor = get_optimal_text_color(backgroundColor);
	const contrastRatio = calculate_contrast_ratio(backgroundColor, suggestedColor);

	// Only update if the suggested color is different from current
	if (frm.doc[textField] !== suggestedColor) {
		frappe.confirm(
			`For better accessibility, we recommend ${suggestedColor === '#ffffff' ? 'white' : 'black'} text on this background.<br>` +
				`<small>Contrast ratio: ${contrastRatio.toFixed(1)}:1 (${contrastRatio >= 4.5 ? 'WCAG AA compliant' : 'below WCAG AA standard'})</small><br><br>` +
				`Update the ${__(textField.replace(/_/g, ' '))} to ${suggestedColor}?`,
			() => {
				frm.set_value(textField, suggestedColor);
			},
			__('Accessibility Suggestion')
		);
	}
}

/**
 * Calculates Optimal Text Color for Accessibility
 *
 * Determines whether white or black text provides better contrast
 * against the given background color according to WCAG guidelines.
 *
 * @description Algorithm:
 * - Calculates relative luminance of background color
 * - Compares contrast ratios with white and black text
 * - Returns the color that provides higher contrast
 * - Ensures WCAG 2.1 AA compliance when possible
 *
 * @param {string} backgroundColor - Hex color code (e.g., '#ff0000')
 * @returns {string} Optimal text color ('#ffffff' or '#000000')
 *
 * @example
 * const textColor = get_optimal_text_color('#cf3131'); // Returns '#ffffff'
 * const textColor = get_optimal_text_color('#f8f9fa'); // Returns '#000000'
 */
function get_optimal_text_color(backgroundColor) {
	const whiteContrast = calculate_contrast_ratio(backgroundColor, '#ffffff');
	const blackContrast = calculate_contrast_ratio(backgroundColor, '#000000');

	return whiteContrast > blackContrast ? '#ffffff' : '#000000';
}

/**
 * Calculates WCAG 2.1 Contrast Ratio Between Two Colors
 *
 * Implements the official W3C contrast ratio calculation formula
 * for determining accessibility compliance between foreground and
 * background colors.
 *
 * @description WCAG Standards:
 * - Level AA: Minimum 4.5:1 for normal text
 * - Level AAA: Minimum 7:1 for normal text
 * - Level AA Large: Minimum 3:1 for large text (18pt+ or 14pt+ bold)
 *
 * @description Formula:
 * - (L1 + 0.05) / (L2 + 0.05) where L1 is lighter, L2 is darker
 * - L = relative luminance calculated per W3C specification
 * - Range: 1:1 (no contrast) to 21:1 (maximum contrast)
 *
 * @param {string} color1 - First color in hex format (#rrggbb)
 * @param {string} color2 - Second color in hex format (#rrggbb)
 * @returns {number} Contrast ratio (1-21)
 *
 * @example
 * const ratio = calculate_contrast_ratio('#ffffff', '#000000'); // Returns 21
 * const ratio = calculate_contrast_ratio('#cf3131', '#ffffff'); // Returns ~3.8
 */
function calculate_contrast_ratio(color1, color2) {
	const lum1 = get_relative_luminance(color1);
	const lum2 = get_relative_luminance(color2);

	const lightest = Math.max(lum1, lum2);
	const darkest = Math.min(lum1, lum2);

	return (lightest + 0.05) / (darkest + 0.05);
}

/**
 * Calculates Relative Luminance According to W3C Specification
 *
 * Implements the official W3C relative luminance formula used in
 * WCAG contrast calculations, converting sRGB color values to
 * their linear RGB equivalents and applying luminance coefficients.
 *
 * @description W3C Formula:
 * - L = 0.2126 * R + 0.7152 * G + 0.0722 * B
 * - RGB values are linearized: if <= 0.03928 then C/12.92, else ((C+0.055)/1.055)^2.4
 * - Input values are normalized to 0-1 range from 0-255
 *
 * @description Color Space:
 * - Input: sRGB hex color (#rrggbb)
 * - Output: Relative luminance (0-1, where 0 = black, 1 = white)
 * - Gamma correction applied for accurate perceptual luminance
 *
 * @param {string} hexColor - Hex color code (#rrggbb format)
 * @returns {number} Relative luminance value (0-1)
 *
 * @example
 * const luminance = get_relative_luminance('#ffffff'); // Returns 1.0
 * const luminance = get_relative_luminance('#000000'); // Returns 0.0
 * const luminance = get_relative_luminance('#cf3131'); // Returns ~0.127
 */
function get_relative_luminance(hexColor) {
	// Convert hex to RGB
	const hex = hexColor.replace('#', '');
	const r = parseInt(hex.substr(0, 2), 16) / 255;
	const g = parseInt(hex.substr(2, 2), 16) / 255;
	const b = parseInt(hex.substr(4, 2), 16) / 255;

	// Apply gamma correction
	const linearize = (c) => {
		return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
	};

	const rLin = linearize(r);
	const gLin = linearize(g);
	const bLin = linearize(b);

	// Calculate relative luminance using W3C coefficients
	return 0.2126 * rLin + 0.7152 * gLin + 0.0722 * bLin;
}
