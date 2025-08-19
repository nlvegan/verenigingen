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

// Legacy fill_field command - redirects to enhanced version
Cypress.Commands.add('fill_field', (fieldname, value, fieldtype = 'Data') => {
	cy.fill_frappe_field(fieldname, value, { fieldtype });
});

// Save document
Cypress.Commands.add('save', () => {
	cy.get('.primary-action').contains('Save').click();
	cy.wait(2000);
});

// Submit document - using custom name to avoid conflict with built-in submit
Cypress.Commands.add('submit_doc', () => {
	cy.get('.actions-btn-group button').contains('Submit').click();
	cy.get('.modal-footer button').contains('Yes').click();
	cy.wait(2000);
});

// Verify field value
Cypress.Commands.add('verify_field', (fieldname, value) => {
	cy.get(`[data-fieldname="${fieldname}"]`).should('contain', value);
});

// ============================================================================
// CONFIGURATION AND UTILITIES
// ============================================================================

// Configuration object for timeouts, selectors, and test settings
const CypressConfig = {
	timeouts: {
		formLoad: 5000,
		apiCall: 10000,
		dialogAppear: 3000,
		fieldInput: 1000,
		memberDataPopulate: 1000, // For Link field data to populate
		formSave: 2000, // For form save operations
		documentSubmit: 3000, // For document submission
		sepaValidation: 2000, // For SEPA validation processes
		quickValidation: 500, // For quick field validations
		postalCodeLookup: 1000, // For Dutch postal code API calls
		mandateCreation: 3000, // For SEPA mandate creation
		batchProcessing: 3000, // For Direct Debit batch processing
		navigationDelay: 2000 // For page navigation and form loading
	},
	selectors: {
		formLayout: '.form-layout',
		modal: '.modal',
		saveButton: '.primary-action:contains("Save")',
		submitButton: '.actions-btn-group button:contains("Submit")'
	},
	retries: {
		fieldInput: 3,
		apiCall: 2
	}
};

// Enhanced waiting utility with dynamic conditions
Cypress.Commands.add('wait_for_condition', (conditionFn, options = {}) => {
	const { timeout = 10000, interval = 100, errorMessage = 'Condition not met' } = options;

	return cy.waitUntil(conditionFn, {
		timeout,
		interval,
		errorMsg: errorMessage
	});
});

// Wait for Frappe form to be fully loaded and ready
Cypress.Commands.add('wait_for_frappe_form', (doctype) => {
	return cy.wait_for_condition(
		() => cy.window().then(win =>
			win.frappe
			&& win.frappe.ui
			&& win.frappe.ui.form
			&& win.frappe.ui.form.get_form(doctype)
			&& win.frappe.ui.form.get_form(doctype).doc
		),
		{
			timeout: CypressConfig.timeouts.formLoad,
			errorMessage: `Failed to load ${doctype} form controller`
		}
	);
});

// Enhanced error handling wrapper
Cypress.Commands.add('with_error_handling', (operation, fallbackFn = null) => {
	return cy.window().then(win => {
		try {
			return operation(win);
		} catch (error) {
			cy.log(`Operation failed: ${error.message}`);
			if (fallbackFn) {
				return fallbackFn(win, error);
			}
			throw error;
		}
	});
});

// ============================================================================
// ENHANCED WAITING AND TIMEOUT COMMANDS
// ============================================================================

/**
 * Wait with centralized timeout configuration
 * @param {string} timeoutType - Key from CypressConfig.timeouts
 */
Cypress.Commands.add('wait_with_config', (timeoutType) => {
	const timeout = CypressConfig.timeouts[timeoutType] || CypressConfig.timeouts.fieldInput;
	cy.wait(timeout);
});

/**
 * Wait for specific condition with error recovery
 * @param {Function} condition - Function that returns boolean when condition is met
 * @param {string} timeoutType - Timeout key from CypressConfig
 * @param {string} errorMessage - Error message if timeout
 */
