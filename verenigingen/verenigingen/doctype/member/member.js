/**
 * @fileoverview Member DocType Frontend Controller for Verenigingen Association Management
 *
 * This is the comprehensive frontend controller for the Member DocType in the Verenigingen
 * association management system. It provides the complete administrative interface for
 * member management in the ERPNext backend, handling member lifecycle, payments,
 * SEPA mandates, chapter assignments, and volunteer coordination.
 *
 * @description Business Context:
 * Members are the core entity in the association management system. This controller handles:
 * - Member registration and profile management
 * - Payment method configuration and SEPA mandate integration
 * - Chapter assignment and geographical organization
 * - Volunteer profile creation and management
 * - Membership fee calculation and invoicing
 * - Suspension, termination, and status management
 * - Integration with Dutch banking (IBAN/BIC) and SEPA systems
 *
 * @description Architecture Integration:
 * - Integrates with modular JavaScript utilities for specific functionality
 * - Connects to Python backend for business logic and data validation
 * - Manages complex UI state for administrative workflows
 * - Handles real-time updates and form validation
 *
 * @description Key Features:
 * - Comprehensive member lifecycle management
 * - SEPA direct debit integration with mandate validation
 * - Chapter-based geographical organization
 * - Volunteer profile creation and management
 * - Fee management with override capabilities
 * - Dutch naming conventions support
 * - Administrative approval workflows
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13-001
 * @since 1.0.0
 *
 * @requires frappe - Frappe Framework client-side API
 * @requires payment-utils.js - Payment processing utilities
 * @requires chapter-utils.js - Chapter management utilities
 * @requires sepa-utils.js - SEPA banking integration utilities
 * @requires volunteer-utils.js - Volunteer management utilities
 * @requires termination-utils.js - Membership termination utilities
 * @requires ui-utils.js - User interface utilities
 *
 * @example
 * // This controller is automatically loaded when viewing Member DocType forms
 * // Access through Frappe's form events system:
 * frappe.ui.form.on('Member', {
 *   refresh: function(frm) {
 *     // Controller initialization and UI setup
 *   }
 * });
 */

// Copyright (c) 2025, Verenigingen Development Team and contributors
// For license information, please see license.txt
// Cache buster: v2025-01-13-001

// Import utility modules
frappe.require([
	'/assets/verenigingen/js/member/js_modules/payment-utils.js',
	'/assets/verenigingen/js/member/js_modules/chapter-utils.js',
	'/assets/verenigingen/js/member/js_modules/chapter-history-utils.js',
	'/assets/verenigingen/js/member/js_modules/sepa-utils.js',
	'/assets/verenigingen/js/member/js_modules/termination-utils.js',
	'/assets/verenigingen/js/member/js_modules/volunteer-utils.js',
	'/assets/verenigingen/js/member/js_modules/ui-utils.js'
]);

/**
 * Main Member DocType Form Controller
 *
 * Handles all form events and user interactions for the Member DocType.
 * This includes form lifecycle events, field change handlers, and
 * integration with backend services for comprehensive member management.
 */
frappe.ui.form.on('Member', {

	// ==================== FORM LIFECYCLE EVENTS ====================

	/**
	 * Form Refresh Event Handler
	 *
	 * Primary initialization function called when the Member form is displayed
	 * or refreshed. Orchestrates the setup of the entire user interface including
	 * action buttons, status displays, and integration with external services.
	 *
	 * @description Business Logic:
	 * - Initializes UI components and custom styling
	 * - Sets up administrative action buttons based on user permissions
	 * - Displays member status indicators (termination, suspension, amendments)
	 * - Configures SEPA mandate integration and banking information
	 * - Loads chapter assignment and volunteer information
	 * - Sets up payment history and dues schedule displays
	 *
	 * @description Performance Considerations:
	 * - Uses debounced API calls to prevent excessive server requests
	 * - Implements conditional loading based on user roles and permissions
	 * - Optimizes DOM manipulation with delayed execution for heavy operations
	 *
	 * @description Security Features:
	 * - Role-based access control for administrative functions
	 * - Validation of user permissions before displaying sensitive actions
	 * - Protection against unauthorized member data access
	 *
	 * @param {Object} frm - Frappe Form object containing member document and UI controls
	 * @param {Object} frm.doc - Current member document with all field values
	 * @param {boolean} frm.doc.__islocal - Flag indicating if document is unsaved/new
	 * @param {string} frm.doc.name - Unique identifier for the member record
	 * @param {Object} frm.doc.__onload - Server-side data preloaded for performance
	 *
	 * @example
	 * // Automatically called by Frappe when form loads:
	 * // refresh: function(frm) {
	 * //   // Form initialization logic
	 * // }
	 *
	 * @throws {Error} If required utility modules are not loaded
	 * @throws {ValidationError} If member document contains invalid data
	 *
	 * @see {@link setup_dutch_naming_fields} For Dutch naming convention setup
	 * @see {@link add_consolidated_action_buttons} For action button configuration
	 * @see {@link check_sepa_mandate_status_debounced} For SEPA integration
	 */
	refresh(frm) {
		// Skip API calls for new/unsaved documents
		if (frm.doc.__islocal || !frm.doc.name || frm.doc.name.startsWith('new-member-')) {
			// Only initialize basic UI for new documents
			if (window.UIUtils) {
				UIUtils.add_custom_css();
				UIUtils.setup_payment_history_grid(frm);
				UIUtils.setup_member_id_display(frm);
			}
			setup_dutch_naming_fields(frm);

			// Add basic buttons that don't require API calls
			add_basic_action_buttons(frm);
			return;
		}

		// Initialize UI and custom CSS
		if (window.UIUtils) {
			UIUtils.add_custom_css();
			UIUtils.setup_payment_history_grid(frm);
			UIUtils.setup_member_id_display(frm);
		}

		// Handle Dutch naming field visibility
		setup_dutch_naming_fields(frm);

		// Add custom User link button
		setup_user_link_button(frm);

		// Add custom Customer link button
		setup_customer_link_button(frm);

		// Add all action buttons with proper consolidation
		add_consolidated_action_buttons(frm);

		// Add all view buttons in consolidated menu
		add_consolidated_view_buttons(frm);


		// Display termination status
		display_termination_status(frm);

		// Auto-populate other_members_at_address field on form load
		// Check if data is already available from backend via onload
		if (frm.doc.primary_address && !frm.doc.__islocal) {
			setTimeout(() => {
				// First check if we have the HTML content from onload
				if (frm.doc.__onload && frm.doc.__onload.other_members_at_address) {
					// Found address members data in onload, using Frappe field API

					const html_content = frm.doc.__onload.other_members_at_address;

					// Try using Frappe's field API first
					if (frm.fields_dict && frm.fields_dict.other_members_at_address) {
						const field = frm.fields_dict.other_members_at_address;
						// console.log('Found field object:', field);

						if (field.df && field.df.fieldtype === 'HTML') {
							// For HTML fields, set content using the html method if available
							if (typeof field.html === 'function') {
								field.html(html_content);
								// console.log('Set content using field.html() method');
							} else if (field.$wrapper && field.$wrapper.length > 0) {
								// Use the wrapper to set content
								field.$wrapper.html(html_content);
								// console.log('Set content using field.$wrapper');
							} else if (field.$input && field.$input.length > 0) {
								// Some HTML fields use $input
								field.$input.html(html_content);
								// console.log('Set content using field.$input');
							}

							// Ensure field is visible
							if (typeof field.toggle === 'function') {
								field.toggle(true);
							}
						} else {
							// console.log('Field is not HTML type or missing df');
						}
					} else {
						// console.log('Field not found in fields_dict, trying DOM injection');
					}

					// Fallback to direct DOM manipulation
					const field_element = $('[data-fieldname="other_members_at_address"]');
					if (field_element.length > 0) {
						// console.log('Found field element in DOM');

						// For Frappe HTML fields, the content typically goes in a child div
						const frappe_control = field_element.find('.frappe-control').first();
						if (frappe_control.length > 0) {
							frappe_control.html(html_content);
							// console.log('Injected into .frappe-control');
						} else {
							// Try other selectors
							const containers = [
								'.control-value',
								'.control-html',
								'.form-control',
								'div[data-fieldtype="HTML"]',
								'div'
							];

							let injected = false;
							for (const selector of containers) {
								const container = field_element.find(selector).first();
								if (container.length > 0 && !container.hasClass('form-group')) {
									container.html(html_content);
									// console.log(`Injected into ${selector}`);
									injected = true;
									break;
								}
							}

							if (!injected) {
								console.error('Could not find suitable container');
							}
						}

						// Make sure field is visible
						field_element.show();
						field_element.css('display', 'block');
					}
				} else {
					// No onload data, check if field is empty and needs API call
					const field_element = $('[data-fieldname="other_members_at_address"]');
					const has_content = field_element.find('.control-value').html();

					if (field_element.length > 0 && (!has_content || has_content.trim() === '')) {
						// Call the update function to populate it
						if (window.update_other_members_at_address) {
							// console.log('No onload data, calling API to populate address members field');
							update_other_members_at_address(frm);
						}
					}
				}
			}, 1000); // Longer delay to ensure form is fully loaded
		}

		// Display amendment status
		display_amendment_status(frm);

		// Check if user has admin roles before calling admin functions
		const admin_roles = ['System Manager', 'Verenigingen Administrator', 'Verenigingen Manager', 'Verenigingen Staff'];
		const has_admin_role = frappe.user_roles.some(role => admin_roles.includes(role));

		// Display suspension status (only for admins or own record)
		if (has_admin_role || frm.doc.user === frappe.session.user) {
			display_suspension_status(frm);
		}

		// Add fee management functionality (only for admins)
		if (has_admin_role) {
			add_fee_management_buttons(frm);
		}

		// Ensure fee management section visibility
		ensure_fee_management_section_visibility(frm);

		// Also ensure visibility after a short delay (in case form is still loading)
		setTimeout(() => {
			ensure_fee_management_section_visibility(frm);
		}, 500);

		// Add administrative buttons for authorized users (only for admins)
		if (has_admin_role) {
			add_administrative_buttons(frm);
		}

		// Check SEPA mandate status (debounced to avoid multiple rapid calls)
		check_sepa_mandate_status_debounced(frm);

		// Show volunteer info if exists
		if (window.VolunteerUtils) {
			VolunteerUtils.show_volunteer_info(frm);
		}


		// Setup chapter membership history display and utilities (with delay for async loading)
		setTimeout(() => {
			if (window.ChapterHistoryUtils) {
				ChapterHistoryUtils.setup_chapter_history_display(frm);
				ChapterHistoryUtils.add_chapter_history_insights(frm);
			}
		}, 1000);

		// Load and display current dues schedule details
		load_dues_schedule_summary(frm);

		// Always update the address display for HTML fields (they don't persist)
		if (frm.doc.primary_address && window.update_other_members_at_address) {
			// Delay to ensure form is fully loaded and DOM is ready
			setTimeout(() => {
				// Check if we already have data from onload first
				if (frm.doc.__onload && frm.doc.__onload.other_members_at_address) {
					// Using onload data for address display refresh
					// Don't call API if we already have the data
				} else {
					// console.log('Refreshing address display on form refresh via API');
					update_other_members_at_address(frm);
				}
			}, 500);
		}

		// Setup Sales Invoice link filtering (consolidated - only once per refresh)
		if (frm.doc.customer && !frm.doc.__islocal) {
			setup_sales_invoice_link_filter(frm);
		}
	},

	onload(frm) {
		// Set up form behavior on load
		setup_form_behavior(frm);

		// Initialize IBAN tracking for change detection
		frm._previous_iban = frm.doc.iban;

		// Ensure fee management section visibility on load
		ensure_fee_management_section_visibility(frm);

		// Sales Invoice link filtering is handled in refresh() - no need to duplicate here
	},

	// ==================== FIELD EVENT HANDLERS ====================

	/**
	 * Full Name Field Change Handler
	 *
	 * Triggers automatic name synchronization when the full name is manually edited.
	 * Updates component fields (first, middle, last) when full name changes.
	 *
	 * @param {Object} frm - Form object containing member data
	 */
	full_name(frm) {
		// Auto-generate full name from component fields when individual fields change
		update_full_name_from_components(frm);
	},

	/**
	 * First Name Field Change Handler
	 *
	 * Updates the full name when first name component changes.
	 * Part of the automatic name composition system for member records.
	 *
	 * @param {Object} frm - Form object
	 */
	first_name(frm) {
		update_full_name_from_components(frm);
	},

	/**
	 * Middle Name Field Change Handler
	 *
	 * Updates the full name when middle name component changes.
	 * Supports Dutch naming conventions with multiple middle names.
	 *
	 * @param {Object} frm - Form object
	 */
	middle_name(frm) {
		update_full_name_from_components(frm);
	},

	/**
	 * Last Name Field Change Handler
	 *
	 * Updates the full name when last name component changes.
	 * Handles Dutch prefixes and compound surnames properly.
	 *
	 * @param {Object} frm - Form object
	 */
	last_name(frm) {
		update_full_name_from_components(frm);
	},

	/**
	 * Payment Method Field Change Handler
	 *
	 * Handles payment method changes and configures UI based on selected method.
	 * Triggers SEPA mandate validation for direct debit payments and manages
	 * banking field visibility and requirements.
	 *
	 * @description Business Logic:
	 * - Shows/hides banking fields based on payment method
	 * - Validates SEPA mandate requirements for direct debit
	 * - Updates payment-related UI components and indicators
	 * - Manages field requirements and validation rules
	 *
	 * @param {Object} frm - Form object with payment method configuration
	 */
	payment_method(frm) {
		if (window.UIUtils) {
			UIUtils.handle_payment_method_change(frm);
		}
		// Only update UI elements, don't prompt for mandate creation during field changes
		check_sepa_mandate_status_debounced(frm);
	},

	/**
	 * IBAN Field Change Handler
	 *
	 * Handles International Bank Account Number (IBAN) input and validation.
	 * Automatically derives BIC/SWIFT codes for supported banks and manages
	 * SEPA direct debit mandate validation for European banking integration.
	 *
	 * @description Banking Integration Features:
	 * - Automatic IBAN formatting and validation
	 * - BIC/SWIFT code derivation from IBAN bank codes
	 * - SEPA mandate status validation and updates
	 * - Real-time banking information validation
	 *
	 * @description Supported Banking Systems:
	 * - Dutch banks (ABN AMRO, ING, Rabobank, etc.)
	 * - European SEPA-compatible banks
	 * - International SWIFT network participants
	 *
	 * @description Business Logic:
	 * - Cleans and formats IBAN input to standard format
	 * - Validates IBAN structure and check digits
	 * - Automatically populates BIC when possible
	 * - Updates SEPA mandate status indicators
	 * - Triggers payment method validation
	 *
	 * @param {Object} frm - Form object with banking information
	 * @param {string} frm.doc.iban - IBAN string being validated
	 * @param {string} frm.doc.bic - BIC/SWIFT code (may be auto-populated)
	 *
	 * @example
	 * // User enters: "NL91 ABNA 0417 1643 00"
	 * // Result: iban = "NL91ABNA0417164300", bic = "ABNANL2A"
	 *
	 * @throws {ValidationError} If IBAN format is invalid
	 * @throws {APIError} If BIC derivation service is unavailable
	 *
	 * @see {@link derive_bic_from_iban} Backend method for BIC derivation
	 * @see {@link check_sepa_mandate_status_debounced} SEPA mandate validation
	 */
	iban(frm) {
		// Auto-derive BIC from IBAN if BIC is empty
		if (frm.doc.iban && !frm.doc.bic) {
			// Clean the IBAN first
			const cleanIban = frm.doc.iban.replace(/\s+/g, '').toUpperCase();

			// Only update IBAN if it actually changed (to prevent recursion)
			if (cleanIban !== frm.doc.iban) {
				frm.set_value('iban', cleanIban);
				return; // Exit and let the next trigger handle BIC derivation
			}

			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban',
				args: {
					iban: cleanIban
				},
				callback(r) {
					if (r.message && r.message.bic) {
						frm.set_value('bic', r.message.bic);
						frappe.show_alert({
							message: __('BIC/SWIFT code automatically derived: {0}', [r.message.bic]),
							indicator: 'blue'
						}, 3);
					} else if (cleanIban.length >= 4) {
						// Show message for unsupported bank/country
						frappe.show_alert({
							message: __('Could not automatically derive BIC for this IBAN. Please enter manually.'),
							indicator: 'orange'
						}, 4);
					}
				},
				error(r) {
					console.error('Error deriving BIC from IBAN:', r);
				}
			});
		}

		// Update UI elements to show current SEPA status
		// Mandate discrepancy checking is now handled by scheduled task
		check_sepa_mandate_status_debounced(frm);
	},

	pincode(frm) {
		// Simple notification when postal code changes
		if (frm.doc.pincode && !frm.doc.current_chapter_display) {
			frappe.show_alert({
				message: __('Postal code updated. You may want to assign a chapter based on this location.'),
				indicator: 'blue'
			}, 3);
		}
	},

	primary_address(frm) {
		// Update other members at address when primary address changes
		// Force refresh since address changed
		if (window.update_other_members_at_address) {
			update_other_members_at_address(frm, true);
		}
	},

	after_save(frm) {
		// SEPA mandate discrepancy checking is now handled by scheduled task
		// No real-time processing needed here

		// Still show basic UI updates after save
		if (frm.doc.payment_method === 'SEPA Direct Debit' && frm.doc.iban && !frm.doc.__islocal) {
			// Just update the UI to show current SEPA status
			check_sepa_mandate_status_debounced(frm);
		}
	}
});

