/**
 * @fileoverview Global Frontend Test Setup Configuration
 *
 * This module provides global setup configuration for frontend JavaScript tests
 * in the Verenigingen application. It mocks external dependencies, provides
 * global utilities, and ensures consistent test environment across all test suites.
 *
 * Business Context:
 * - Frontend tests validate user interface functionality and business logic
 * - Tests need isolated environment without external dependencies
 * - Consistent mocking ensures reliable and predictable test results
 * - Global setup reduces boilerplate code in individual test files
 *
 * Mock Components:
 * - Frappe framework translation function (__)
 * - jQuery DOM manipulation library with chainable methods
 * - Moment.js date manipulation library
 * - Global form object (cur_frm) for Frappe form tests
 *
 * Test Environment Features:
 * - Isolated test execution without external API calls
 * - Predictable mock responses for consistent testing
 * - Chainable jQuery mock methods for DOM testing
 * - Date handling mocks for time-sensitive tests
 *
 * Usage:
 * - Automatically loaded by Jest test runner
 * - Provides global mocks available in all test files
 * - Ensures consistent test environment setup
 * - Reduces test setup complexity
 *
 * @module verenigingen/tests/frontend/setup
 * @version 1.0.0
 * @since 2024
 * @requires jest
 * @see {@link https://jestjs.io/docs/configuration#setupfilesafterenv|Jest Setup Files}
 */

// Global test setup
global.__ = jest.fn(str => str);
global.cur_frm = {};

// Mock jQuery globally
global.$ = jest.fn(() => ({
	html: jest.fn(),
	on: jest.fn(),
	off: jest.fn().mockReturnThis(),
	find: jest.fn().mockReturnThis(),
	addClass: jest.fn().mockReturnThis(),
	removeClass: jest.fn().mockReturnThis(),
	val: jest.fn(),
	prop: jest.fn().mockReturnThis(),
	toggle: jest.fn(),
	show: jest.fn(),
	hide: jest.fn()
}));

// Mock moment if used
global.moment = jest.fn((date) => ({
	format: jest.fn(() => date || '2024-01-01'),
	diff: jest.fn(() => 0),
	add: jest.fn().mockReturnThis(),
	subtract: jest.fn().mockReturnThis()
}));