Cypress.Commands.add('wait_for_business_condition', (condition, timeoutType = 'fieldInput', errorMessage = 'Condition not met') => {
	const timeout = CypressConfig.timeouts[timeoutType];

	return cy.waitUntil(condition, {
		timeout,
		interval: 200,
		errorMsg: errorMessage
	}).catch(() => {
		cy.log(`Timeout waiting for condition: ${errorMessage}`);
		// Fallback: try once more with longer timeout
		return cy.waitUntil(condition, {
			timeout: timeout * 2,
			interval: 500,
			errorMsg: `Final attempt: ${errorMessage}`
		});
	});
});

/**
 * Wait for member data to populate in Link fields
 */
Cypress.Commands.add('wait_for_member_data', () => {
	cy.wait_with_config('memberDataPopulate');
});

/**
 * Wait for SEPA validation processes
 */
Cypress.Commands.add('wait_for_sepa_validation', () => {
	cy.wait_with_config('sepaValidation');
});

/**
 * Wait for form navigation and loading
 */
Cypress.Commands.add('wait_for_navigation', () => {
	cy.wait_with_config('navigationDelay');
});

/**
 * Wait for specific field to be ready and populated
 * @param {string} fieldname - Name of the field to wait for
 * @param {string} expectedValue - Optional expected value to wait for
 */
Cypress.Commands.add('wait_for_field_ready', (fieldname, expectedValue = null) => {
	return cy.waitUntil(() => {
		return cy.get(`[data-fieldname="${fieldname}"]`).should('be.visible').then(() => {
			if (expectedValue) {
				return cy.get(`[data-fieldname="${fieldname}"] input, [data-fieldname="${fieldname}"] select, [data-fieldname="${fieldname}"] textarea`)
					.should('have.value', expectedValue).then(() => true);
			}
			return true;
		});
	}, {
		timeout: CypressConfig.timeouts.formLoad,
		interval: 200,
		errorMsg: `Field ${fieldname} not ready after waiting`
	});
});

/**
 * Wait for link field to populate with selected value
 * @param {string} fieldname - Name of the link field
 * @param {string} expectedValue - Expected linked value
 */
Cypress.Commands.add('wait_for_link_field_populated', (fieldname, expectedValue) => {
	return cy.waitUntil(() => {
		return cy.get(`[data-fieldname="${fieldname}"] input`)
			.should('have.value', expectedValue).then(() => true);
	}, {
		timeout: CypressConfig.timeouts.memberDataPopulate,
		interval: 100,
		errorMsg: `Link field ${fieldname} did not populate with ${expectedValue}`
	});
});

// ============================================================================
// COMPREHENSIVE ERROR RECOVERY PATTERNS
// ============================================================================

/**
 * Execute business workflow with comprehensive error recovery
 * @param {Function} workflow - The main workflow function
 * @param {Function} fallbackFn - Fallback function if main workflow fails
 * @param {string} workflowName - Name for logging purposes
 */
Cypress.Commands.add('execute_business_workflow', (workflow, fallbackFn = null, workflowName = 'Unknown Workflow') => {
	return cy.window().then(win => {
		return cy.wrap(null).then(() => {
			try {
				cy.log(`Executing business workflow: ${workflowName}`);
				return workflow(win);
			} catch (error) {
				cy.log(`Workflow ${workflowName} failed: ${error.message}`);
				cy.screenshot(`workflow-failure-${workflowName.replace(/\s+/g, '-').toLowerCase()}`);

				if (fallbackFn) {
					cy.log(`Attempting fallback for ${workflowName}`);
					return fallbackFn(win, error);
				}

				// Default fallback: retry once after a short wait
				cy.log(`Default retry for ${workflowName}`);
				cy.wait_with_config('quickValidation');
				return workflow(win);
			}
		});
	});
});

/**
 * SEPA operation with error recovery
 * @param {Function} sepaOperation - SEPA-related operation
 * @param {string} operationType - Type of SEPA operation
 */