// ==================== CUSTOM LINK FILTERING ====================

/**
 * Setup Sales Invoice Link Filtering
 *
 * Configures custom filtering for Sales Invoice links in the member form dashboard.
 * Ensures that when users click on Sales Invoice links from the member form,
 * they only see invoices related to this specific member's customer record.
 *
 * @description Business Context:
 * Members are linked to Customer records for invoicing purposes. This function
 * ensures that the Sales Invoice list view is automatically filtered to show
 * only invoices for the current member's associated customer, improving
 * user experience and data clarity.
 *
 * @description Implementation Details:
 * - Waits for dashboard to be fully loaded before applying filters
 * - Overrides default Sales Invoice link behavior
 * - Uses Frappe's route_options to apply customer filtering
 * - Handles both badge links and individual document links
 *
 * @description Performance Optimization:
 * - Implements retry logic for dashboard readiness
 * - Uses event delegation to avoid memory leaks
 * - Removes existing event handlers before adding new ones
 *
 * @param {Object} frm - Frappe Form object for member record
 * @param {string} frm.doc.customer - Customer ID linked to this member
 *
 * @example
 * // Called automatically from refresh event:
 * if (frm.doc.customer && !frm.doc.__islocal) {
 *   setup_sales_invoice_link_filter(frm);
 * }
 *
 * @throws {Error} If customer field is not populated
 *
 * @see {@link frappe.route_options} Frappe routing system
 * @see {@link frappe.set_route} Navigation control
 */
function setup_sales_invoice_link_filter(frm) {
	if (!frm.doc.customer) {
		return;
	}

	// Wait for dashboard to be ready and try multiple times if needed
	let attempts = 0;
	const maxAttempts = 5;

	function setupFilter() {
		attempts++;

		// Find the Sales Invoice connection link in the dashboard
		const sales_invoice_section = $('[data-doctype="Sales Invoice"]');

		if (sales_invoice_section.length === 0 && attempts < maxAttempts) {
			// Dashboard not ready yet, try again
			setTimeout(setupFilter, 500);
			return;
		}

		// Override the main "Sales Invoice" badge link
		const badge_links = sales_invoice_section.find('.badge-link');
		badge_links.off('click.member_custom_filter').on('click.member_custom_filter', (e) => {
			e.preventDefault();
			e.stopPropagation();

			// Set route options to filter by customer
			frappe.route_options = {
				customer: frm.doc.customer
			};

			// Navigate to Sales Invoice list with filter
			frappe.set_route('List', 'Sales Invoice');

			return false;
		});

		// Override individual invoice document links
		const document_links = sales_invoice_section.find('.document-link-item a');
		document_links.each(function () {
			const $link = $(this);
			const original_href = $link.attr('href');

			// If it's a form link, leave it as is (individual invoice)
			// If it's a list link, add the customer filter
			if (original_href && original_href.includes('#List/Sales Invoice')) {
				$link.off('click.member_custom_filter').on('click.member_custom_filter', (e) => {
					e.preventDefault();

					frappe.route_options = {
						customer: frm.doc.customer
					};

					frappe.set_route('List', 'Sales Invoice');
					return false;
				});
			}
		});

		// Also check for any other Sales Invoice links that might appear
		const other_links = $('a[href*="List/Sales Invoice"], a[href*="sales-invoice"]').filter(function () {
			return $(this).closest('.form-dashboard').length > 0;
		});

		other_links.off('click.member_custom_filter').on('click.member_custom_filter', function (e) {
			const href = $(this).attr('href');
			if (href && href.includes('List')) {
				e.preventDefault();

				frappe.route_options = {
					customer: frm.doc.customer
				};

				frappe.set_route('List', 'Sales Invoice');
				return false;
			}
		});
	}

	// Start the setup process
	setTimeout(setupFilter, 500);
}

// ==================== CHILD TABLE EVENT HANDLERS ====================

frappe.ui.form.on('Member Payment History', {
	payment_history_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.transaction_date) {
			frappe.model.set_value(cdt, cdn, 'transaction_date', frappe.datetime.get_today());
		}
	},

	amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.outstanding_amount) {
			frappe.model.set_value(cdt, cdn, 'outstanding_amount', row.amount || 0);
		}
	}
});

// ==================== CONSOLIDATED BUTTON SETUP FUNCTIONS ====================

function add_basic_action_buttons(frm) {
	// Only add buttons that don't require API calls for new documents
	frm.clear_custom_buttons();

	// Basic creation buttons that don't need saved document
	if (frm.doc.email && !frm.doc.user) {
		frm.add_custom_button(__('Create User Account'), () => {
			create_user_account_dialog(frm);
		}, __('Create'));
	}

	if (!frm.doc.customer) {
		frm.add_custom_button(__('Create Customer'), () => {
			frm.call({
				doc: frm.doc,
				method: 'create_customer',
				callback(r) {
					if (r.message) {
						frm.refresh();
					}
				}
			});
		}, __('Create'));
	}
}

