/**
 * @fileoverview MSW Setup Utility
 *
 * Provides MSW server setup and teardown functions that can be called
 * explicitly by tests that need HTTP mocking. This approach avoids
 * loading MSW for all tests.
 *
 * @author Verenigingen Development Team
 * @version 2025-08-26
 */

const { server } = require('./msw-server');

/**
 * Setup MSW for tests that need HTTP mocking
 * Call this in beforeAll() of test suites that need MSW
 */
function setupMSW() {
	server.listen({ onUnhandledRequest: 'warn' });
}

/**
 * Reset MSW handlers between tests
 * Call this in afterEach() of test suites using MSW
 */
function resetMSW() {
	server.resetHandlers();
}

/**
 * Cleanup MSW after tests
 * Call this in afterAll() of test suites using MSW
 */
function teardownMSW() {
	server.close();
}

module.exports = {
	server,
	setupMSW,
	resetMSW,
	teardownMSW
};