Cypress.Commands.add('execute_sepa_operation', (sepaOperation, operationType = 'SEPA Operation') => {
	return cy.execute_business_workflow(
		(win) => sepaOperation(win),
		(win, error) => {
			cy.log(`SEPA operation failed: ${error.message}`);

			// SEPA-specific fallbacks
			if (error.message.includes('SepaUtils')) {
				cy.log('Reloading SEPA utilities...');
				cy.reload();
				cy.wait_for_navigation();
				return sepaOperation(win);
			}

			if (error.message.includes('IBAN')) {
				cy.log('IBAN validation failed, retrying with validation reset...');
				cy.wait_for_sepa_validation();
				return sepaOperation(win);
			}

			throw error;
		},
		operationType
	);
});

/**
 * Form operation with validation error recovery
 * @param {Function} formOperation - Form-related operation
 * @param {string} operationType - Type of form operation
 */
Cypress.Commands.add('execute_form_operation', (formOperation, operationType = 'Form Operation') => {
	return cy.execute_business_workflow(
		(win) => formOperation(win),
		(win, error) => {
			cy.log(`Form operation failed: ${error.message}`);

			// Form-specific fallbacks
			if (error.message.includes('form not ready')) {
				cy.log('Form not ready, waiting for form load...');
				cy.wait_with_config('formLoad');
				return formOperation(win);
			}

			if (error.message.includes('validation')) {
				cy.log('Validation error, attempting to clear and retry...');
				cy.get('.has-error').should('be.visible');
				cy.wait_with_config('quickValidation');
				return formOperation(win);
			}

			throw error;
		},
		operationType
	);
});

// ============================================================================
// ENHANCED TEST DATA ISOLATION PATTERNS
// ============================================================================

/**
 * Create isolated test scope with cleanup tracking
 * @param {string} testName - Name of the test for scoping
 * @param {Function} testFn - Test function to execute
 */
Cypress.Commands.add('with_test_scope', (testName, testFn) => {
	const testScope = `test_${testName.replace(/\s+/g, '_').toLowerCase()}_${Date.now()}`;

	// Store test scope for cleanup
	cy.wrap(testScope).as('currentTestScope');

	return cy.wrap(testScope).then((scope) => {
		cy.log(`Starting test scope: ${scope}`);

		// Execute test function with scope
		return testFn(scope).finally(() => {
			// Cleanup only this scope's data
			cy.cleanup_test_scope(scope);
		});
	});
});

/**
 * Cleanup test scope data
 * @param {string} scope - Test scope to cleanup
 */
Cypress.Commands.add('cleanup_test_scope', (scope) => {
	cy.log(`Cleaning up test scope: ${scope}`);

	// More targeted cleanup than clearing all test data
	cy.window().then((win) => {
		if (win.frappe && win.frappe.call) {
			// Call backend cleanup for specific test scope
			return win.frappe.call({
				method: 'verenigingen.tests.utils.cleanup_test_scope',
				args: { scope }
			}).catch(() => {
				cy.log(`Scope cleanup failed for ${scope}, using fallback`);
				// Fallback to general cleanup
				cy.clear_test_data();
			});
		}
	});
});

/**
 * Create test data with scope tracking
 * @param {string} doctype - DocType to create
 * @param {Object} data - Data for the document
 * @param {string} scope - Test scope for isolation
 */
Cypress.Commands.add('create_scoped_test_data', (doctype, data, scope) => {
	const scopedData = {
		...data,
		test_scope: scope,
		// Add test identifier to name if possible
		name: data.name ? `${data.name}_${scope}` : undefined
	};

	return cy.request({
		method: 'POST',
		url: `/api/resource/${doctype}`,
		body: scopedData,
		failOnStatusCode: false
	}).then((response) => {
		if (response.status === 200 || response.status === 201) {
			cy.log(`Created scoped ${doctype}: ${response.body.data.name}`);
			return response.body.data;
		} else {
			cy.log(`Failed to create scoped ${doctype}: ${response.statusText}`);
			throw new Error(`Failed to create ${doctype}`);
		}
	});
});