function add_consolidated_action_buttons(frm) {
	// Clear existing custom buttons to avoid duplicates
	frm.clear_custom_buttons();

	// === PRIMARY ACTIONS GROUP ===

	// Customer and donor creation
	if (!frm.doc.customer) {
		frm.add_custom_button(__('Create Customer'), () => {
			frm.call({
				doc: frm.doc,
				method: 'create_customer',
				callback(r) {
					if (r.message) {
						frm.refresh();
					}
				}
			});
		}, __('Create'));
	}

	// Add donor creation button
	add_donor_creation_button(frm);

	// User account creation/management
	if (frm.doc.email) {
		if (!frm.doc.user) {
			frm.add_custom_button(__('Create User Account'), () => {
				create_user_account_dialog(frm);
			}, __('Create'));
		}
	}

	// Volunteer profile creation
	check_and_add_volunteer_creation_button(frm);

	// Membership creation - only for members without active memberships
	add_membership_creation_button(frm);

	// Consolidated dues schedule management
	add_consolidated_dues_schedule_buttons(frm);

	// === MEMBER ACTIONS GROUP ===

	// Payment actions for submitted documents
	if (frm.doc.docstatus === 1 && frm.doc.payment_status !== 'Paid') {
		frm.add_custom_button(__('Process Payment'), () => {
			if (window.PaymentUtils) {
				PaymentUtils.process_payment(frm);
			}
		}, __('Member Actions'));

		frm.add_custom_button(__('Mark as Paid'), () => {
			if (window.PaymentUtils) {
				PaymentUtils.mark_as_paid(frm);
			}
		}, __('Member Actions'));
	}

	// Payment history update
	frm.add_custom_button(__('Update Payment History'), () => {
		incremental_update_history_tables(frm);
	}, __('Member Actions'));

	// View complete expense history (if employee is linked)
	if (frm.doc.employee) {
		frm.add_custom_button(__('View Complete Expense History'), () => {
			frappe.set_route('List', 'Expense Claim', {
				employee: frm.doc.employee
			});
		}, __('Member Actions'));
	}

	// Chapter assignment
	add_chapter_assignment_button(frm);

	// Termination and suspension actions
	add_member_status_actions(frm);

	// === REVIEW ACTIONS GROUP ===

	// Membership review button (improved loading)
	add_membership_review_button(frm);

	// Financial actions moved to Membership & Dues section
	// This button is now added in add_fee_management_buttons()
}

function add_consolidated_view_buttons(frm) {
	// Customer record
	if (frm.doc.customer) {
		frm.add_custom_button(__('Customer Record'), () => {
			frappe.set_route('Form', 'Customer', frm.doc.customer);
		}, __('View'));
	}

	// User account
	if (frm.doc.user) {
		frm.add_custom_button(__('User Account'), () => {
			frappe.set_route('Form', 'User', frm.doc.user);
		}, __('View'));
	}

	// Chapter record
	if (frm.doc.current_chapter_display) {
		frm.add_custom_button(__('Chapter'), () => {
			frappe.set_route('Form', 'Chapter', frm.doc.current_chapter_display);
		}, __('View'));
	}

	// Volunteer profile and activities
	add_volunteer_view_buttons(frm);

	// Donations view
	if (frm.doc.customer) {
		frm.add_custom_button(__('Donations'), () => {
			view_donations(frm);
		}, __('View'));
	}
}

function add_administrative_buttons(frm) {
	const hasAdminRole = frappe.user.has_role(['System Manager', 'Membership Manager', 'Verenigingen Administrator']);
	const isSystemManager = frappe.user.has_role(['System Manager']);

	if (!hasAdminRole) { return; }

	// Fee management
	if (frm.doc.docstatus === 1) {
		frm.add_custom_button(__('View Fee Details'), () => {
			show_fee_details_dialog(frm);
		}, __('Fee Management'));

		frm.add_custom_button(__('Override Membership Fee'), () => {
			show_fee_override_dialog(frm);
		}, __('Fee Management'));

		if (frm.doc.customer) {
			frm.add_custom_button(__('Refresh Dues Schedule History'), () => {
				refresh_dues_schedule_history(frm);
			}, __('Membership & Dues'));

			frm.add_custom_button(__('Refresh Dues Schedule Summary'), () => {
				load_dues_schedule_summary(frm);
			}, __('Membership & Dues'));
		}

		frm.add_custom_button(__('Refresh Fee Section'), () => {
			ensure_fee_management_section_visibility(frm);
			frappe.show_alert('Fee section visibility refreshed', 3);
		}, __('Fee Management'));
	}

	// Member ID management
	add_member_id_management_buttons(frm);

	// Debug tools for System Managers
	if (isSystemManager && frappe.boot.developer_mode) {
		// Debug tools can be added here as needed
	}

	// Ensure fee management section visibility
	ensure_fee_management_section_visibility(frm);
}

function add_donor_creation_button(frm) {
	// Check if donor record already exists
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.check_donor_exists',
		args: {
			member_name: frm.doc.name
		},
		callback(r) {
			if (r.message && !r.message.exists) {
				frm.add_custom_button(__('Create Donor Record'), () => {
					create_donor_from_member(frm);
				}, __('Create'));
			} else if (r.message && r.message.exists) {
				// Show view donor button instead
				frm.add_custom_button(__('Donor Record'), () => {
					frappe.set_route('Form', 'Donor', r.message.donor_name);
				}, __('View'));
			}
		}
	});
}

function create_donor_from_member(frm) {
	frappe.confirm(
		__('Create a donor record for {0}? This will enable donation tracking and receipts.', [frm.doc.full_name]),
		() => {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.create_donor_from_member',
				args: {
					member_name: frm.doc.name
				},
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: r.message.message,
							indicator: 'green'
						}, 5);
						frm.refresh(); // Refresh to update buttons

						// Optionally open the new donor record
						if (r.message.donor_name) {
							frappe.set_route('Form', 'Donor', r.message.donor_name);
						}
					} else {
						frappe.msgprint({
							message: r.message.error || r.message.message,
							indicator: 'red'
						});
					}
				}
			});
		}
	);
}

function add_membership_review_button(frm) {
	// Add application review buttons if member is pending
	if (frm.doc.application_status === 'Pending' && frm.doc.status === 'Pending') {
		// Check if user has appropriate permissions
		if (frappe.user.has_role(['Verenigingen Administrator', 'Membership Manager'])
            || is_chapter_board_member_with_permissions(frm)) {
			// Add approve button
			frm.add_custom_button(__('Approve Application'), () => {
				show_approval_dialog(frm);
			}, __('Review Actions'));

			// Add reject button
			frm.add_custom_button(__('Reject Application'), () => {
				show_rejection_dialog(frm);
			}, __('Review Actions'));

			// Add request more info button
			frm.add_custom_button(__('Request More Info'), () => {
				request_more_info(frm);
			}, __('Review Actions'));

			// Add dashboard indicator
			frm.dashboard.add_indicator(__('Pending Review'), 'orange');
		}
	}
}

function add_membership_creation_button(frm) {
	// Check if member has any active or pending memberships (exclude cancelled memberships)
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Membership',
			filters: {
				member: frm.doc.name,
				status: ['in', ['Active', 'Pending']],
				docstatus: ['!=', 2] // Exclude cancelled documents (docstatus 2)
			},
			fields: ['name'],
			limit: 1
		},
		callback(r) {
			if (!r.message || r.message.length === 0) {
				// No active or pending memberships found, show create button
				// (Cancelled memberships are ignored - member can create new membership after cancellation)
				frm.add_custom_button(__('Create Membership'), () => {
					frappe.new_doc('Membership', {
						member: frm.doc.name,
						member_name: frm.doc.full_name,
						email: frm.doc.email,
						mobile_no: frm.doc.contact_number,
						start_date: frappe.datetime.get_today()
					});
				}, __('Create'));
			}
		}
	});
}

function check_and_add_volunteer_creation_button(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Volunteer',
			filters: {
				member: frm.doc.name
			}
		},
		callback(r) {
			if (!r.message || r.message.length === 0) {
				frm.add_custom_button(__('Create Volunteer Profile'), () => {
					if (window.VolunteerUtils) {
						VolunteerUtils.create_volunteer_from_member(frm);
					}
				}, __('Create'));
			}
		}
	});
}

function add_volunteer_view_buttons(frm) {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Volunteer',
			filters: {
				member: frm.doc.name
			}
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				const volunteer = r.message[0];

				frm.add_custom_button(__('Volunteer Profile'), () => {
					frappe.set_route('Form', 'Volunteer', volunteer.name);
				}, __('View'));
			}
		}
	});
}

function add_chapter_assignment_button(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.is_chapter_management_enabled',
		callback(r) {
			if (r.message) {
				frm.add_custom_button(__('Assign Chapter'), () => {
					if (window.ChapterUtils) {
						ChapterUtils.assign_chapter_for_member(frm);
					}
				}, __('Member Actions'));

				// Add simple chapter suggestion when no chapter is assigned
				add_simple_chapter_suggestion(frm);

				// Add visual indicator for chapter membership
				if (frm.doc.current_chapter_display && !frm.doc.__unsaved) {
					frm.dashboard.add_indicator(__('Member of {0}', [frm.doc.current_chapter_display]), 'blue');
				}
			}
		}
	});
}

function add_member_status_actions(frm) {
	// Only check permissions for admin users
	const admin_roles = ['System Manager', 'Verenigingen Administrator', 'Verenigingen Manager', 'Verenigingen Staff'];
	const has_admin_role = frappe.user_roles.some(role => admin_roles.includes(role));

	if (!has_admin_role) {
		return; // Skip for non-admin users
	}

	// Check permissions and add termination/suspension buttons
	frappe.call({
		method: 'verenigingen.permissions.can_terminate_member_api',
		args: {
			member_name: frm.doc.name
		},
		callback(perm_result) {
			if (perm_result.message) {
				// Add termination actions
				add_termination_action_button(frm);
			}
		}
	});

	// Check suspension permissions
	frappe.call({
		method: 'verenigingen.api.suspension_api.can_suspend_member',
		args: {
			member_name: frm.doc.name
		},
		callback(perm_result) {
			if (perm_result.message) {
				add_suspension_action_button(frm);
			}
		}
	});
}

function add_termination_action_button(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_member_termination_status',
		args: {
			member: frm.doc.name
		},
		callback(r) {
			if (r.message && !r.message.has_active_termination) {
				const btn = frm.add_custom_button(__('Terminate Membership'), () => {
					if (window.TerminationUtils) {
						TerminationUtils.show_termination_dialog(frm.doc.name, frm.doc.full_name);
					}
				}, __('Member Actions'));

				if (btn && btn.addClass) {
					btn.addClass('btn-danger termination-button');
				}
			}
		}
	});
}

