/**
 * @fileoverview API Contract Testing Setup
 * 
 * Global setup for API contract testing including server initialization,
 * mock configuration, and test environment preparation.
 * 
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { APIContractTestServer } = require('./api-contract-testing');

// Global API contract server instance
let globalApiServer = null;

/**
 * Setup API contract testing environment
 * Called once before all tests run
 */
function setupAPIContractTesting() {
    // Initialize global API contract server
    globalApiServer = new APIContractTestServer();
    
    // Store reference for cleanup
    global.__API_CONTRACT_SERVER__ = globalApiServer;
    
    // Start server for all tests
    globalApiServer.start();
    
    // Setup global fetch mock for Node.js environment
    if (typeof fetch === 'undefined') {
        global.fetch = require('node-fetch');
    }
    
    // Enhanced frappe.call mock for contract validation
    const originalFrappeCall = global.frappe?.call;
    
    if (global.frappe) {
        global.frappe.call = jest.fn((options) => {
            // Store original call details for contract validation
            if (!global.__API_CALLS__) {
                global.__API_CALLS__ = [];
            }
            
            global.__API_CALLS__.push({
                method: options.method,
                args: options.args || {},
                timestamp: Date.now()
            });
            
            // Call original implementation if available
            if (originalFrappeCall) {
                return originalFrappeCall.call(global.frappe, options);
            }
            
            // Default mock behavior
            if (options.callback) {
                setImmediate(() => {
                    options.callback({
                        success: true,
                        message: 'Mock response for API contract testing'
                    });
                });
            }
        });
    }
    
    console.log('✅ API Contract Testing environment initialized');
}

/**
 * Cleanup API contract testing environment
 * Called once after all tests complete
 */
function teardownAPIContractTesting() {
    if (globalApiServer) {
        globalApiServer.stop();
        globalApiServer = null;
        global.__API_CONTRACT_SERVER__ = null;
    }
    
    // Clear API call tracking
    if (global.__API_CALLS__) {
        global.__API_CALLS__ = [];
    }
    
    console.log('✅ API Contract Testing environment cleaned up');
}

/**
 * Reset API contract state between tests
 * Called before each test
 */
function resetAPIContractState() {
    if (globalApiServer) {
        globalApiServer.reset();
    }
    
    // Clear API call tracking for this test
    if (global.__API_CALLS__) {
        global.__API_CALLS__.length = 0;
    }
}

/**
 * Get captured API calls for current test
 */
function getCapturedAPICalls() {
    return global.__API_CALLS__ || [];
}

/**
 * Utility to validate captured API calls against contracts
 */
function validateCapturedCalls() {
    const { APIContractTester } = require('./api-contract-testing');
    const tester = new APIContractTester();
    
    const calls = getCapturedAPICalls();
    const violations = [];
    
    calls.forEach(call => {
        try {
            if (tester.getMethodSchema(call.method)) {
                const result = tester.validateFrappeCall(call);
                if (!result.valid) {
                    violations.push({
                        method: call.method,
                        errors: result.errors
                    });
                }
            }
        } catch (error) {
            violations.push({
                method: call.method,
                errors: [{ message: error.message }]
            });
        }
    });
    
    return violations;
}

// Setup Jest hooks for API contract testing
beforeAll(() => {
    setupAPIContractTesting();
});

afterAll(() => {
    teardownAPIContractTesting();
});

beforeEach(() => {
    resetAPIContractState();
});

// Export utilities for use in tests
module.exports = {
    setupAPIContractTesting,
    teardownAPIContractTesting,
    resetAPIContractState,
    getCapturedAPICalls,
    validateCapturedCalls
};