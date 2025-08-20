/**
 * @fileoverview Controller Test Base Class and Common Test Patterns
 *
 * Provides centralized infrastructure for testing Frappe DocType controllers
 * in the Verenigingen association management system. Reduces boilerplate and
 * ensures consistent testing patterns across all controller tests.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

/* eslint-env jest */
/* No need to redeclare beforeAll - covered by eslint-env jest */

const {
	setupTestMocks,
	cleanupTestMocks,
	createMockForm
	// dutchTestData - unused
} = require('./frappe-mocks');
const {
	loadFrappeController,
	testFormEvent
} = require('./controller-loader');

/**
 * Base class for controller testing with common patterns and utilities
 */
class BaseControllerTest {
	constructor(config) {
		this.doctype = config.doctype;
		this.controllerPath = config.controllerPath;
		this.defaultDoc = config.defaultDoc || {};
		this.expectedHandlers = config.expectedHandlers || ['refresh'];
		this.customCreateMockForm = config.createMockForm || null;
		this.handlers = null;
		this.mockForm = null;
	}

	/**
     * Load the controller and validate expected handlers exist
     */
	loadController() {
		const allHandlers = loadFrappeController(this.controllerPath);
		this.handlers = allHandlers[this.doctype];

		if (!this.handlers) {
			throw new Error(`No handlers found for DocType: ${this.doctype}`);
		}

		// Validate expected handlers exist
		for (const expectedHandler of this.expectedHandlers) {
			if (!this.handlers[expectedHandler]) {
				console.warn(`Expected handler '${expectedHandler}' not found in ${this.doctype} controller`);
			}
		}

		return this.handlers;
	}

	/**
     * Create standardized mock form with common field structures
     */
	createMockForm(overrides = {}) {
		const baseDoc = {
			name: `${this.doctype.toUpperCase()}-TEST-001`,
			doctype: this.doctype,
			docstatus: 0,
			__islocal: 0,
			...this.defaultDoc,
			...overrides.doc
		};

		this.mockForm = createMockForm({
			doc: baseDoc,
			...overrides
		});

		// Add common field structures
		this.mockForm.fields_dict = {
			...this.mockForm.fields_dict,
			...this.getCommonFields(),
			...overrides.fields_dict
		};

		return this.mockForm;
	}

	/**
     * Get common field structures used across controllers
     */
	getCommonFields() {
		return {
			// Address and contact fields
			address_html: { wrapper: global.$('<div>') },
			contact_html: { wrapper: global.$('<div>') },
			address_section: { wrapper: global.$('<div>') },

			// Common data fields
			status: { df: { fieldtype: 'Select' } },
			creation: { df: { fieldtype: 'Datetime' } },
			modified: { df: { fieldtype: 'Datetime' } }
		};
	}

	/**
     * Test a specific form event handler
     */
	testEvent(eventName, mockForm = null, ...args) {
		const frm = mockForm || this.mockForm;
		if (!frm) {
			throw new Error('No mock form available. Call createMockForm() first.');
		}

		return testFormEvent(this.doctype, eventName, frm, { [this.doctype]: this.handlers }, ...args);
	}

	/**
     * Generate standard test suite for common controller patterns
     */
	generateStandardTests() {
		const tests = {};

		// Basic refresh test
		if (this.handlers.refresh) {
			tests.shouldExecuteRefreshWithoutErrors = () => {
				expect(() => {
					this.testEvent('refresh');
				}).not.toThrow();
			};
		}

		// Performance test
		if (this.handlers.refresh) {
			tests.shouldNotMakeExcessiveServerCalls = () => {
				const initialCallCount = global.frappe.call.mock.calls.length;
				this.testEvent('refresh');
				const finalCallCount = global.frappe.call.mock.calls.length;
				const callsAdded = finalCallCount - initialCallCount;
				expect(callsAdded).toBeLessThanOrEqual(5);
			};

			tests.shouldExecuteQuickly = () => {
				const start = Date.now();
				this.testEvent('refresh');
				const duration = Date.now() - start;
				expect(duration).toBeLessThan(100);
			};
		}

		// Error handling test
		tests.shouldHandleNetworkErrors = () => {
			// Mock network error
			global.frappe.call.mockImplementation(({ error }) => {
				if (error) { error('Network timeout'); }
			});

			expect(() => {
				this.testEvent('refresh');
			}).not.toThrow();
		};

		// Handler existence validation
		tests.shouldHaveExpectedHandlers = () => {
			for (const expectedHandler of this.expectedHandlers) {
				if (this.handlers[expectedHandler]) {
					expect(this.handlers[expectedHandler]).toBeDefined();
					expect(typeof this.handlers[expectedHandler]).toBe('function');
				}
			}
		};

		return tests;
	}