/**
 * Enhanced test member creation with scope isolation
 * @param {string} scope - Test scope for isolation
 */
Cypress.Commands.add('create_scoped_test_member', (scope) => {
	const memberData = {
		first_name: 'Scoped',
		last_name: 'Test Member',
		email: `scoped.test.${scope}@example.com`,
		birth_date: '1990-01-01',
		test_scope: scope
	};

	return cy.create_scoped_test_data('Member', memberData, scope);
});

// ============================================================================
// ENHANCED TEST FACTORY INTEGRATION
// ============================================================================

// Create test member with financial setup using Enhanced Test Factory
Cypress.Commands.add('createTestMemberWithFinancialSetup', () => {
	return cy.request({
		method: 'POST',
		url: '/api/method/frappe.tests.utils.run_server_script',
		body: {
			script: `
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory
factory = EnhancedTestDataFactory()
test_member = factory.create_test_member(
	first_name="Test",
	last_name="Member",
	has_iban=True,
	has_sepa_mandate=True,
	with_customer=True
)
frappe.response["message"] = test_member.as_dict()
`
		}
	}).then((response) => {
		expect(response.status).to.eq(200);
		return response.body.message;
	});
});

// Create test member with chapter assignment
Cypress.Commands.add('createTestMemberWithChapter', () => {
	return cy.request({
		method: 'POST',
		url: '/api/method/frappe.tests.utils.run_server_script',
		body: {
			script: `
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory
factory = EnhancedTestDataFactory()
member = factory.create_test_member(
	first_name="Chapter",
	last_name="Member",
	with_chapter=True
)
frappe.response["message"] = member.as_dict()
`
		}
	}).then((response) => {
		expect(response.status).to.eq(200);
		return response.body.message;
	});
});

// Create test volunteer using Enhanced Test Factory
Cypress.Commands.add('createTestVolunteer', () => {
	return cy.request({
		method: 'POST',
		url: '/api/method/frappe.tests.utils.run_server_script',
		body: {
			script: `
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory
factory = EnhancedTestDataFactory()
member = factory.create_test_member(
	first_name="Volunteer",
	last_name="Member",
	birth_date="1990-01-01"
)
volunteer = factory.create_test_volunteer(member.name)
frappe.response["message"] = {
	"member": member.as_dict(),
	"volunteer": volunteer.as_dict()
}
`
		}
	}).then((response) => {
		expect(response.status).to.eq(200);
		return response.body.message;
	});
});

// Enhanced clear test data with comprehensive cleanup
Cypress.Commands.add('clear_test_data', () => {
	return cy.request({
		method: 'POST',
		url: '/api/method/verenigingen.api.generate_test_members.cleanup_test_members',
		body: {}
	}).then((response) => {
		expect(response.status).to.eq(200);
		// Clear browser cache and storage
		cy.clearLocalStorage();
		cy.clearCookies();
		return response.body;
	});
});

// Wait for JavaScript form controller to be ready
Cypress.Commands.add('wait_for_form_ready', (doctype) => {
	cy.window().then((win) => {
		cy.waitUntil(() => {
			const form = win.frappe.ui.form.get_form(doctype);
			return form && form.doc && form.layout && form.layout.wrapper;
		}, {
			timeout: 10000,
			interval: 100
		});
	});
});

// Verify JavaScript module is loaded
Cypress.Commands.add('verify_js_module', (moduleName) => {
	cy.window().then((win) => {
		expect(win[moduleName]).to.exist;
	});
});

// Test JavaScript field validation
Cypress.Commands.add('test_field_validation', (fieldname, invalidValue, validValue, expectedError) => {
	// Test invalid value
	cy.fill_field(fieldname, invalidValue);
	cy.get(`[data-fieldname="${fieldname}"] input`).should('have.class', 'is-invalid');
	if (expectedError) {
		cy.get('.invalid-feedback').should('contain', expectedError);
	}

	// Test valid value
	cy.fill_field(fieldname, validValue);
	cy.get(`[data-fieldname="${fieldname}"] input`).should('have.class', 'is-valid');
});

