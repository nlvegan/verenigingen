/**
 * @fileoverview Playwright Configuration for Mollie Donation E2E Testing
 *
 * This configuration file sets up Playwright for comprehensive end-to-end
 * testing of the Mollie donation flow and related payment processing.
 *
 * Key Features:
 * - Development environment integration (dev.veganisme.net)
 * - Multiple browser testing (Chrome, Firefox, Safari)
 * - Test data isolation and cleanup
 * - Video recording and screenshot capture
 * - Comprehensive logging and reporting
 * - CI/CD pipeline integration
 *
 * @module PlaywrightConfig
 * @version 1.0.0
 * @requires @playwright/test
 */

const { defineConfig, devices } = require('@playwright/test');

/**
 * Playwright Test Configuration
 *
 * Comprehensive configuration for E2E testing of the Verenigingen
 * donation system with Mollie payment integration.
 */
module.exports = defineConfig({
	// Test directory configuration
	testDir: './tests/e2e',

	// Global test timeout (2 minutes for complex donation flows)
	timeout: 120 * 1000,

	// Expect timeout for assertions
	expect: {
		timeout: 10 * 1000
	},

	// Test execution configuration
	fullyParallel: false, // Run tests sequentially to avoid database conflicts
	forbidOnly: !!process.env.CI, // Fail CI if test.only is used
	retries: process.env.CI ? 2 : 1, // Retry failed tests in CI
	workers: process.env.CI ? 2 : 1, // Limit workers to avoid overwhelming test DB

	// Reporting configuration
	reporter: [
		['html', { outputFolder: 'test-results/html-report' }],
		['json', { outputFile: 'test-results/test-results.json' }],
		['junit', { outputFile: 'test-results/junit.xml' }],
		process.env.CI ? ['github'] : ['list']
	],

	// Global test configuration
	use: {
		// Base URL for the development environment
		baseURL: 'https://dev.veganisme.net',

		// Browser configuration
		headless: true, // Always headless by default
		viewport: { width: 1400, height: 960 },

		// Network and timeout settings
		navigationTimeout: 30 * 1000,
		actionTimeout: 10 * 1000,

		// Test artifacts
		screenshot: 'only-on-failure',
		video: process.env.CI ? 'retain-on-failure' : 'off',
		trace: 'retain-on-failure',

		// Additional context options
		ignoreHTTPSErrors: true, // For development environment

		// User agent for test identification
		userAgent: 'PlaywrightE2E/1.0 (Verenigingen Test Suite)'
	},

	// Project configuration for different browsers and scenarios
	projects: [
		{
			name: 'setup',
			testMatch: /.*\.setup\.js/,
			teardown: 'cleanup'
		},

		{
			name: 'cleanup',
			testMatch: /.*\.cleanup\.js/
		},

		{
			name: 'mollie-donation-chrome',
			use: {
				...devices['Desktop Chrome'],
				// Chrome-specific overrides for Mollie testing
				launchOptions: {
					args: [
						'--disable-web-security', // For CORS in test environment
						'--ignore-certificate-errors', // For dev SSL
						'--no-sandbox' // For CI environment
					]
				}
			},
			dependencies: ['setup'],
			testMatch: /mollie-donation-flow\.spec\.js/
		},

		{
			name: 'mollie-donation-firefox',
			use: {
				...devices['Desktop Firefox'],
				// Firefox-specific configuration
				launchOptions: {
					firefoxUserPrefs: {
						'security.tls.insecure_fallback_hosts': 'dev.veganisme.net',
						'security.tls.skip_ocsp_for_issuers': true
					}
				}
			},
			dependencies: ['setup'],
			testMatch: /mollie-donation-flow\.spec\.js/
		},

		{
			name: 'mollie-donation-mobile',
			use: {
				...devices['iPhone 13'],
				// Mobile-specific viewport for responsive testing
				viewport: { width: 390, height: 844 }
			},
			dependencies: ['setup'],
			testMatch: /mollie-donation-flow\.spec\.js/
		},

		{
			name: 'webhook-comprehensive',
			use: { ...devices['Desktop Chrome'] },
			dependencies: ['setup'],
			testMatch: /webhook-.*\.spec\.js/
		},

		{
			name: 'performance-testing',
			use: {
				...devices['Desktop Chrome'],
				// Performance testing specific configuration
				video: 'off',
				screenshot: 'off'
			},
			dependencies: ['setup'],
			testMatch: /performance-.*\.spec\.js/
		}
	],

	// Global setup and teardown
	globalSetup: require.resolve('./tests/support/global-setup.js'),
	globalTeardown: require.resolve('./tests/support/global-teardown.js'),

	// Web server configuration (if needed to start dev server)
	webServer: process.env.START_DEV_SERVER
		? {
				command: 'bench start --skip-redis-config-generation',
				port: 8000,
				timeout: 120 * 1000,
				reuseExistingServer: !process.env.CI
			}
		: undefined,

	// Test output directory
	outputDir: 'test-results/playwright-output',

	// Metadata for test runs
	metadata: {
		environment: process.env.NODE_ENV || 'development',
		baseURL: 'https://dev.veganisme.net',
		testType: 'e2e-mollie-integration',
		version: require('./package.json').version || '1.0.0',
		timestamp: new Date().toISOString()
	}
});
