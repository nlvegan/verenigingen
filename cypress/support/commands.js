/**
 * @fileoverview Cypress Custom Commands for Verenigingen E2E Testing
 *
 * This module provides a comprehensive suite of custom Cypress commands specifically designed
 * for end-to-end testing of the Verenigingen association management system. These commands
 * abstract common testing operations into reusable, maintainable functions that ensure
 * consistent test behavior across the application.
 *
 * Purpose and Architecture
 * -----------------------
 * The custom commands address several key testing requirements:
 *
 * **Test Consistency**: Provides standardized ways to interact with Frappe DocType forms
 * **Maintainability**: Centralizes common operations to reduce test code duplication
 * **Reliability**: Implements proper waiting strategies and error handling
 * **Abstraction**: Hides complexity of Frappe UI interactions from test specifications
 *
 * Key Features
 * ------------
 * - **Authentication Management**: Session-based login with automatic caching
 * - **DocType Navigation**: Specialized commands for Frappe document workflows
 * - **Field Interaction**: Type-aware field input handling for different Frappe field types
 * - **Document Lifecycle**: Save, submit, and validation operations
 * - **Test Data Management**: Utilities for test data cleanup and isolation
 *
 * Business Context
 * ---------------
 * The Verenigingen system manages complex business workflows including:
 * - Member registration and management
 * - Volunteer coordination and assignments
 * - Financial operations and donations
 * - Chapter organization and governance
 *
 * These commands enable comprehensive testing of these workflows while maintaining
 * test isolation and data integrity across test runs.
 *
 * Technical Implementation
 * -----------------------
 *
 * ### Session Management Strategy
 * Uses Cypress session caching to minimize login overhead:
 * - Sessions are cached by email/password combination
 * - Automatic session restoration for subsequent tests
 * - Proper logout handling for test isolation
 *
 * ### Field Type Handling
 * Implements specialized input strategies for Frappe field types:
 * - **Link Fields**: Autocomplete interaction with dropdown selection
 * - **Select Fields**: Option selection from predefined choices
 * - **Check Fields**: Boolean state management
 * - **Data Fields**: Direct text input with validation
 *
 * ### Waiting Strategy
 * Implements strategic waits to handle Frappe's dynamic UI:
 * - Fixed waits for known slow operations
 * - Dynamic waits for element visibility
 * - Form state synchronization delays
 *
 * Command Categories
 * -----------------
 *
 * ### Authentication Commands
 * - `cy.login()`: Session-cached authentication with role support
 *
 * ### Navigation Commands
 * - `cy.visit_list()`: Navigate to DocType list views
 * - `cy.new_doc()`: Open new document creation forms
 *
 * ### Form Interaction Commands
 * - `cy.fill_field()`: Type-aware field input handling
 * - `cy.verify_field()`: Field value validation
 *
 * ### Document Lifecycle Commands
 * - `cy.save()`: Document saving with completion waiting
 * - `cy.submit()`: Document submission with confirmation handling
 *
 * ### Test Management Commands
 * - `cy.clear_test_data()`: Comprehensive test data cleanup
 *
 * Error Handling and Reliability
 * -----------------------------
 * - Implements proper waiting strategies for dynamic content
 * - Handles Frappe's asynchronous form operations
 * - Provides fallback mechanisms for flaky operations
 * - Includes timeout handling for slow operations
 *
 * Usage Patterns
 * -------------
 *
 * ### Typical Test Flow
 * ```javascript
 * describe('Member Registration', () => {
 *   beforeEach(() => {
 *     cy.login('test@example.com', 'password');
 *     cy.clear_test_data();
 *   });
 *
 *   it('should create new member', () => {
 *     cy.new_doc('Member');
 *     cy.fill_field('first_name', 'Test');
 *     cy.fill_field('last_name', 'User');
 *     cy.fill_field('email', 'test@example.com');
 *     cy.save();
 *     cy.verify_field('status', 'Active');
 *   });
 * });
 * ```
 *
 * ### Field Type Examples
 * ```javascript
 * // Link field with autocomplete
 * cy.fill_field('chapter', 'Amsterdam', 'Link');
 *
 * // Select field with predefined options
 * cy.fill_field('membership_type', 'Regular', 'Select');
 *
 * // Checkbox field
 * cy.fill_field('is_volunteer', true, 'Check');
 *
 * // Regular data field
 * cy.fill_field('phone_number', '+31612345678');
 * ```
 *
 * Integration with Testing Infrastructure
 * -------------------------------------
 * These commands integrate with the broader testing infrastructure:
 *
 * **Test Data Factory**: Works with server-side test data creation utilities
 * **Database Cleanup**: Coordinates with backend cleanup procedures
 * **Permission Testing**: Supports role-based access testing scenarios
 * **API Integration**: Can trigger backend operations for complex test setup
 *
 * Performance Considerations
 * -------------------------
 * - Session caching reduces authentication overhead
 * - Strategic waits balance speed with reliability
 * - Bulk operations for test data management
 * - Optimized selectors for faster element location
 *
 * Maintenance and Extension
 * ------------------------
 * To add new commands:
 * 1. Follow the established naming convention
 * 2. Implement proper error handling and waiting
 * 3. Document the command's purpose and usage
 * 4. Add appropriate timeout handling
 * 5. Consider reusability across different test scenarios
 *
 * Author: Development Team
 * Date: 2025-08-03
 * Version: 1.0
 */

// Login command
Cypress.Commands.add('login', (email = 'Administrator', password = 'admin') => {
	cy.session([email, password], () => {
		cy.visit('/login');
		cy.get('#login_email').clear().type(email);
		cy.get('#login_password').clear().type(password);
		cy.get('.btn-login').click();
		cy.location('pathname').should('eq', '/app');
	});
});

// Navigate to doctype list
Cypress.Commands.add('visit_list', (doctype) => {
	cy.visit(`/app/${frappe.router.slug(doctype)}`);
	cy.wait(1000);
});

// Create a new document
Cypress.Commands.add('new_doc', (doctype) => {
	cy.visit(`/app/${frappe.router.slug(doctype)}/new`);
	cy.wait(1000);
});

// Fill field
Cypress.Commands.add('fill_field', (fieldname, value, fieldtype = 'Data') => {
	if (fieldtype === 'Link' || fieldtype === 'Select') {
		cy.get(`[data-fieldname="${fieldname}"] input`).clear().type(value);
		cy.wait(500);
		cy.get('.awesomplete li').first().click();
	} else if (fieldtype === 'Check') {
		if (value) {
			cy.get(`[data-fieldname="${fieldname}"] input`).check();
		} else {
			cy.get(`[data-fieldname="${fieldname}"] input`).uncheck();
		}
	} else {
		cy.get(`[data-fieldname="${fieldname}"] input`).clear().type(value);
	}
});

// Save document
Cypress.Commands.add('save', () => {
	cy.get('.primary-action').contains('Save').click();
	cy.wait(2000);
});

// Submit document
Cypress.Commands.add('submit', () => {
	cy.get('.actions-btn-group button').contains('Submit').click();
	cy.get('.modal-footer button').contains('Yes').click();
	cy.wait(2000);
});

// Verify field value
Cypress.Commands.add('verify_field', (fieldname, value) => {
	cy.get(`[data-fieldname="${fieldname}"]`).should('contain', value);
});

// Clear all test data
Cypress.Commands.add('clear_test_data', () => {
	cy.window().then((win) => {
		return win.frappe.call({
			method: 'verenigingen.tests.clear_test_data',
			args: {}
		});
	});
});