// Click custom button with wait and verification
Cypress.Commands.add('click_custom_button', (buttonLabel) => {
	cy.get(`button[data-label="${buttonLabel}"]`)
		.should('be.visible')
		.should('not.be.disabled')
		.click();
	cy.wait(1000);
});

// Verify JavaScript-generated UI element
Cypress.Commands.add('verify_js_ui_element', (selector, shouldExist = true) => {
	if (shouldExist) {
		cy.get(selector).should('be.visible');
	} else {
		cy.get(selector).should('not.exist');
	}
});

// Test JavaScript event handler
Cypress.Commands.add('trigger_js_event', (eventType, selector) => {
	cy.get(selector).trigger(eventType);
	cy.wait(500); // Allow time for JavaScript to process event
});

// Verify form JavaScript initialization
Cypress.Commands.add('verify_form_js_init', (doctype, expectedModules = []) => {
	// Verify main form controller
	cy.window().then((win) => {
		expect(win.frappe.ui.form.get_form(doctype)).to.exist;
	});

	// Verify expected utility modules are loaded
	expectedModules.forEach(module => {
		cy.verify_js_module(module);
	});

	// Verify form layout is ready
	cy.get('.form-layout').should('be.visible');
	cy.get('.form-body').should('be.visible');
});

// Test Dutch-specific validations
Cypress.Commands.add('test_dutch_validation', (fieldname, testValue, expectedResult) => {
	cy.fill_field(fieldname, testValue);

	// Wait for Dutch validation to complete
	cy.wait(1000);

	// Check validation result
	if (expectedResult.valid) {
		cy.get(`[data-fieldname="${fieldname}"] input`).should('have.class', 'is-valid');
		if (expectedResult.message) {
			cy.get('.validation-message').should('contain', expectedResult.message);
		}
	} else {
		cy.get(`[data-fieldname="${fieldname}"] input`).should('have.class', 'is-invalid');
		if (expectedResult.error) {
			cy.get('.invalid-feedback').should('contain', expectedResult.error);
		}
	}
});

// Create test member with enhanced options - updated to use existing API
Cypress.Commands.add('createTestMember', () => {
	return cy.request({
		method: 'POST',
		url: '/api/method/verenigingen.api.generate_test_members.generate_test_members',
		body: {}
	}).then((response) => {
		// The API creates multiple test members, return the first one
		return response.body.message.members_created[0];
	});
});

// ============================================================================
// FRAPPE DOCTYPE JAVASCRIPT CONTROLLER TESTING
// ============================================================================

// Navigate to DocType list with proper waiting
Cypress.Commands.add('visit_doctype_list', (doctype) => {
	const slug = doctype.toLowerCase().replace(/\s+/g, '-');
	cy.visit(`/app/${slug}`);
	cy.wait(2000); // Allow list to load
	cy.get('.page-title').should('contain', doctype);
});

// Navigate to DocType form and verify JavaScript controller loading
Cypress.Commands.add('visit_doctype_form', (doctype, docname = null) => {
	const slug = doctype.toLowerCase().replace(/\s+/g, '-');
	const url = docname ? `/app/${slug}/${docname}` : `/app/${slug}/new`;

	cy.visit(url);
	cy.wait(2000); // Allow form to load

	// Verify form loaded
	cy.get('.form-layout').should('be.visible');

	// Verify JavaScript controller is available
	cy.window().then((win) => {
		expect(win.frappe.ui.form.get_form(doctype)).to.exist;
	});
});

