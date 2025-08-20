/**
 * @fileoverview Jest Configuration for API Contract Testing
 * 
 * Specialized Jest configuration for running API contract tests
 * alongside controller tests with proper environment setup.
 * 
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const baseConfig = require('./jest.config');

module.exports = {
    ...baseConfig,
    
    // Test identification
    displayName: 'API Contract Tests',
    
    // Test file patterns - include API contract tests
    testMatch: [
        '**/tests/setup/**/api-contract*.test.js',
        '**/tests/unit/**/test_*_api_contracts.test.js',
        '**/tests/integration/**/api-*.test.js'
    ],
    
    // Setup files for API contract testing
    setupFilesAfterEnv: [
        '<rootDir>/tests/setup/frappe-mocks.js',
        '<rootDir>/tests/setup/api-contract-setup.js'
    ],
    
    // Test environment with network mocking support
    testEnvironment: 'node',
    
    // Module mapping for API contract dependencies
    moduleNameMapping: {
        '^@/(.*)$': '<rootDir>/$1',
        '^verenigingen/(.*)$': '<rootDir>/verenigingen/$1',
        '^tests/(.*)$': '<rootDir>/tests/$1'
    },
    
    // Extended timeout for API contract validation
    testTimeout: 15000,
    
    // Coverage configuration including API contract code
    collectCoverageFrom: [
        ...baseConfig.collectCoverageFrom,
        'tests/setup/api-contract-*.js',
        '!tests/setup/api-contract-example.test.js'
    ],
    
    // Test environment variables for API contract testing
    setupFiles: [
        '<rootDir>/tests/setup/api-contract-env.js'
    ],
    
    // Global configuration for API contract tests
    globals: {
        'process.env': {
            NODE_ENV: 'test',
            API_CONTRACT_TESTING: 'true',
            DEBUG_API_CONTRACTS: process.env.DEBUG_API_CONTRACTS || 'false'
        }
    },
    
    // Transform configuration for MSW and other dependencies
    transformIgnorePatterns: [
        'node_modules/(?!(msw|@mswjs)/)'
    ],
    
    // Module directories including node_modules for MSW
    moduleDirectories: [
        'node_modules',
        '<rootDir>',
        '<rootDir>/tests'
    ],
    
    // Custom matchers and utilities
    testEnvironmentOptions: {
        url: 'http://localhost'
    },
    
    // Verbose output for debugging API contracts
    verbose: process.env.DEBUG_API_CONTRACTS === 'true'
};