function add_suspension_action_button(frm) {
	frappe.call({
		method: 'verenigingen.api.suspension_api.get_suspension_status_safe',
		args: {
			member_name: frm.doc.name
		},
		callback(status_result) {
			// Handle error responses gracefully
			if (status_result.message && status_result.message.error) {
				// If user doesn't have permission, just don't show suspension buttons
				if (status_result.message.access_denied) {
					return; // Silent fail for permission errors
				}
				console.warn('Suspension status check failed:', status_result.message.error);
				return;
			}
			if (status_result.message && !status_result.message.error) {
				const status = status_result.message;

				if (status.is_suspended) {
					const btn = frm.add_custom_button(__('Unsuspend Member'), () => {
						show_unsuspension_dialog(frm);
					}, __('Member Actions'));

					if (btn && btn.addClass) {
						btn.addClass('btn-success suspension-button');
					}
				} else {
					const btn = frm.add_custom_button(__('Suspend Member'), () => {
						show_suspension_dialog(frm);
					}, __('Member Actions'));

					if (btn && btn.addClass) {
						btn.addClass('btn-warning suspension-button');
					}
				}
			}
		}
	});
}

function add_member_id_management_buttons(frm) {
	const user_roles = frappe.user_roles || [];
	const can_manage_member_ids = user_roles.includes('System Manager') || user_roles.includes('Membership Manager');

	if (!can_manage_member_ids) { return; }

	if (!frm.doc.member_id) {
		frm.add_custom_button(__('Assign Member ID'), () => {
			assign_member_id_dialog(frm);
		}, __('Member ID'));
	}

	// Member ID Statistics and Preview Next ID buttons removed as requested
}

function create_user_account_dialog(frm) {
	frappe.confirm(
		__('Create a user account for {0} to access member portal pages?', [frm.doc.full_name]),
		() => {
			frappe.call({
				method: 'verenigingen.verenigingen.doctype.member.member.create_member_user_account',
				args: {
					member_name: frm.doc.name,
					send_welcome_email: true
				},
				callback(r) {
					if (r.message) {
						if (r.message.success) {
							frappe.show_alert({
								message: r.message.message,
								indicator: 'green'
							}, 5);
							frm.refresh();
						} else {
							frappe.msgprint({
								message: r.message.error || r.message.message,
								indicator: 'red'
							});
						}
					}
				}
			});
		}
	);
}

function assign_member_id_dialog(frm) {
	frappe.confirm(
		__('Are you sure you want to assign a member ID to {0}?', [frm.doc.full_name]),
		() => {
			frm.call({
				method: 'ensure_member_id',
				doc: frm.doc,
				callback(r) {
					if (r.message && r.message.success) {
						frm.reload_doc();
						frappe.show_alert({
							message: r.message.message,
							indicator: 'green'
						}, 5);
					} else if (r.message && r.message.message) {
						frappe.msgprint(r.message.message);
					}
				}
			});
		}
	);
}

function view_donations(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.get_linked_donations',
		args: {
			member: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.donor) {
				frappe.route_options = {
					donor: r.message.donor
				};
				frappe.set_route('List', 'Donation');
			} else {
				frappe.msgprint(__('No donor record linked to this member.'));
			}
		}
	});
}

function add_simple_chapter_suggestion(frm) {
	// Chapter suggestion banner removed as requested
	// No longer showing assignment prompts in the UI
}

// ==================== FORM SETUP FUNCTIONS ====================

function setup_form_behavior(frm) {
	// Set up member ID field behavior
	if (frm.doc.member_id) {
		frm.set_df_property('member_id', 'read_only', 1);
	}

	// Set up payment method dependent fields
	if (window.UIUtils) {
		UIUtils.handle_payment_method_change(frm);
	}

	// Set up organization user creation if enabled
	setup_organization_user_creation(frm);
}

function setup_organization_user_creation(frm) {
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.verenigingen_settings.verenigingen_settings.get_organization_email_domain',
		callback(r) {
			if (r.message && r.message.organization_email_domain) {
				if (!frm.doc.user && frm.doc.docstatus === 1) {
					frm.add_custom_button(__('Create Organization User'), () => {
						if (window.UIUtils) {
							UIUtils.create_organization_user(frm);
						}
					}, __('Actions'));
				}
			}
		}
	});
}


function add_member_id_buttons(frm) {
	// Check if user has permission to manage member IDs
	const user_roles = frappe.user_roles || [];
	const can_manage_member_ids = user_roles.includes('System Manager') || user_roles.includes('Membership Manager');

	if (!can_manage_member_ids) {
		return; // User doesn't have permission
	}

	// Add "Assign Member ID" button if member doesn't have one
	if (!frm.doc.member_id) {
		frm.add_custom_button(__('Assign Member ID'), () => {
			frappe.confirm(
				__('Are you sure you want to assign a member ID to {0}?', [frm.doc.full_name]),
				() => {
					frm.call({
						method: 'ensure_member_id',
						doc: frm.doc,
						callback(r) {
							if (r.message && r.message.success) {
								frm.reload_doc();
								frappe.show_alert({
									message: r.message.message,
									indicator: 'green'
								}, 5);
							} else if (r.message && r.message.message) {
								frappe.msgprint(r.message.message);
							}
						}
					});
				}
			);
		}, __('Member ID'));
	}

	// Member ID Statistics and Preview Next ID buttons removed as requested

	// Add force assign button for System Managers
	if (user_roles.includes('System Manager')) {
		frm.add_custom_button(__('Force Assign Member ID'), () => {
			frappe.confirm(
				__('Force assign a member ID to {0}? This bypasses normal assignment rules.', [frm.doc.full_name]),
				() => {
					frm.call({
						method: 'force_assign_member_id',
						doc: frm.doc,
						callback(r) {
							if (r.message && r.message.success) {
								frm.reload_doc();
								frappe.show_alert({
									message: r.message.message,
									indicator: 'green'
								}, 5);
							} else if (r.message && r.message.message) {
								frappe.msgprint(r.message.message);
							}
						}
					});
				}
			);
		}, __('Member ID'));
	}
}

// show_member_id_statistics_dialog function removed as the button was removed

function add_fee_management_buttons(frm) {
	if (frm.doc.docstatus === 1) {
		// Add button to view current fee info
		frm.add_custom_button(__('View Fee Details'), () => {
			show_fee_details_dialog(frm);
		}, __('Membership & Dues'));

		// Add button to change fee if user has permission
		if (frappe.user.has_role(['System Manager', 'Membership Manager', 'Verenigingen Administrator'])) {
			frm.add_custom_button(__('Override Membership Fee'), () => {
				show_fee_override_dialog(frm);
			}, __('Membership & Dues'));
		}

		// Add the renamed refresh button if member has customer record
		if (frm.doc.customer) {
			frm.add_custom_button(__('Refresh Membership & Dues Info'), () => {
				if (window.PaymentUtils) {
					PaymentUtils.refresh_membership_dues_info(frm);
				}
			}, __('Membership & Dues'));
		}


		// Subscription history functionality removed - use dues schedule system instead
		// Dues schedule buttons moved to consolidated function
	}
}

function ensure_fee_management_section_visibility(frm) {
	// Ensure fee management section is visible for authorized users
	const hasRequiredRole = frappe.user.has_role(['System Manager', 'Membership Manager', 'Verenigingen Administrator']);
	const shouldShow = !frm.doc.__islocal && hasRequiredRole;

	if (shouldShow) {
		// Force show the section and all related fields
		frm.set_df_property('fee_management_section', 'hidden', 0);
		frm.set_df_property('fee_management_section', 'depends_on', '');
		frm.set_df_property('dues_rate', 'hidden', 0);
		frm.set_df_property('fee_override_reason', 'hidden', 0);
		frm.set_df_property('fee_override_date', 'hidden', 0);
		frm.set_df_property('fee_override_by', 'hidden', 0);
		frm.set_df_property('fee_change_history_section', 'hidden', 0);
		frm.set_df_property('fee_change_history', 'hidden', 0);

		// Also use toggle_display as backup
		frm.toggle_display('fee_management_section', true);
		frm.toggle_display('dues_rate', true);
		frm.toggle_display('fee_override_reason', true);
		frm.toggle_display('fee_override_date', true);
		frm.toggle_display('fee_override_by', true);
		frm.toggle_display('fee_change_history_section', true);
		frm.toggle_display('fee_change_history', true);

		// Force refresh the fields
		frm.refresh_field('dues_rate');
		frm.refresh_field('fee_override_reason');
		frm.refresh_field('fee_override_date');
		frm.refresh_field('fee_override_by');
		frm.refresh_field('fee_change_history');

		// Direct DOM manipulation to ensure visibility
		setTimeout(() => {
			$('[data-fieldname="fee_management_section"]').show();
			$('[data-fieldname="dues_rate"]').show();
			$('[data-fieldname="fee_override_reason"]').show();
			$('[data-fieldname="fee_override_date"]').show();
			$('[data-fieldname="fee_override_by"]').show();
		}, 100);
	} else {
		frm.toggle_display('fee_management_section', false);
	}
}

function show_fee_details_dialog(frm) {
	frappe.call({
		method: 'get_current_membership_fee',
		doc: frm.doc,
		callback(r) {
			if (r.message) {
				const fee_info = r.message;
				let html = `
                    <div class="fee-details">
                        <h4>Current Membership Fee Information</h4>
                        <table class="table table-bordered">
                            <tr><td><strong>Current Amount:</strong></td><td>${format_currency(fee_info.amount)}</td></tr>
                            <tr><td><strong>Source:</strong></td><td>${get_fee_source_label(fee_info.source)}</td></tr>
                `;

				if (fee_info.source === 'custom_override' && fee_info.reason) {
					html += `<tr><td><strong>Override Reason:</strong></td><td>${fee_info.reason}</td></tr>`;
				}

				if (fee_info.membership_type) {
					html += `<tr><td><strong>Membership Type:</strong></td><td>${fee_info.membership_type}</td></tr>`;
				}

				html += '</table></div>';

				const dialog = new frappe.ui.Dialog({
					title: __('Membership Fee Details'),
					size: 'large',
					fields: [
						{
							fieldtype: 'HTML',
							options: html
						}
					]
				});

				dialog.show();
			}
		}
	});
}

function show_fee_override_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Override Membership Fee'),
		size: 'large',
		fields: [
			{
				fieldtype: 'Currency',
				fieldname: 'new_fee_amount',
				label: __('New Fee Amount'),
				reqd: 1,
				description: __('Enter the new membership fee amount for this member')
			},
			{
				fieldtype: 'Small Text',
				fieldname: 'override_reason',
				label: __('Reason for Override'),
				reqd: 1,
				description: __('Explain why this member needs a different fee amount')
			},
			{
				fieldtype: 'HTML',
				options: `
                    <div class="alert alert-info">
                        <h5>Important Notes:</h5>
                        <ul>
                            <li>This will update the member's dues schedule with the new amount</li>
                            <li>The change will be recorded in the fee change history</li>
                            <li>Active dues schedules will be updated</li>
                        </ul>
                    </div>
                `
			}
		],
		primary_action_label: __('Apply Fee Override'),
		primary_action(values) {
			frappe.confirm(
				__('Are you sure you want to override the membership fee to {0}?', [format_currency(values.new_fee_amount)]),
				() => {
					frm.set_value('dues_rate', values.new_fee_amount);
					frm.set_value('fee_override_reason', values.override_reason);

					frm.save().then(() => {
						dialog.hide();
						frappe.show_alert({
							message: __('Membership fee override applied successfully'),
							indicator: 'green'
						}, 5);
					});
				}
			);
		}
	});

	dialog.show();
}