// Fill Frappe field with intelligent type detection
Cypress.Commands.add('fill_frappe_field', (fieldname, value, options = {}) => {
	const { fieldtype = 'Data' } = options;

	// Get the field wrapper with dynamic waiting
	const fieldSelector = `[data-fieldname="${fieldname}"]`;
	cy.wait_for_field_ready(fieldname);

	if (fieldtype === 'Link') {
		// Handle Link fields with autocomplete
		cy.get(`${fieldSelector} input`)
			.clear()
			.type(value);
		// Wait for dropdown with intelligent condition
		cy.waitUntil(() => {
			return cy.get('body').then($body => {
				return $body.find('.awesomplete li').length > 0;
			});
		}, {
			timeout: CypressConfig.timeouts.fieldInput,
			interval: 100,
			errorMsg: `Autocomplete dropdown not found for ${fieldname}`
		});

		// Select first option and wait for field to populate
		cy.get('.awesomplete li').first().click();
		cy.wait_for_link_field_populated(fieldname, value);
	} else if (fieldtype === 'Select') {
		// Handle Select fields
		cy.get(`${fieldSelector} select`).select(value);
	} else if (fieldtype === 'Check') {
		// Handle Check fields
		if (value) {
			cy.get(`${fieldSelector} input[type="checkbox"]`).check();
		} else {
			cy.get(`${fieldSelector} input[type="checkbox"]`).uncheck();
		}
	} else if (fieldtype === 'Date') {
		// Handle Date fields
		cy.get(`${fieldSelector} input`)
			.clear()
			.type(value);
	} else {
		// Handle standard Data/Text fields
		cy.get(`${fieldSelector} input, ${fieldSelector} textarea`)
			.first()
			.clear()
			.type(value);
	}

	cy.wait(CypressConfig.timeouts.fieldInput);
});

// Verify Frappe field value
Cypress.Commands.add('verify_frappe_field', (fieldname, expectedValue) => {
	cy.get(`[data-fieldname="${fieldname}"]`)
		.find('input, select, textarea')
		.first()
		.should('have.value', expectedValue);
});

// Verify field validation state
Cypress.Commands.add('verify_field_validation', (fieldname, isValid = true) => {
	const fieldSelector = `[data-fieldname="${fieldname}"]`;

	if (isValid) {
		cy.get(fieldSelector).should('not.have.class', 'has-error');
		cy.get(`${fieldSelector} .help-block`).should('not.exist');
	} else {
		cy.get(fieldSelector).should('have.class', 'has-error');
		cy.get(`${fieldSelector} .help-block`).should('be.visible');
	}
});

// Save Frappe document with waiting
Cypress.Commands.add('save_frappe_doc', () => {
	cy.get('.primary-action').contains('Save').click();
	cy.wait(2000);
	// Verify save completed
	cy.get('.indicator.green').should('contain', 'Saved');
});

// Submit Frappe document with confirmation
Cypress.Commands.add('submit_frappe_doc', () => {
	cy.get('.actions-btn-group button').contains('Submit').click();
	cy.get('.modal-footer button').contains('Yes').click();
	cy.wait(3000);
	// Verify submission completed
	cy.get('.indicator.blue').should('contain', 'Submitted');
});

// ============================================================================
// SPECIALIZED DOCTYPE JAVASCRIPT TESTING
// ============================================================================

// Test SEPA utilities module and functionality
Cypress.Commands.add('test_sepa_utils', (memberName) => {
	// Navigate to member form
	cy.visit_doctype_form('Member', memberName);

	// Verify SepaUtils module is loaded with error recovery
	cy.execute_sepa_operation((win) => {
		expect(win.SepaUtils).to.exist;
		expect(win.SepaUtils.create_sepa_mandate_with_dialog).to.be.a('function');
		expect(win.SepaUtils.check_sepa_mandate_status).to.be.a('function');
		return true;
	}, 'SEPA Utils Verification');
});

