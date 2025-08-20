/**
 * Test Environment Setup for Verenigingen Unit Tests
 * Configures JSDOM environment with necessary polyfills and global objects
 */

const { TextEncoder, TextDecoder } = require('util');

// Setup text encoding polyfills for JSDOM
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

// Setup fetch API polyfill for testing
global.fetch = jest.fn(() => Promise.resolve({
	ok: true,
	json: () => Promise.resolve({}),
	text: () => Promise.resolve('')
}));

// Mock DOM APIs that JSDOM doesn't fully support
Object.defineProperty(window, 'matchMedia', {
	writable: true,
	value: jest.fn().mockImplementation(query => ({
		matches: false,
		media: query,
		onchange: null,
		addListener: jest.fn(), // deprecated
		removeListener: jest.fn(), // deprecated
		addEventListener: jest.fn(),
		removeEventListener: jest.fn(),
		dispatchEvent: jest.fn()
	}))
});

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
	constructor(cb) {
		this.cb = cb;
	}
	observe() {}
	unobserve() {}
	disconnect() {}
};

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
	constructor(cb) {
		this.cb = cb;
	}
	observe() {}
	unobserve() {}
	disconnect() {}
};

// Mock crypto for secure operations
Object.defineProperty(global, 'crypto', {
	value: {
		getRandomValues: jest.fn((arr) => {
			for (let i = 0; i < arr.length; i++) {
				arr[i] = Math.floor(Math.random() * 256);
			}
			return arr;
		}),
		subtle: {
			digest: jest.fn(() => Promise.resolve(new ArrayBuffer(32))),
			encrypt: jest.fn(() => Promise.resolve(new ArrayBuffer(16))),
			decrypt: jest.fn(() => Promise.resolve(new ArrayBuffer(16)))
		}
	}
});

// Mock localStorage and sessionStorage
const createStorage = () => {
	let store = {};
	return {
		getItem: jest.fn(key => store[key] || null),
		setItem: jest.fn((key, value) => {
			store[key] = value.toString();
		}),
		removeItem: jest.fn(key => {
			delete store[key];
		}),
		clear: jest.fn(() => {
			store = {};
		}),
		get length() {
			return Object.keys(store).length;
		},
		key: jest.fn(index => Object.keys(store)[index] || null)
	};
};

Object.defineProperty(window, 'localStorage', {
	value: createStorage()
});

Object.defineProperty(window, 'sessionStorage', {
	value: createStorage()
});

// Mock console methods for cleaner test output
global.console = {
	...console,
	log: jest.fn(),
	debug: jest.fn(),
	info: jest.fn(),
	warn: jest.fn(),
	error: jest.fn()
};

module.exports = {};