function get_fee_source_label(source) {
	const labels = {
		custom_override: 'Custom Override',
		membership_type: 'Membership Type Default',
		none: 'No Fee Set'
	};
	return labels[source] || source;
}

function refresh_dues_schedule_history(frm) {
	// Refresh both fee change history AND payment history with proper error handling
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.refresh_fee_change_history',
		args: {
			member_name: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.success) {
				// Check if document reload is needed
				if (r.message.reload_doc) {
					frappe.show_alert({
						message: `Dues schedule history refreshed: ${r.message.history_count} entries. Reloading document and refreshing financial history...`,
						indicator: 'green'
					}, 3);

					// Reload the document and then refresh financial history with fresh doc
					frm.reload_doc().then(() => {
						// After reload, refresh financial history with the fresh document
						frm.call({
							method: 'refresh_financial_history',
							doc: frm.doc,
							callback(payment_r) {
								frm.refresh_field('payment_history');

								let message = `Dues schedule history refreshed: ${r.message.history_count} entries from ${r.message.dues_schedules_found} schedules`;
								if (payment_r.message && payment_r.message.success) {
									message += `. Financial history refreshed: ${payment_r.message.added_entries || 0} new payment entries added (atomic updates only).`;
								} else if (payment_r.message) {
									message += `. Financial history refresh failed: ${payment_r.message.message}`;
								}

								frappe.show_alert({
									message,
									indicator: payment_r.message && payment_r.message.success ? 'green' : 'orange'
								}, 5);
							}
						});
					});
					return;
				}

				// If no reload needed, proceed normally
				frm.refresh_field('fee_change_history');

				// Also refresh financial history using modern atomic method
				frm.call({
					method: 'refresh_financial_history',
					doc: frm.doc,
					callback(payment_r) {
						frm.refresh_field('payment_history');

						let message = `Dues schedule history refreshed: ${r.message.history_count} entries from ${r.message.dues_schedules_found} schedules`;
						if (payment_r.message && payment_r.message.success) {
							message += `. Financial history refreshed: ${payment_r.message.added_entries || 0} new payment entries added (atomic updates only).`;
						} else if (payment_r.message) {
							message += `. Financial history refresh failed: ${payment_r.message.message}`;
						}

						frappe.show_alert({
							message,
							indicator: payment_r.message && payment_r.message.success ? 'green' : 'orange'
						}, 5);
					}
				});
			} else {
				frappe.show_alert({
					message: r.message ? r.message.message : 'Failed to refresh dues schedule history',
					indicator: 'red'
				}, 5);
			}
		}
	});
}

function refresh_dues_schedule_summary(frm) {
	// Updated to use dues schedule system
	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details',
		args: {
			member: frm.doc.name
		},
		callback(r) {
			if (r.message) {
				if (r.message.has_schedule && r.message.schedule_name) {
					frm.set_value('current_dues_schedule', r.message.schedule_name);
					frm.set_value('dues_rate', r.message.dues_rate || 0);
				}
				frappe.show_alert({
					message: 'Dues schedule summary refreshed',
					indicator: 'green'
				}, 3);
			}
		}
	});
}

function display_termination_status(frm) {
	if (!frm.doc.name) { return; }

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_member_termination_status',
		args: {
			member: frm.doc.name
		},
		callback(r) {
			if (r.message) {
				const status = r.message;

				// Update termination status HTML field
				update_termination_status_html(frm, status);

				// Add dashboard indicators
				add_termination_dashboard_indicators(frm, status);
			}
		}
	});
}

function update_termination_status_html(frm, status) {
	let html = '<div class="termination-status-display">';

	if (status.is_terminated && status.executed_requests && status.executed_requests.length > 0) {
		const term_data = status.executed_requests[0];
		html += `
            <div class="alert alert-danger">
                <h5><i class="fa fa-exclamation-triangle"></i> Membership Terminated</h5>
                <p><strong>Termination Type:</strong> ${term_data.termination_type}</p>
                <p><strong>Execution Date:</strong> ${frappe.datetime.str_to_user(term_data.execution_date)}</p>
                <p><strong>Request:</strong> <a href="/app/membership-termination-request/${term_data.name}">${term_data.name}</a></p>
            </div>
        `;
	} else if (status.pending_requests && status.pending_requests.length > 0) {
		const pending = status.pending_requests[0];
		const status_colors = {
			Draft: 'warning',
			'Pending Approval': 'warning',
			Approved: 'info'
		};
		const alert_class = status_colors[pending.status] || 'secondary';

		html += `
            <div class="alert alert-${alert_class}">
                <h5><i class="fa fa-clock-o"></i> Termination Request Pending</h5>
                <p><strong>Status:</strong> ${pending.status}</p>
                <p><strong>Type:</strong> ${pending.termination_type}</p>
                <p><strong>Request Date:</strong> ${frappe.datetime.str_to_user(pending.request_date)}</p>
                <p><strong>Request:</strong> <a href="/app/membership-termination-request/${pending.name}">${pending.name}</a></p>
            </div>
        `;
	} else {
		html += `
            <div class="alert alert-success">
                <h6><i class="fa fa-check-circle"></i> Active Membership</h6>
                <p>No termination requests or actions on record.</p>
            </div>
        `;
	}

	html += '</div>';

	// Update the HTML field
	if (frm.fields_dict.termination_status_html) {
		frm.fields_dict.termination_status_html.html(html);
	}
}

function add_termination_dashboard_indicators(frm, status) {
	if (status.is_terminated && status.executed_requests && status.executed_requests.length > 0) {
		const term_data = status.executed_requests[0];

		frm.dashboard.add_indicator(
			__('Membership Terminated'),
			'red'
		);

		if (term_data.execution_date) {
			frm.dashboard.add_indicator(
				__('Terminated on {0}', [frappe.datetime.str_to_user(term_data.execution_date)]),
				'grey'
			);
		}
	} else if (status.pending_requests && status.pending_requests.length > 0) {
		const pending = status.pending_requests[0];

		if (pending.status === 'Pending Approval') {
			frm.dashboard.add_indicator(
				__('Termination Pending Approval'),
				'orange'
			);
		} else if (pending.status === 'Approved') {
			frm.dashboard.add_indicator(
				__('Termination Approved - Awaiting Execution'),
				'yellow'
			);
		}
	}
}

// ==================== DUES SCHEDULE FUNCTIONS ====================
// Uses dues schedule system

function load_dues_schedule_summary(frm) {
	// Updated to use dues schedule system
	if (!frm.doc.name) {
		return;
	}

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.member.member.get_current_dues_schedule_details',
		args: {
			member: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.has_schedule && r.message.schedule_name) {
				// Update the current dues schedule link field
				frm.set_value('current_dues_schedule', r.message.schedule_name);
				// Update dues rate from schedule
				if (r.message.dues_rate !== undefined) {
					frm.set_value('dues_rate', r.message.dues_rate);
				}
				// next_invoice_date is automatically synced via fetch_from field

				// Add button to view dues schedule if it exists
				if (!frm.custom_buttons[__('View Dues Schedule')]) {
					frm.add_custom_button(__('View Dues Schedule'), () => {
						frappe.set_route('Form', 'Membership Dues Schedule', r.message.schedule_name);
					}, __('View'));
				}
			} else {
				// Clear the fields if no dues schedule found
				frm.set_value('current_dues_schedule', '');
				// next_invoice_date will be automatically cleared via fetch_from field
			}
		}
	});
}

// Subscription display functions removed - using dues schedule system
function update_dues_schedule_summary_display(frm, dues_schedule_data) {
	// Dues schedule system implementation
	const html = '<div class="alert alert-info">Membership Dues Schedule system is active.</div>';

	// Update any remaining legacy summary fields
	if (frm.fields_dict.current_legacy_summary) {
		frm.fields_dict.current_legacy_summary.html(html);
	}
}


// ==================== NAME HANDLING FUNCTIONS ====================

function update_full_name_from_components(frm) {
	// Build full name with proper handling of name particles (tussenvoegsels)
	const name_parts = [];

	if (frm.doc.first_name && frm.doc.first_name.trim()) {
		name_parts.push(frm.doc.first_name.trim());
	}

	// Handle name particles (tussenvoegsels) - these should be lowercase when in the middle
	if (frm.doc.middle_name && frm.doc.middle_name.trim()) {
		const particles = frm.doc.middle_name.trim();
		// Ensure particles are lowercase when between first and last name
		name_parts.push(particles.toLowerCase());
	}

	if (frm.doc.last_name && frm.doc.last_name.trim()) {
		name_parts.push(frm.doc.last_name.trim());
	}

	const full_name = name_parts.join(' ');

	// Only update if the generated name is different and not empty
	if (full_name && frm.doc.full_name !== full_name) {
		frm.set_value('full_name', full_name);
	}
}

// ==================== SUSPENSION FUNCTIONS ====================

function add_suspension_buttons(frm) {
	if (!frm.doc.name) { return; }

	// Check if user can perform suspension actions
	frappe.call({
		method: 'verenigingen.api.suspension_api.can_suspend_member',
		args: {
			member_name: frm.doc.name
		},
		callback(perm_result) {
			const can_suspend = perm_result.message;

			if (!can_suspend) {
				return; // No permission, don't show buttons
			}

			// Get current suspension status
			frappe.call({
				method: 'verenigingen.api.suspension_api.get_suspension_status_safe',
				args: {
					member_name: frm.doc.name
				},
				callback(status_result) {
					// Handle error responses gracefully
					if (status_result.message && status_result.message.error) {
						if (status_result.message.access_denied) {
							return; // Silent fail for permission errors
						}
						console.warn('Suspension status check failed:', status_result.message.error);
						return;
					}
					if (status_result.message && !status_result.message.error) {
						const status = status_result.message;

						if (status.is_suspended) {
							// Member is suspended - show unsuspend button
							const btn = frm.add_custom_button(__('Unsuspend Member'), () => {
								show_unsuspension_dialog(frm);
							}, __('Actions'));

							if (btn && btn.addClass) {
								btn.addClass('btn-success suspension-button');
							}
						} else {
							// Member is not suspended - show suspend button
							const btn = frm.add_custom_button(__('Suspend Member'), () => {
								show_suspension_dialog(frm);
							}, __('Actions'));

							if (btn && btn.addClass) {
								btn.addClass('btn-warning suspension-button');
							}
						}
					}
				}
			});
		}
	});
}

