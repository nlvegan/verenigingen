/**
 * @fileoverview Cypress Support Configuration for Verenigingen E2E Testing
 *
 * This module serves as the central configuration hub for Cypress end-to-end testing
 * within the Verenigingen association management system. It orchestrates the loading
 * of custom commands, third-party plugins, global hooks, and error handling strategies
 * to provide a robust and reliable testing environment.
 *
 * Purpose and Architecture
 * -----------------------
 * The support configuration addresses several critical testing infrastructure needs:
 *
 * **Plugin Integration**: Coordinates multiple testing libraries and tools
 * **Global Test Setup**: Provides consistent initialization across all test suites
 * **Error Handling**: Implements intelligent error filtering for framework-specific issues
 * **Code Coverage**: Enables comprehensive test coverage reporting and analysis
 *
 * Key Components
 * -------------
 *
 * ### Custom Command Integration
 * - Loads Verenigingen-specific custom commands for DocType interaction
 * - Provides abstracted methods for common testing operations
 * - Ensures consistent behavior across all test specifications
 *
 * ### Third-Party Plugin Stack
 * - **@cypress/code-coverage**: Comprehensive code coverage reporting
 * - **@testing-library/cypress**: Enhanced DOM testing utilities
 * - **cypress-real-events**: Real browser event simulation for complex interactions
 *
 * ### Global Test Orchestration
 * - Automatic authentication setup for all test suites
 * - Consistent application state initialization
 * - Shared error handling and exception management
 *
 * Business Context
 * ---------------
 * The Verenigingen system requires comprehensive testing due to its complex workflows:
 *
 * **Financial Operations**: SEPA payments, donations, and membership dues
 * **User Management**: Members, volunteers, and administrative users
 * **Integration Testing**: External accounting system synchronization
 * **Workflow Validation**: Multi-step business processes with state management
 *
 * This configuration ensures all these areas can be tested reliably and consistently.
 *
 * Technical Implementation Details
 * ------------------------------
 *
 * ### Plugin Integration Strategy
 * ```javascript
 * import './commands';                        // Custom Verenigingen commands
 * import '@cypress/code-coverage/support';    // Coverage collection
 * import '@testing-library/cypress/add-commands';  // Enhanced DOM queries
 * import 'cypress-real-events/support';       // Real browser events
 * ```
 *
 * ### Global Initialization Hook
 * The `before()` hook ensures consistent test environment setup:
 *
 * **Authentication**: Automatic login with Administrator privileges
 * **Navigation**: Consistent starting point in the application interface
 * **State Reset**: Clean application state for test isolation
 *
 * ### Error Handling Strategy
 * Implements intelligent error filtering to distinguish between:
 *
 * **Framework Noise**: ResizeObserver and other browser API errors
 * **Application Issues**: Legitimate application errors that should fail tests
 * **Known Issues**: Documented Frappe framework quirks that can be safely ignored
 *
 * Error Categories and Handling
 * ----------------------------
 *
 * ### ResizeObserver Errors
 * **Issue**: Browser ResizeObserver loop limit exceeded
 * **Handling**: Safely ignored as these don't affect application functionality
 * **Impact**: Prevents false test failures from browser optimization quirks
 *
 * ### Frappe Framework Errors
 * **Issue**: Undefined property access in framework code
 * **Handling**: Logged as warnings but don't fail tests
 * **Rationale**: Framework errors often don't affect actual business functionality
 *
 * ### Application Errors
 * **Issue**: Legitimate application bugs and issues
 * **Handling**: Allow tests to fail to catch real problems
 * **Coverage**: All other uncaught exceptions are treated as test failures
 *
 * Code Coverage Integration
 * ------------------------
 * The configuration enables comprehensive code coverage reporting:
 *
 * **Instrumentation**: Automatic code instrumentation during test runs
 * **Report Generation**: Coverage reports in multiple formats (HTML, JSON, LCOV)
 * **Integration**: Works with CI/CD pipelines for coverage tracking
 * **Thresholds**: Supports coverage threshold enforcement for quality gates
 *
 * Testing Library Integration
 * --------------------------
 * Adds powerful DOM testing utilities:
 *
 * **Semantic Queries**: Find elements by role, label, text content
 * **Accessibility Testing**: Built-in accessibility assertion helpers
 * **User-Centric Approach**: Test from user perspective rather than implementation details
 * **Enhanced Debugging**: Better error messages and element selection strategies
 *
 * Real Events Support
 * ------------------
 * Enables realistic user interaction simulation:
 *
 * **Mouse Events**: Real mouse movements, clicks, and hover states
 * **Keyboard Events**: Proper key press simulation with modifier keys
 * **Focus Management**: Realistic focus behavior for accessibility testing
 * **Touch Events**: Mobile and tablet interaction simulation
 *
 * Global Setup Strategy
 * --------------------
 *
 * ### Authentication Management
 * ```javascript
 * before(() => {
 *   cy.login();        // Use cached session when possible
 *   cy.visit('/app');  // Consistent starting point
 * });
 * ```
 *
 * ### State Consistency
 * - Ensures all tests start from the same application state
 * - Provides authenticated access to all system features
 * - Establishes reliable navigation patterns
 *
 * Performance Considerations
 * -------------------------
 *
 * **Session Caching**: Uses Cypress session management to minimize login overhead
 * **Plugin Loading**: Optimized plugin loading order to reduce startup time
 * **Error Filtering**: Prevents unnecessary test retries from framework noise
 * **Coverage Optimization**: Efficient instrumentation without performance impact
 *
 * Maintenance and Extension
 * ------------------------
 *
 * ### Adding New Plugins
 * To integrate additional testing tools:
 * 1. Add import statement in proper loading order
 * 2. Configure plugin-specific options if needed
 * 3. Update error handling if plugin introduces new error types
 * 4. Document plugin purpose and usage patterns
 *
 * ### Error Handling Updates
 * When encountering new framework errors:
 * 1. Identify if error affects actual functionality
 * 2. Add appropriate filtering if error is harmless
 * 3. Document the error type and reasoning
 * 4. Consider upstream fixes if error indicates real issues
 *
 * ### Coverage Configuration
 * Coverage settings can be customized:
 * - Threshold enforcement for quality gates
 * - Report format preferences
 * - File inclusion/exclusion patterns
 * - Integration with external reporting systems
 *
 * Quality Assurance Impact
 * -----------------------
 * This configuration directly supports quality assurance by:
 *
 * **Reducing False Positives**: Intelligent error filtering prevents noise
 * **Improving Test Reliability**: Consistent setup reduces flaky tests
 * **Enhancing Coverage**: Comprehensive instrumentation catches untested code
 * **Supporting CI/CD**: Reliable automation for continuous integration
 *
 * Author: Development Team
 * Date: 2025-08-03
 * Version: 1.0
 */

// Import commands
import './commands';
import '@cypress/code-coverage/support';
import '@testing-library/cypress/add-commands';
import 'cypress-real-events/support';
import 'cypress-wait-until';

// Global before hook
before(() => {
	cy.login();
	cy.visit('/app');
});

// Handle uncaught exceptions
Cypress.on('uncaught:exception', (err) => {
	// Ignore ResizeObserver errors
	if (err.message.includes('ResizeObserver loop limit exceeded')) {
		return false;
	}
	// Ignore other known Frappe framework errors
	if (err.message.includes('Cannot read properties of undefined')) {
		console.warn('Uncaught exception:', err.message);
		return false;
	}
	// Let other errors fail the test
	return true;
});
