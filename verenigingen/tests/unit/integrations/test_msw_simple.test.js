/**
 * Simple MSW test to verify setup
 */

const {
	setupTestMocks,
	cleanupTestMocks
} = require('../../setup/frappe-mocks');

// Initialize test environment
setupTestMocks();

describe('MSW Basic Setup Test', () => {
	beforeEach(() => {
		cleanupTestMocks();
		setupTestMocks();
	});

	afterEach(() => {
		cleanupTestMocks();
	});

	it('should run basic test without MSW first', () => {
		expect(true).toBe(true);
	});

	it('should test fetch availability', () => {
		expect(typeof fetch).toBe('function');
	});
});
