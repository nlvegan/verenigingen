/**
 * @fileoverview API Contract Testing Environment Setup
 * 
 * Environment configuration and polyfills for API contract testing.
 * Sets up necessary globals and configurations.
 * 
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

// Set environment variables for API contract testing
process.env.NODE_ENV = 'test';
process.env.API_CONTRACT_TESTING = 'true';

// Polyfill for fetch in Node.js environment if not available
if (typeof global.fetch === 'undefined') {
    const nodeFetch = require('node-fetch');
    global.fetch = nodeFetch;
    global.Request = nodeFetch.Request;
    global.Response = nodeFetch.Response;
    global.Headers = nodeFetch.Headers;
}

// TextEncoder/TextDecoder polyfills for older Node.js versions
if (typeof global.TextEncoder === 'undefined') {
    global.TextEncoder = require('util').TextEncoder;
}

if (typeof global.TextDecoder === 'undefined') {
    global.TextDecoder = require('util').TextDecoder;
}

// URL polyfill if needed
if (typeof global.URL === 'undefined') {
    global.URL = require('url').URL;
}

// Setup console enhancements for debugging API contracts
if (process.env.DEBUG_API_CONTRACTS === 'true') {
    const originalLog = console.log;
    console.log = (...args) => {
        const timestamp = new Date().toISOString();
        originalLog(`[${timestamp}] [API-CONTRACT]`, ...args);
    };
}

// Mock storage APIs that might be used by MSW or other libraries
if (typeof global.localStorage === 'undefined') {
    const { LocalStorage } = require('node-localstorage');
    global.localStorage = new LocalStorage('./tmp/localStorage');
}

if (typeof global.sessionStorage === 'undefined') {
    global.sessionStorage = {
        getItem: () => null,
        setItem: () => {},
        removeItem: () => {},
        clear: () => {},
        length: 0,
        key: () => null
    };
}

// Setup global error handling for unhandled promise rejections
process.on('unhandledRejection', (reason, promise) => {
    if (process.env.DEBUG_API_CONTRACTS === 'true') {
        console.error('Unhandled API Contract Test Promise Rejection:', reason);
    }
});

console.log('✅ API Contract Testing environment configured');