function show_suspension_dialog(frm) {
	// First get suspension preview
	frappe.call({
		method: 'verenigingen.api.suspension_api.get_suspension_preview',
		args: {
			member_name: frm.doc.name
		},
		callback(r) {
			if (r.message) {
				const preview = r.message;

				let preview_html = `
                    <div class="suspension-preview">
                        <h5>Suspension Impact</h5>
                        <ul>
                            <li><strong>Member Status:</strong> ${preview.member_status} → Suspended</li>
                `;

				if (preview.has_user_account) {
					preview_html += '<li><strong>User Account:</strong> Will be disabled</li>';
				}

				if (preview.active_teams > 0) {
					preview_html += `<li><strong>Team Memberships:</strong> ${preview.active_teams} team(s) will be suspended</li>`;
					if (preview.team_details && preview.team_details.length > 0) {
						preview_html += '<li><strong>Teams:</strong> ';
						preview_html += preview.team_details.map(t => `${t.team} (${t.role})`).join(', ');
						preview_html += '</li>';
					}
				}

				if (preview.active_memberships > 0) {
					preview_html += `<li><strong>Active Memberships:</strong> ${preview.active_memberships} membership(s) remain active</li>`;
				}

				preview_html += '</ul></div>';

				const dialog = new frappe.ui.Dialog({
					title: __('Suspend Member: {0}', [frm.doc.full_name]),
					size: 'large',
					fields: [
						{
							fieldtype: 'HTML',
							options: preview_html
						},
						{
							fieldtype: 'Section Break',
							label: __('Suspension Details')
						},
						{
							fieldname: 'suspension_reason',
							fieldtype: 'Small Text',
							label: __('Reason for Suspension'),
							reqd: 1,
							description: __('Explain why this member is being suspended')
						},
						{
							fieldtype: 'Column Break'
						},
						{
							fieldname: 'suspend_user',
							fieldtype: 'Check',
							label: __('Suspend User Account'),
							default: 1,
							description: __('Disable the member\'s backend user account')
						},
						{
							fieldname: 'suspend_teams',
							fieldtype: 'Check',
							label: __('Suspend Team Memberships'),
							default: 1,
							description: __('Remove member from all teams')
						}
					],
					primary_action_label: __('Suspend Member'),
					primary_action(values) {
						frappe.confirm(
							__('Are you sure you want to suspend {0}?', [frm.doc.full_name]),
							() => {
								frappe.call({
									method: 'verenigingen.api.suspension_api.suspend_member',
									args: {
										member_name: frm.doc.name,
										suspension_reason: values.suspension_reason,
										suspend_user: values.suspend_user,
										suspend_teams: values.suspend_teams
									},
									callback(r) {
										if (r.message && r.message.success) {
											dialog.hide();
											frm.reload_doc();
										}
									}
								});
							}
						);
					}
				});

				dialog.show();
			}
		}
	});
}

function show_unsuspension_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __('Unsuspend Member: {0}', [frm.doc.full_name]),
		fields: [
			{
				fieldtype: 'HTML',
				options: `
                    <div class="alert alert-info">
                        <h5>Unsuspension Process</h5>
                        <ul>
                            <li>Member status will be restored to previous state</li>
                            <li>User account will be reactivated</li>
                            <li>Team memberships require manual restoration</li>
                        </ul>
                    </div>
                `
			},
			{
				fieldname: 'unsuspension_reason',
				fieldtype: 'Small Text',
				label: __('Reason for Unsuspension'),
				reqd: 1,
				description: __('Explain why this member is being unsuspended')
			}
		],
		primary_action_label: __('Unsuspend Member'),
		primary_action(values) {
			frappe.confirm(
				__('Are you sure you want to unsuspend {0}?', [frm.doc.full_name]),
				() => {
					frappe.call({
						method: 'verenigingen.api.suspension_api.unsuspend_member',
						args: {
							member_name: frm.doc.name,
							unsuspension_reason: values.unsuspension_reason
						},
						callback(r) {
							if (r.message && r.message.success) {
								dialog.hide();
								frm.reload_doc();
							}
						}
					});
				}
			);
		}
	});

	dialog.show();
}

function display_suspension_status(frm) {
	if (!frm.doc.name) { return; }

	frappe.call({
		method: 'verenigingen.api.suspension_api.get_suspension_status_safe',
		args: {
			member_name: frm.doc.name
		},
		callback(r) {
			// Handle error responses gracefully
			if (r.message && r.message.error) {
				if (r.message.access_denied) {
					return; // Silent fail for permission errors
				}
				console.warn('Suspension status display failed:', r.message.error);
				return;
			}
			if (r.message && !r.message.error) {
				const status = r.message;

				if (status.is_suspended) {
					// Add dashboard indicator for suspended member
					frm.dashboard.add_indicator(
						__('Member Suspended'),
						'orange'
					);

					if (status.user_suspended) {
						frm.dashboard.add_indicator(
							__('User Account Disabled'),
							'red'
						);
					}

					if (status.active_teams === 0) {
						frm.dashboard.add_indicator(
							__('No Active Teams'),
							'grey'
						);
					}
				}
			}
		}
	});
}

function display_amendment_status(frm) {
	if (!frm.doc.name) { return; }

	frappe.call({
		method: 'verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request.get_member_pending_contribution_amendments',
		args: {
			member_name: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				const amendments = r.message;
				let amendment_html = '<div class="amendment-status-container" style="margin: 10px 0;">';

				for (const amendment of amendments) {
					let status_color = 'orange';
					let alert_class = 'alert-warning';
					if (amendment.status === 'Approved') {
						status_color = 'green';
						alert_class = 'alert-success';
					}
					if (amendment.status === 'Rejected') {
						status_color = 'red';
						alert_class = 'alert-danger';
					}

					amendment_html += `
                        <div class="alert ${alert_class}" style="padding: 12px; margin: 8px 0; border-left: 4px solid var(--${status_color});">
                            <div class="row">
                                <div class="col-md-8">
                                    <h6 style="margin: 0 0 5px 0;"><i class="fa fa-edit"></i> ${amendment.amendment_type}</h6>
                                    <p style="margin: 0;"><strong>Amount:</strong> ${frappe.format(amendment.requested_amount, { fieldtype: 'Currency' })}</p>
                                    <p style="margin: 5px 0 0 0;"><small><strong>Reason:</strong> ${amendment.reason}</small></p>
                                </div>
                                <div class="col-md-4 text-right">
                                    <span class="badge badge-${status_color} badge-lg" style="font-size: 12px; padding: 4px 8px;">${amendment.status}</span>
                                    <br><small style="color: #666;">Effective: ${frappe.datetime.str_to_user(amendment.effective_date)}</small>
                                    <br><a href="/app/contribution-amendment-request/${amendment.name}" class="btn btn-xs btn-default" style="margin-top: 5px;">
                                        View Amendment
                                    </a>
                                </div>
                            </div>
                        </div>
                    `;
				}

				amendment_html += '</div>';

				// Try injecting the content directly as a dashboard element as a fallback
				let amendment_displayed = false;

				// First try the standard HTML field approach
				if (frm.fields_dict.amendment_status_html) {
					try {
						frm.fields_dict.amendment_status_html.$wrapper.html(amendment_html);
						frm.set_df_property('amendment_status_section', 'depends_on', '');
						frm.set_df_property('amendment_status_section', 'hidden', 0);
						frm.toggle_display('amendment_status_section', true);
						frm.toggle_display('amendment_status_html', true);

						// Try to expand collapsible section
						setTimeout(() => {
							const sectionField = frm.get_field('amendment_status_section');
							if (sectionField && sectionField.collapse) {
								sectionField.collapse(false);
							}

							const sectionEl = $('[data-fieldname="amendment_status_section"]');
							const collapseToggle = sectionEl.find('.collapse-indicator, .octicon-chevron-down, .octicon-chevron-right');
							if (collapseToggle.length > 0) {
								collapseToggle.click();
							}

							// Check if it's actually visible after all attempts
							const htmlEl = $('[data-fieldname="amendment_status_html"]');
							if (htmlEl.is(':visible')) {
								amendment_displayed = true;
							}
						}, 200);
					} catch (e) {
						console.error('Error setting HTML field:', e);
					}
				}

				// Fallback: Add as dashboard comment if HTML field doesn't work
				setTimeout(() => {
					if (!amendment_displayed) {
						// Clear any existing amendment dashboard elements
						frm.dashboard.clear_comment();

						// Add as dashboard element
						const dashboard_html = `
                            <div class="alert alert-info" style="margin: 10px 0;">
                                <h5><i class="fa fa-info-circle"></i> Pending Fee Amendment</h5>
                                ${amendment_html}
                            </div>
                        `;

						frm.dashboard.add_comment(dashboard_html, 'blue', true);
					}
				}, 500);

				// Clear any existing amendment indicators before adding new one
				const existing_indicators = frm.dashboard.stats_area_parent.find('.indicator-pill:contains("Pending Amendments")');
				existing_indicators.remove();

				// Add dashboard indicator
				frm.dashboard.add_indicator(
					__('Pending Amendments: {0}', [amendments.length]),
					'orange'
				);
			} else {
				// Hide the section if no amendments
				if (frm.fields_dict.amendment_status_html) {
					frm.toggle_display('amendment_status_section', false);
					frm.toggle_display('amendment_status_html', false);
				}
			}
		},
		error(r) {
			console.error('Error loading amendment status:', r);
			// Hide the section on error
			if (frm.fields_dict.amendment_status_html) {
				frm.toggle_display('amendment_status_section', false);
			}
		}
	});
}

// ==================== SEPA MANDATE OPTIMIZATION ====================

// Debounced SEPA mandate status check to avoid rapid API calls
// Function declaration to avoid redeclaration issues
function check_sepa_mandate_status_debounced(frm) {
	// Static variable to store timeout
	if (!check_sepa_mandate_status_debounced.timeout) {
		check_sepa_mandate_status_debounced.timeout = null;
	}

	// Clear any existing timeout
	if (check_sepa_mandate_status_debounced.timeout) {
		clearTimeout(check_sepa_mandate_status_debounced.timeout);
	}

	// Set a new timeout to check SEPA status after 300ms of inactivity
	check_sepa_mandate_status_debounced.timeout = setTimeout(() => {
		if (frm.doc.payment_method === 'SEPA Direct Debit' && frm.doc.iban) {
			if (window.SepaUtils && window.SepaUtils.check_sepa_mandate_status) {
				SepaUtils.check_sepa_mandate_status(frm);
			}
		} else {
			// Clear SEPA UI if conditions aren't met
			if (window.SepaUtils && window.SepaUtils.clear_sepa_ui_elements) {
				SepaUtils.clear_sepa_ui_elements(frm);
			}
		}
	}, 300);
}

function check_sepa_mandate_and_prompt_creation(frm, context = 'general') {
	// Simplified function - only update UI, no more real-time prompting
	// SEPA mandate discrepancy checking is now handled by scheduled task

	if (!frm.doc.iban || frm.doc.payment_method !== 'SEPA Direct Debit') {
		return;
	}

	// Just update the UI to show current SEPA status
	if (window.SepaUtils && window.SepaUtils.check_sepa_mandate_status) {
		SepaUtils.check_sepa_mandate_status(frm);
	}
}

// ==================== APPLICATION REVIEW FUNCTIONS ====================

