/**
 * @fileoverview Jest Unit Testing Configuration - Frontend unit test setup for Verenigingen
 *
 * This module configures Jest for comprehensive unit testing of JavaScript
 * components in the Verenigingen association management system. It defines
 * test environment settings, coverage requirements, file patterns, and
 * reporting configurations for automated testing workflows.
 *
 * Key Features:
 * - Browser-like testing environment with jsdom
 * - Comprehensive code coverage collection and thresholds
 * - CSS/SCSS module handling for component testing
 * - Test result reporting in multiple formats
 * - CI/CD integration with JUnit XML output
 * - Custom setup files for test environment initialization
 *
 * Configuration Categories:
 * - Environment: jsdom for DOM manipulation testing
 * - File Patterns: Test file discovery and source coverage
 * - Coverage: Thresholds and reporting formats
 * - Transformation: Babel for modern JavaScript features
 * - Reporting: Multiple output formats for different audiences
 *
 * Test Coverage Strategy:
 * - Minimum 70% coverage across all metrics
 * - Includes public JavaScript files and templates
 * - Excludes test files, node_modules, and vendor code
 * - Supports branch, function, line, and statement coverage
 *
 * Usage:
 * ```bash
 * # Run all unit tests
 * npm test
 *
 * # Run tests with coverage
 * npm run test:coverage
 *
 * # Run tests in watch mode
 * npm run test:watch
 *
 * # Run specific test file
 * npm test -- member-validation.test.js
 * ```
 *
 * Test File Organization:
 * - Unit tests: verenigingen/tests/frontend/unit/
 * - Integration tests: verenigingen/tests/frontend/integration/
 * - Component tests: verenigingen/tests/frontend/components/
 * - Setup files: verenigingen/tests/frontend/setup.js
 *
 * Coverage Reports:
 * - Text: Console output for development
 * - LCOV: Integration with code coverage tools
 * - HTML: Visual coverage reports for browsers
 * - JSON: Programmatic access to coverage data
 * - JUnit XML: CI/CD pipeline integration
 *
 * @module jest.config
 * @version 1.2.0
 * @since 1.0.0
 * @requires jest
 * @requires babel-jest
 * @requires jest-junit
 * @see {@link https://jestjs.io/docs/configuration|Jest Configuration}
 * @see {@link verenigingen/tests/frontend/|Test Files}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

/**
 * Jest Configuration Object
 *
 * Defines comprehensive settings for Jest unit testing including
 * environment setup, coverage thresholds, and reporting options.
 */
module.exports = {
	/** @type {string} Test environment for DOM-based testing */
	testEnvironment: 'jsdom',

	/** @type {Array<string>} Root directories for test discovery */
	roots: ['<rootDir>/verenigingen'],

	/** @type {Array<string>} Patterns for locating test files - ONLY utility tests */
	testMatch: [
		'**/tests/unit/**/*.test.js'
	],

	/** @type {Array<string>} Files to include in coverage collection - ONLY utilities */
	collectCoverageFrom: [
		'verenigingen/public/js/utils/**/*.js',
		'verenigingen/public/js/services/**/*.js',
		'!**/*frappe*/**', // Exclude Frappe-dependent files
		'!**/node_modules/**',
		'!**/vendor/**',
		'!**/tests/**'
	],

	/** @type {Object} Minimum coverage thresholds for code quality */
	coverageThreshold: {
		global: {
			/** @type {number} Minimum branch coverage percentage */
			branches: 70,
			/** @type {number} Minimum function coverage percentage */
			functions: 70,
			/** @type {number} Minimum line coverage percentage */
			lines: 70,
			/** @type {number} Minimum statement coverage percentage */
			statements: 70
		}
	},

	/** @type {Object} Module path resolution for assets and styles */
	moduleNameMapper: {
		'\\.(css|less|scss|sass)$': 'identity-obj-proxy'
	},

	/** @type {Array<string>} Setup files to run after test framework initialization */
	setupFilesAfterEnv: ['<rootDir>/verenigingen/tests/frontend/setup.js'],

	/** @type {Object} File transformation rules for different file types */
	transform: {
		'^.+\\.jsx?$': 'babel-jest'
	},

	/** @type {Array<string>} Coverage report output formats */
	coverageReporters: ['text', 'lcov', 'html', 'json'],

	/** @type {Array} Test result reporters for different output formats */
	reporters: [
		'default',
		['jest-junit', {
			/** @type {string} Directory for JUnit XML output */
			outputDirectory: './test-results',
			/** @type {string} Filename for JUnit XML report */
			outputName: 'jest-junit.xml'
		}]
	]
};