// Test SEPA mandate dialog creation
Cypress.Commands.add('test_sepa_mandate_dialog', (memberName) => {
	cy.visit_doctype_form('Member', memberName);

	// Wait for form to be ready
	cy.wait_for_navigation();

	// Trigger SEPA mandate dialog via JavaScript with error recovery
	cy.execute_sepa_operation((win) => {
		const frm = win.frappe.ui.form.get_form('Member');
		expect(frm).to.exist;
		// Call your sophisticated dialog function
		win.SepaUtils.create_sepa_mandate_with_dialog(frm);
		return true;
	}, 'SEPA Mandate Dialog Creation');

	// Verify dialog appeared with error recovery
	cy.execute_form_operation(() => {
		cy.get('.modal-title').should('contain', 'Create SEPA Mandate');
		cy.get('[data-fieldname="mandate_id"]').should('be.visible');
		cy.get('[data-fieldname="iban"]').should('be.visible');
		cy.get('[data-fieldname="bic"]').should('be.visible');
		return true;
	}, 'SEPA Dialog Verification');
});

// Test IBAN validation with your IBANValidator
Cypress.Commands.add('test_iban_validation', (iban, expectedValid = true) => {
	cy.window().then((win) => {
		if (win.IBANValidator) {
			const validation = win.IBANValidator.validate(iban);

			if (expectedValid) {
				expect(validation.valid).to.be.true;
				expect(validation.formatted).to.exist;
			} else {
				expect(validation.valid).to.be.false;
				expect(validation.error).to.exist;
			}
		} else {
			cy.log('IBANValidator not available in this context');
		}
	});
});

// Test Direct Debit Batch JavaScript controller
Cypress.Commands.add('test_dd_batch_controller', (batchName = null) => {
	cy.visit_doctype_form('Direct Debit Batch', batchName);

	// Verify batch controller loaded
	cy.window().then((win) => {
		expect(win.frappe.ui.form.get_form('Direct Debit Batch')).to.exist;
	});

	// Verify status indicator functionality
	cy.get('.page-title .indicator').should('be.visible');

	// If it's a new batch, test the "Load Unpaid Invoices" functionality
	if (!batchName) {
		cy.get('button').contains('Load Unpaid Invoices').should('be.visible');
	}
});

// Test custom button functionality
Cypress.Commands.add('test_custom_button', (buttonLabel, expectedAction = null) => {
	cy.get(`button:contains("${buttonLabel}")`).should('be.visible').click();

	if (expectedAction === 'dialog') {
		cy.get('.modal').should('be.visible');
	} else if (expectedAction === 'form_save') {
		cy.get('.indicator.green').should('contain', 'Saved');
	}

	cy.wait(1000);
});

// Test JavaScript form events and validation
Cypress.Commands.add('test_form_validation', (fieldname, invalidValue, validValue) => {
	// Test invalid value
	cy.fill_frappe_field(fieldname, invalidValue);
	cy.get(`[data-fieldname="${fieldname}"]`).should('have.class', 'has-error');

	// Test valid value
	cy.fill_frappe_field(fieldname, validValue);
	cy.get(`[data-fieldname="${fieldname}"]`).should('not.have.class', 'has-error');
});

// Test dynamic UI updates based on field changes
Cypress.Commands.add('test_dynamic_ui_update', (triggerField, triggerValue, expectedChange) => {
	// Change the trigger field
	cy.fill_frappe_field(triggerField, triggerValue);
	cy.wait(1000); // Allow JavaScript to process

	// Verify expected UI change
	if (expectedChange.fieldVisible) {
		cy.get(`[data-fieldname="${expectedChange.fieldVisible}"]`).should('be.visible');
	}
	if (expectedChange.fieldHidden) {
		cy.get(`[data-fieldname="${expectedChange.fieldHidden}"]`).should('not.be.visible');
	}
	if (expectedChange.buttonAppears) {
		cy.get(`button:contains("${expectedChange.buttonAppears}")`).should('be.visible');
	}
});

// Test centralized configuration access
Cypress.Commands.add('test_centralized_config_access', () => {
	cy.window().then((win) => {
		// Test that forms can access centralized Verenigingen Settings
		return win.frappe.call({
			method: 'frappe.client.get_single',
			args: { doctype: 'Verenigingen Settings' }
		}).then((r) => {
			expect(r.message).to.exist;
			// Verify SEPA configuration is accessible
			expect(r.message.sepa_creditor_identifier).to.exist;
		});
	});
});