function show_approval_dialog(frm) {
	// Get membership types
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Membership Type',
			filters: { is_active: 1 },
			fields: ['name', 'membership_type_name']
		},
		callback(r) {
			const membership_types = r.message || [];

			var d = new frappe.ui.Dialog({
				title: __('Approve Membership Application'),
				fields: [
					{
						fieldname: 'membership_type',
						fieldtype: 'Select',
						label: __('Membership Type'),
						options: membership_types.map(t => t.name).join('\n'),
						reqd: 1,
						default: frm.doc.selected_membership_type || ''
					},
					{
						fieldname: 'create_invoice',
						fieldtype: 'Check',
						label: __('Create Invoice'),
						default: 1,
						description: __('Generate an invoice for the first membership fee')
					},
					{
						fieldname: 'assign_chapter',
						fieldtype: 'Link',
						label: __('Assign to Chapter'),
						options: 'Chapter',
						default: frm.doc.suggested_chapter
					},
					{
						fieldname: 'welcome_message',
						fieldtype: 'Small Text',
						label: __('Additional Welcome Message'),
						description: __('Optional personalized message to include in welcome email')
					}
				],
				primary_action_label: __('Approve'),
				primary_action(values) {
					// Update chapter if changed
					if (values.assign_chapter && values.assign_chapter !== frm.doc.primary_chapter) {
						frappe.model.set_value(frm.doctype, frm.docname, 'primary_chapter', values.assign_chapter);
					}

					// Call comprehensive approval method
					frappe.call({
						method: 'verenigingen.api.membership_application_review.approve_membership_application',
						args: {
							member_name: frm.doc.name,
							create_invoice: values.create_invoice,
							membership_type: values.membership_type,
							chapter: values.assign_chapter,
							notes: values.welcome_message
						},
						freeze: true,
						freeze_message: __('Approving application...'),
						callback(r) {
							if (r.message && r.message.success) {
								frappe.show_alert({
									message: __('Application approved successfully!'),
									indicator: 'green'
								}, 5);
								d.hide();
								frm.reload_doc();
							}
						}
					});
				}
			});

			d.show();
		}
	});
}

function show_rejection_dialog(frm) {
	var d = new frappe.ui.Dialog({
		title: __('Reject Membership Application'),
		fields: [
			{
				fieldname: 'rejection_category',
				fieldtype: 'Select',
				label: __('Rejection Category'),
				options: [
					'Incomplete Information',
					'Ineligible for Membership',
					'Duplicate Application',
					'Failed Verification',
					'Does Not Meet Requirements',
					'Application Withdrawn',
					'Other'
				].join('\n'),
				reqd: 1,
				description: __('Select the primary reason for rejection')
			},
			{
				fieldname: 'email_template',
				fieldtype: 'Link',
				label: __('Email Template'),
				options: 'Email Template',
				filters: {
					name: ['like', '%rejection%']
				},
				reqd: 1,
				description: __('Email template to use for rejection notification')
			},
			{
				fieldname: 'additional_details',
				fieldtype: 'Small Text',
				label: __('Additional Details'),
				description: __('Specific details to include in the rejection email (optional)')
			},
			{
				fieldname: 'internal_notes',
				fieldtype: 'Small Text',
				label: __('Internal Notes'),
				description: __('For internal use only, not sent to applicant')
			}
		],
		primary_action_label: __('Reject Application'),
		primary_action(values) {
			// Combine category and additional details for the reason
			let reason = values.rejection_category;
			if (values.additional_details) {
				reason += `: ${values.additional_details}`;
			}

			frappe.call({
				method: 'verenigingen.api.membership_application_review.reject_membership_application',
				args: {
					member_name: frm.doc.name,
					reason,
					email_template: values.email_template,
					rejection_category: values.rejection_category,
					internal_notes: values.internal_notes,
					process_refund: false
				},
				freeze: true,
				freeze_message: __('Rejecting application...'),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __('Application rejected successfully'),
							indicator: 'red'
						}, 5);
						d.hide();
						frm.reload_doc();
					}
				}
			});
		}
	});

	// Load available email templates and set default
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Email Template',
			filters: {
				name: ['like', '%rejection%']
			},
			fields: ['name', 'subject']
		},
		callback(r) {
			if (r.message && r.message.length > 0) {
				// Set the first available rejection template as default
				d.set_value('email_template', r.message[0].name);
			} else {
				// If no templates exist, show message and create default ones
				frappe.confirm(
					__('No rejection email templates found. Would you like to create default templates?'),
					() => {
						create_default_email_templates().then(() => {
							frappe.msgprint(__('Default email templates created. Please try again.'));
							d.hide();
						});
					}
				);
			}
		}
	});

	d.show();
}

function request_more_info(frm) {
	var d = new frappe.ui.Dialog({
		title: __('Request More Information'),
		fields: [
			{
				fieldname: 'info_needed',
				fieldtype: 'Small Text',
				label: __('Information Needed'),
				reqd: 1,
				description: __('Describe what additional information you need from the applicant')
			}
		],
		primary_action_label: __('Send Request'),
		primary_action(values) {
			// Update status to "Under Review"
			frappe.model.set_value(frm.doctype, frm.docname, 'application_status', 'Under Review');

			// Send email to applicant
			frappe.call({
				method: 'frappe.core.doctype.communication.email.make',
				args: {
					recipients: frm.doc.email,
					subject: __('Additional Information Required for Your Membership Application'),
					content: `
                        <p>Dear ${frm.doc.first_name},</p>
                        <p>Thank you for your membership application. We need some additional information to process your application:</p>
                        <p><strong>${values.info_needed}</strong></p>
                        <p>Please reply to this email with the requested information.</p>
                        <p>Best regards,<br>The Membership Team</p>
                    `,
					doctype: frm.doctype,
					name: frm.docname,
					send_email: 1
				},
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __('Request sent to applicant'),
							indicator: 'blue'
						}, 5);
						d.hide();
						frm.save();
					}
				}
			});
		}
	});

	d.show();
}

function is_chapter_board_member_with_permissions(frm) {
	// Check if current user is a board member of the suggested chapter with appropriate permissions
	if (!frm.doc.suggested_chapter) { return false; }

	// This would need a server call to check properly
	// For now, returning false - you'd implement the actual check
	return false;
}

function create_default_email_templates() {
	// Create default email templates for membership application management
	return frappe.call({
		method: 'verenigingen.api.membership_application_review.create_default_email_templates',
		freeze: true,
		freeze_message: __('Creating default email templates...')
	});
}

// ==================== DUTCH NAMING SYSTEM ====================

function setup_dutch_naming_fields(frm) {
	// Check if this is a Dutch installation and show/hide tussenvoegsel field accordingly
	frappe.call({
		method: 'verenigingen.utils.dutch_name_utils.is_dutch_installation',
		callback(r) {
			if (r.message) {
				// This is a Dutch installation, show the tussenvoegsel field
				frm.toggle_display('tussenvoegsel', true);

				// Add a refresh handler for name fields to update full_name
				setup_dutch_name_refresh_handlers(frm);
			} else {
				// Not a Dutch installation, keep the field hidden
				frm.toggle_display('tussenvoegsel', false);
			}
		}
	});
}

function setup_dutch_name_refresh_handlers(frm) {
	// Add event handlers to update full_name when Dutch name fields change
	// Check if fields exist and are rendered before attaching handlers

	if (frm.fields_dict.first_name && frm.fields_dict.first_name.$input) {
		frm.fields_dict.first_name.$input.on('blur', () => {
			update_dutch_full_name(frm);
		});
	}

	if (frm.fields_dict.middle_name && frm.fields_dict.middle_name.$input) {
		frm.fields_dict.middle_name.$input.on('blur', () => {
			update_dutch_full_name(frm);
		});
	}

	if (frm.fields_dict.tussenvoegsel && frm.fields_dict.tussenvoegsel.$input) {
		frm.fields_dict.tussenvoegsel.$input.on('blur', () => {
			update_dutch_full_name(frm);
		});
	}

	if (frm.fields_dict.last_name && frm.fields_dict.last_name.$input) {
		frm.fields_dict.last_name.$input.on('blur', () => {
			update_dutch_full_name(frm);
		});
	}
}

function update_dutch_full_name(frm) {
	// Call server method to update full_name using Dutch naming conventions
	if (frm.doc.first_name || frm.doc.last_name) {
		frappe.call({
			method: 'verenigingen.utils.dutch_name_utils.format_dutch_full_name',
			args: {
				first_name: frm.doc.first_name || '',
				middle_name: frm.doc.middle_name || '',
				tussenvoegsel: frm.doc.tussenvoegsel || '',
				last_name: frm.doc.last_name || ''
			},
			callback(r) {
				if (r.message && r.message !== frm.doc.full_name) {
					frm.set_value('full_name', r.message);
				}
			}
		});
	}
}

// ==================== ADDRESS MEMBERS FUNCTIONALITY ====================

window.update_other_members_at_address = function (frm, force_refresh = false) {
	// Update the other_members_at_address field when address changes
	// console.log('update_other_members_at_address called for:', frm.doc.name, 'Address:', frm.doc.primary_address, 'Force:', force_refresh);

	if (!frm.doc.primary_address || frm.doc.__islocal) {
		// console.log('No address or new document, clearing field');
		// Clear field if no address or new document
		const field_element = $('[data-fieldname="other_members_at_address"]');
		if (field_element.length > 0) {
			field_element.find('.control-value, .control-html, .form-control').html('');
		}
		return;
	}

	// Check if we have onload data first
	if (frm.doc.__onload && frm.doc.__onload.other_members_at_address && !force_refresh) {
		// console.log('Using cached onload data for address members');
		const html_content = frm.doc.__onload.other_members_at_address;

		// Inject the onload content
		const field_element = $('[data-fieldname="other_members_at_address"]');
		if (field_element.length > 0) {
			field_element.show();
			field_element.css('display', 'block');
			field_element.css('visibility', 'visible');

			const control_value = field_element.find('.control-value, .control-html').first();
			if (control_value.length > 0) {
				control_value.html(html_content);
				// console.log('Injected cached onload content');
			}
		}
		return;
	}

	// Call backend method to get other members at same address
	frappe.call({
		method: 'verenigingen.api.member_management.get_address_members_html_api',
		args: {
			member_id: frm.doc.name
		},
		callback(r) {
			// console.log('Address detection response:', r);

			if (r.message) {
				// console.log('API response structure:', Object.keys(r.message));

				// Handle both possible response formats
				let html_content = null;
				if (r.message.success && r.message.html) {
					html_content = r.message.html;
				} else if (r.message.html) {
					html_content = r.message.html;
				} else if (typeof r.message === 'string') {
					html_content = r.message;
				}

				if (html_content) {
					// console.log('Got HTML content from API:', html_content.substring(0, 100) + '...');

					// Use direct DOM injection for HTML fields to avoid triggering dirty state
					const inject_content = () => {
						const field_element = $('[data-fieldname="other_members_at_address"]');
						// console.log('Address members field found:', field_element.length > 0);

						if (field_element.length > 0) {
							// Ensure field is visible
							field_element.show();
							field_element.css('display', 'block');
							field_element.css('visibility', 'visible');

							// Find the control value div for HTML fields
							const control_value = field_element.find('.control-value, .control-html').first();
							if (control_value.length > 0) {
								// Direct HTML injection without triggering form changes
								control_value.html(html_content);
								// console.log('Address members content injected successfully');

								// Also try to update the field wrapper if it exists
								const field_wrapper = field_element.find('.form-control.like-disabled-input');
								if (field_wrapper.length > 0) {
									field_wrapper.html(html_content);
								}
							} else {
								// console.log('Control value element not found, trying alternative selectors');
								// Try alternative selectors for HTML field content
								const alt_container = field_element.find('.html-editor-container, .control-input, .form-control');
								if (alt_container.length > 0) {
									alt_container.html(html_content);
									// console.log('Used alternative container for content injection');
								}
							}

							// console.log('Address members field should now be visible with member content');
						} else {
							// console.log('Field element not found in DOM, will retry...');
							return false; // Indicate retry needed
						}
						return true; // Success
					};

					// Try injection with retries to handle delayed DOM rendering
					let retries = 0;
					const max_retries = 5;
					const retry_delay = 300;

					const attempt_injection = () => {
						if (inject_content()) {
							// console.log('Content injection successful');
						} else if (retries < max_retries) {
							retries++;
							// console.log(`Retrying content injection (${retries}/${max_retries})...`);
							setTimeout(attempt_injection, retry_delay);
						} else {
							console.error('Failed to inject content after maximum retries');
						}
					};

					// Start injection attempts
					setTimeout(attempt_injection, 200);
				} else {
					// console.log('No HTML content in response');
				}
			} else {
				// console.log('No response message from API');
				// Clear field using DOM manipulation to avoid dirty state
				setTimeout(() => {
					const field_element = $('[data-fieldname="other_members_at_address"]');
					if (field_element.length > 0) {
						field_element.find('.control-value, .control-html, .form-control').html('');
					}
				}, 200);
			}
		},
		error(r) {
			console.error('Error loading other members at address:', r);
			// Clear field on error
			frm.set_value('other_members_at_address', '');
		}
	});
};

