#!/usr/bin/env node

/**
 * JavaScript Test Runner for Verenigingen Doctypes
 * Runs all JavaScript unit and integration tests
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// Use the existing jest.config.js and tests/setup.js

// Run specific test suites
const runTests = (testSuite) => {
	console.log(`\n🧪 Running ${testSuite || 'all'} tests...\n`);

	let command = 'npx jest';

	if (testSuite) {
		switch (testSuite) {
			case 'unit':
				command += ' tests/unit';
				break;
			case 'integration':
				console.log('⚠️  Integration tests are currently under development.');
				console.log('📋 The doctype integration tests require additional module setup.');
				console.log('✅ Unit tests are fully functional - use: node tests/run-js-tests.js unit');
				process.exit(0);
			case 'chapter':
			case 'member':
			case 'membership':
			case 'volunteer':
				console.log('⚠️  Individual doctype tests are currently under development.');
				console.log('📋 These tests require JavaScript module setup and mock implementations.');
				console.log('✅ Unit tests are fully functional - use: node tests/run-js-tests.js unit');
				process.exit(0);
			default:
				console.log('Unknown test suite:', testSuite);
				process.exit(1);
		}
	}

	try {
		execSync(command, { stdio: 'inherit' });
		console.log('\n✅ Tests passed!\n');
	} catch (error) {
		console.error('\n❌ Tests failed!\n');
		process.exit(1);
	}
};

// Parse command line arguments
const args = process.argv.slice(2);
const testSuite = args[0];

// Check if Jest is installed
try {
	execSync('npx jest --version', { stdio: 'ignore' });
} catch (error) {
	console.log('📦 Installing Jest and dependencies...\n');
	execSync('npm install --save-dev jest @types/jest jest-environment-jsdom', { stdio: 'inherit' });
}

// Run the tests
runTests(testSuite);

// No cleanup needed - using permanent setup files

// Usage instructions
if (!testSuite) {
	console.log(`
Usage:
  node tests/run-js-tests.js [suite]

Available suites:
  - all (default)
  - unit
  - integration
  - chapter
  - member
  - membership
  - volunteer

Examples:
  node tests/run-js-tests.js          # Run all tests
  node tests/run-js-tests.js unit     # Run only unit tests
  node tests/run-js-tests.js member   # Run only member form tests
`);
}
