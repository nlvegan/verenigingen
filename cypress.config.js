/**
 * @fileoverview Cypress End-to-End Testing Configuration - E2E test setup for Verenigingen
 *
 * This module configures Cypress for comprehensive end-to-end testing of the
 * Verenigingen association management system. It defines test environment
 * settings, browser configurations, timeout values, and custom behaviors
 * for automated browser testing.
 *
 * Key Features:
 * - Development environment integration (dev.veganisme.net)
 * - Optimized viewport and timeout settings
 * - Video recording for test analysis
 * - Code coverage integration
 * - Custom task definitions
 * - Retry mechanisms for flaky tests
 * - Experimental features support
 *
 * Configuration Categories:
 * - Environment: Base URL, viewport dimensions, timeouts
 * - Recording: Video capture settings and upload policies
 * - Reliability: Retry strategies for different execution modes
 * - Integration: Code coverage and custom task support
 * - File Organization: Spec patterns and support file locations
 *
 * Testing Strategy:
 * - Integration tests for critical user workflows
 * - Member application and management testing
 * - Volunteer expense processing validation
 * - Chapter and organization management flows
 * - Payment and donation processing verification
 *
 * Usage:
 * ```bash
 * # Run all E2E tests
 * npx cypress run
 *
 * # Open interactive test runner
 * npx cypress open
 *
 * # Run specific test file
 * npx cypress run --spec "cypress/integration/member_application.spec.js"
 * ```
 *
 * Custom Tasks:
 * - log: Console logging for debugging test execution
 * - Code coverage collection and reporting
 * - Custom data setup and cleanup utilities
 *
 * Environment Requirements:
 * - Cypress framework installed
 * - Development server running on dev.veganisme.net:8000
 * - Test data and user accounts configured
 * - Code coverage plugins configured
 *
 * @module cypress.config
 * @version 1.1.0
 * @since 1.0.0
 * @requires cypress
 * @requires @cypress/code-coverage
 * @see {@link https://docs.cypress.io/guides/references/configuration|Cypress Configuration}
 * @see {@link cypress/integration/|Test Specifications}
 * @see {@link cypress/support/|Support Files}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

const { defineConfig } = require('cypress');

/**
 * Cypress Configuration Object
 *
 * Defines comprehensive settings for Cypress E2E testing including
 * environment setup, browser configuration, and custom behaviors.
 */
module.exports = defineConfig({
  /** @type {string} Cypress project identifier for dashboard integration */
  projectId: 'verenigingen-tests',

  /** @type {number} Browser viewport height in pixels for consistent testing */
  viewportHeight: 960,

  /** @type {number} Browser viewport width in pixels for responsive testing */
  viewportWidth: 1400,

  /** @type {number} Default timeout for Cypress commands in milliseconds */
  defaultCommandTimeout: 20000,

  /** @type {number} Page load timeout for slow development environment */
  pageLoadTimeout: 15000,

  /** @type {boolean} Enable video recording for test debugging */
  video: true,

  /** @type {boolean} Only upload videos on test failures to save storage */
  videoUploadOnPasses: false,

  /** @type {Object} Retry configuration for different execution modes */
  retries: {
    /** @type {number} Retry failed tests 2 times in CI/headless mode */
    runMode: 2,
    /** @type {number} No retries in interactive mode for debugging */
    openMode: 0,
  },

  /** @type {Object} End-to-end testing specific configuration */
  e2e: {
    /** @type {string} Base URL for the Verenigingen development environment */
    baseUrl: 'http://dev.veganisme.net:8000',

    /** @type {string} Pattern for locating test specification files */
    specPattern: 'cypress/integration/**/*.js',

    /** @type {string} Support file with global commands and utilities */
    supportFile: 'cypress/support/index.js',

    /** @type {boolean} Enable Cypress Studio for test recording */
    experimentalStudio: true,

    /**
     * Configure Node.js event handlers and custom tasks
     *
     * @param {Function} on - Event handler registration function
     * @param {Object} config - Cypress configuration object
     * @returns {Object} Modified configuration object
     */
    setupNodeEvents(on, config) {
      // Setup code coverage collection and reporting
      require('@cypress/code-coverage/task')(on, config);

      // Register custom tasks for enhanced testing capabilities
      on('task', {
        /**
         * Custom logging task for debugging test execution
         *
         * @param {string} message - Message to log to console
         * @returns {null} Required return value for Cypress tasks
         */
        log(message) {
          console.log(message);
          return null;
        },
      });

      return config;
    },
  },
});