// ==================== USER LINK MANAGEMENT ====================

function setup_user_link_button(frm) {
	// Add a custom User link button if member has linked user
	if (frm.doc.user && !frm.doc.__islocal) {
		frm.add_custom_button(__('View User Account'), () => {
			frappe.set_route('Form', 'User', frm.doc.user);
		}, __('Links'));

		// Also add in the connections area if dashboard exists
		if (frm.dashboard && frm.dashboard.stats_area) {
			// Add custom link entry to dashboard
			const user_link = `
                <div class="col-sm-6">
                    <div class="document-link" data-doctype="User">
                        <div class="document-link-badge">
                            <span class="count">1</span>
                            <a class="badge-link" href="#Form/User/${encodeURIComponent(frm.doc.user)}">
                                ${__('User')}
                            </a>
                        </div>
                        <div class="document-link-item">
                            <a href="#Form/User/${encodeURIComponent(frm.doc.user)}"
                               class="text-muted text-underline">
                                ${frm.doc.user}
                            </a>
                        </div>
                    </div>
                </div>
            `;

			// Find existing dashboard and append user link
			const connections_area = frm.dashboard.stats_area_parent;
			if (connections_area && !connections_area.find('[data-doctype="User"]').length) {
				connections_area.append(user_link);
			}
		}
	}
}

function setup_customer_link_button(frm) {
	// Add a custom Customer link button if member has linked customer
	if (frm.doc.customer && !frm.doc.__islocal) {
		frm.add_custom_button(__('View Customer Record'), () => {
			frappe.set_route('Form', 'Customer', frm.doc.customer);
		}, __('Links'));

		// Also add in the connections area if dashboard exists
		if (frm.dashboard && frm.dashboard.stats_area) {
			// Add custom link entry to dashboard
			const customer_link = `
                <div class="col-sm-6">
                    <div class="document-link" data-doctype="Customer">
                        <div class="document-link-badge">
                            <span class="count">1</span>
                            <a class="badge-link" href="#Form/Customer/${encodeURIComponent(frm.doc.customer)}">
                                ${__('Customer')}
                            </a>
                        </div>
                        <div class="document-link-item">
                            <a href="#Form/Customer/${encodeURIComponent(frm.doc.customer)}"
                               class="text-muted text-underline">
                                ${frm.doc.customer}
                            </a>
                        </div>
                    </div>
                </div>
            `;

			// Find existing dashboard and append customer link
			const connections_area = frm.dashboard.stats_area_parent;
			if (connections_area && !connections_area.find('[data-doctype="Customer"]').length) {
				connections_area.append(customer_link);
			}
		}
	}
}

// Consolidated dues schedule button management
function add_consolidated_dues_schedule_buttons(frm) {
	if (!frm.doc.name || frm.doc.__islocal) { return; }

	// Check for any active dues schedule for this member
	frappe.db.get_value('Membership Dues Schedule', {
		member: frm.doc.name,
		is_template: 0,
		status: ['in', ['Active', 'Paused']]
	}, ['name', 'dues_rate', 'billing_frequency', 'status']).then((result) => {
		if (result.message && result.message.name) {
			const schedule = result.message;

			// Add consolidated dues schedule button
			frm.add_custom_button(__('View Dues Schedule'), () => {
				frappe.set_route('Form', 'Membership Dues Schedule', schedule.name);
			}, __('Membership & Dues'));

			// Add dues rate info button
			frm.add_custom_button(__(`Current Rate: €${schedule.dues_rate} (${schedule.billing_frequency})`), () => {
				frappe.set_route('Form', 'Membership Dues Schedule', schedule.name);
			}, __('Membership & Dues'));

			// Refresh dues history button
			frm.add_custom_button(__('Refresh Dues History'), () => {
				refresh_dues_schedule_history(frm);
			}, __('Membership & Dues'));

			// Sync dues rate button
			frm.add_custom_button(__('Sync Dues Rate'), () => {
				frappe.call({
					method: 'verenigingen.verenigingen.doctype.member.member.sync_member_dues_rate',
					args: { member_name: frm.doc.name },
					callback(r) {
						if (r.message && r.message.success) {
							frm.set_value('dues_rate', r.message.dues_rate);
							frappe.show_alert({
								message: r.message.message,
								indicator: 'green'
							}, 3);
						} else {
							frappe.show_alert({
								message: r.message.message || 'Sync failed',
								indicator: 'red'
							}, 3);
						}
					}
				});
			}, __('Membership & Dues'));

			// Add manual invoice generation button
			frm.add_custom_button(__('Generate Invoice'), () => {
				show_manual_invoice_dialog(frm);
			}, __('Membership & Dues'));

			// Update current dues schedule field
			frm.set_value('current_dues_schedule', schedule.name);
		}
	}).catch((error) => {
		console.error('Dues schedule buttons: Error loading schedule', error);
	});
}

// ==================== MANUAL INVOICE GENERATION ====================

function show_manual_invoice_dialog(frm) {
	// First get member's current dues schedule and invoice info
	frappe.call({
		method: 'verenigingen.api.manual_invoice_generation.get_member_invoice_info',
		args: {
			member_name: frm.doc.name
		},
		callback(r) {
			if (r.message && r.message.success) {
				const info = r.message;

				if (!info.has_customer) {
					frappe.msgprint({
						title: __('Customer Record Required'),
						message: __('This member needs a customer record to generate invoices. Please create a customer record first.'),
						indicator: 'red'
					});
					return;
				}

				if (!info.has_dues_schedule) {
					frappe.msgprint({
						title: __('No Dues Schedule'),
						message: __('This member does not have an active dues schedule. Please create a dues schedule first.'),
						indicator: 'red'
					});
					return;
				}

				// Show confirmation dialog with member info
				let recent_invoices_html = '';
				if (info.recent_invoices && info.recent_invoices.length > 0) {
					recent_invoices_html = '<h5>Recent Invoices:</h5><ul>';
					info.recent_invoices.forEach((invoice) => {
						const status_color = invoice.status === 'Paid' ? 'green' : (invoice.status === 'Overdue' ? 'red' : 'orange');
						recent_invoices_html += `<li><strong>${invoice.name}</strong> - ${invoice.posting_date} - €${invoice.grand_total} <span style="color: ${status_color};">(${invoice.status})</span></li>`;
					});
					recent_invoices_html += '</ul>';
				}

				const dialog_content = `
					<p><strong>Member:</strong> ${info.member_name}</p>
					<p><strong>Current Rate:</strong> €${info.current_rate} (${info.billing_frequency})</p>
					<p><strong>Dues Schedule:</strong> ${info.dues_schedule_name}</p>
					${info.next_invoice_date ? `<p><strong>Next Scheduled Invoice:</strong> ${info.next_invoice_date}</p>` : ''}
					${recent_invoices_html}
					<p><em>This will generate a new invoice for €${info.current_rate} using the current dues schedule settings.</em></p>
				`;

				frappe.confirm(
					dialog_content,
					() => {
						// User confirmed - generate the invoice
						generate_manual_invoice_for_member(frm, info);
					},
					() => {
						// User cancelled - do nothing
					},
					__('Generate Manual Invoice'),
					__('Generate Invoice'),
					__('Cancel')
				);
			} else {
				frappe.msgprint({
					title: __('Error'),
					message: r.message ? r.message.error : __('Failed to retrieve member information'),
					indicator: 'red'
				});
			}
		}
	});
}

function generate_manual_invoice_for_member(frm, member_info) {
	frappe.call({
		method: 'verenigingen.api.manual_invoice_generation.generate_manual_invoice',
		args: {
			member_name: frm.doc.name
		},
		freeze: true,
		freeze_message: __('Generating invoice...'),
		callback(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				}, 5);

				// Ask if user wants to view the invoice
				frappe.confirm(
					__('Invoice {0} has been generated successfully. Would you like to view it now?', [r.message.invoice_name]),
					() => {
						frappe.set_route('Form', 'Sales Invoice', r.message.invoice_name);
					}
				);

				// Refresh the form to update any payment history
				frm.reload_doc();
			} else {
				frappe.msgprint({
					title: __('Invoice Generation Failed'),
					message: r.message ? r.message.error : __('Unknown error occurred'),
					indicator: 'red'
				});
			}
		}
	});
}

// ==================== ATOMIC HISTORY TABLE UPDATE ====================

function incremental_update_history_tables(frm) {
	if (!frm.doc.name || frm.doc.__islocal) {
		frappe.msgprint(__('Please save the member record first.'));
		return;
	}

	frappe.confirm(
		__('This will update both volunteer expense and donation payment history with the most recent entries. Continue?'),
		() => {
			frappe.call({
				method: 'incremental_update_history_tables',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Updating payment history...'),
				callback(r) {
					if (r.message && r.message.overall_success) {
						const message_parts = [];

						// Add volunteer expenses results
						if (r.message.volunteer_expenses.success) {
							message_parts.push(__('Volunteer Expenses: Updated {0} entries', [r.message.volunteer_expenses.count]));
						} else if (r.message.volunteer_expenses.error) {
							message_parts.push(__('Volunteer Expenses: {0}', [r.message.volunteer_expenses.error]));
						}

						// Add donations results
						if (r.message.donations.success) {
							message_parts.push(__('Donations: Updated {0} entries', [r.message.donations.count]));
						} else if (r.message.donations.error) {
							message_parts.push(__('Donations: {0}', [r.message.donations.error]));
						}

						frappe.show_alert({
							message: __('History tables updated successfully:<br>{0}', [message_parts.join('<br>')]),
							indicator: 'green'
						}, 7);

						// Refresh the form to show updated tables
						frm.reload_doc();
					} else {
						const error_message = r.message ? r.message.error : __('Unknown error occurred');
						const error_parts = [];

						if (r.message && r.message.volunteer_expenses.error) {
							error_parts.push(__('Volunteer Expenses: {0}', [r.message.volunteer_expenses.error]));
						}
						if (r.message && r.message.donations.error) {
							error_parts.push(__('Donations: {0}', [r.message.donations.error]));
						}

						frappe.msgprint({
							title: __('Update Failed'),
							message: error_parts.length > 0 ? error_parts.join('<br><br>') : error_message,
							indicator: 'red'
						});
					}
				}
			});
		}
	);
}