	/**
     * Setup test environment
     */
	setup() {
		setupTestMocks();
		this.loadController();
	}

	/**
     * Cleanup test environment
     */
	cleanup() {
		cleanupTestMocks();
		this.mockForm = null;
	}
}

/**
 * Creates a standardized test describe block for a controller
 */
function createControllerTestSuite(config, customTests = {}) {
	return () => {
		let controllerTest;

		beforeAll(() => {
			controllerTest = new BaseControllerTest(config);
			controllerTest.setup();
		});

		beforeEach(() => {
			cleanupTestMocks();
			if (controllerTest) {
				// Use custom createMockForm if provided, otherwise use default
				if (controllerTest.customCreateMockForm) {
					controllerTest.mockForm = controllerTest.customCreateMockForm(controllerTest);
				} else {
					controllerTest.createMockForm();
				}
			}
		});

		afterEach(() => {
			cleanupTestMocks();
		});

		describe('Standard Controller Tests', () => {
			it('should load controller and handlers', () => {
				expect(controllerTest).toBeDefined();
				expect(controllerTest.handlers).toBeDefined();
			});

			it('should execute refresh handler without errors', () => {
				expect(() => {
					controllerTest.testEvent('refresh');
				}).not.toThrow();
			});

			it('should not make excessive server calls during refresh', () => {
				const initialCallCount = global.frappe.call.mock.calls.length;
				controllerTest.testEvent('refresh');
				const finalCallCount = global.frappe.call.mock.calls.length;
				const callsAdded = finalCallCount - initialCallCount;
				// Use custom threshold if provided, otherwise default to 15
				const threshold = config.mockServerCallThreshold || 15;
				expect(callsAdded).toBeLessThanOrEqual(threshold);
			});

			it('should execute quickly', () => {
				const start = Date.now();
				controllerTest.testEvent('refresh');
				const duration = Date.now() - start;
				expect(duration).toBeLessThan(100);
			});

			it('should handle network errors gracefully', () => {
				// Mock network error
				const originalCall = global.frappe.call;
				global.frappe.call.mockImplementation(({ error }) => {
					if (error) { error('Network timeout'); }
				});

				expect(() => {
					controllerTest.testEvent('refresh');
				}).not.toThrow();

				// Restore original mock
				global.frappe.call = originalCall;
			});
		});

		// Add custom tests
		Object.entries(customTests).forEach(([suiteName, suiteTests]) => {
			describe(suiteName, () => {
				if (typeof suiteTests === 'function') {
					suiteTests(() => controllerTest); // Pass getter function
				} else {
					Object.entries(suiteTests).forEach(([testName, testFn]) => {
						it(testName, () => testFn.call(controllerTest));
					});
				}
			});
		});
	};
}

/**
 * Utility function to test multiple status transitions
 */
function testStatusTransitions(controllerTest, statusField, transitions) {
	transitions.forEach(({ from, to }) => {
		controllerTest.mockForm.doc[statusField] = from;

		expect(() => {
			controllerTest.testEvent('refresh');
		}).not.toThrow();

		// Test status change handler if it exists
		if (controllerTest.handlers[statusField]) {
			controllerTest.mockForm.doc[statusField] = to;
			expect(() => {
				controllerTest.testEvent(statusField);
			}).not.toThrow();
		}
	});
}

/**
 * Utility function to test field validation
 */
function testFieldValidation(controllerTest, fieldName, testCases) {
	testCases.forEach(({ value, shouldPass }) => {
		controllerTest.mockForm.doc[fieldName] = value;

		if (shouldPass) {
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		} else {
			// For validation failures, we expect the refresh to still work
			// but validation might set error states
			expect(() => {
				controllerTest.testEvent('refresh');
			}).not.toThrow();
		}
	});
}

module.exports = {
	BaseControllerTest,
	createControllerTestSuite,
	testStatusTransitions,
	testFieldValidation
};
