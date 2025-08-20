/**
 * Controller Loader for Jest Testing
 * Enables testing of Frappe controllers by extracting registered event handlers
 *
 * SECURITY CONSIDERATIONS:
 * - Uses Node.js vm module with sandboxed context for code execution
 * - Validates file paths to prevent directory traversal attacks
 * - Enforces file size limits to prevent memory exhaustion
 * - Implements execution timeout to prevent infinite loops
 * - Restricts execution to project directory structure
 * - Basic content validation to ensure files are Frappe controllers
 *
 * LIMITATIONS:
 * - This is a testing utility and should NEVER be used in production
 * - Controllers execute in simulated environment, not real Frappe runtime
 * - Some dynamic features may not work identically to production
 */

const fs = require('fs');
const path = require('path');

/**
 * Loads a Frappe controller file and extracts testable event handlers
 * @param {string} controllerPath - Path to the controller file
 * @returns {Object} Extracted event handlers organized by DocType
 */
function loadFrappeController(controllerPath) {
	// Clear any existing handlers
	global._frappe_form_handlers = {};

	// Validate and sanitize input path
	if (!controllerPath || typeof controllerPath !== 'string') {
		throw new Error('Controller path must be a non-empty string');
	}

	// Ensure absolute path and validate it's within expected directory structure
	const absolutePath = path.resolve(controllerPath);
	const expectedBasePath = '/home/frappe/frappe-bench/apps/verenigingen';

	if (!absolutePath.startsWith(expectedBasePath)) {
		throw new Error(`Controller file must be within project directory: ${absolutePath}`);
	}

	if (!fs.existsSync(absolutePath)) {
		throw new Error(`Controller file not found: ${absolutePath}`);
	}

	// Check file permissions and type
	const stats = fs.statSync(absolutePath);
	if (!stats.isFile()) {
		throw new Error(`Path is not a file: ${absolutePath}`);
	}

	// Read the controller file content with size limit
	const maxFileSize = 1024 * 1024; // 1MB limit
	if (stats.size > maxFileSize) {
		throw new Error(`Controller file too large (${stats.size} bytes, max ${maxFileSize}): ${absolutePath}`);
	}

	const controllerContent = fs.readFileSync(absolutePath, 'utf8');

	// Basic content validation - ensure it looks like a Frappe controller
	if (!controllerContent.includes('frappe.ui.form.on')) {
		throw new Error(`File does not appear to be a Frappe controller: ${absolutePath}`);
	}

	// Setup minimal Frappe environment for controller loading
	setupMinimalFrappeEnvironment();

	try {
		// Use Node.js vm module for safer code execution with timeout and context isolation
		const vm = require('vm');

		// Create a sandboxed context with only necessary globals
		// Note: We need to share the global _frappe_form_handlers for extraction
		const context = vm.createContext({
			// Expose only required globals for controller execution
			frappe: global.frappe,
			__: global.__,
			$: global.$,
			window: global.window,
			document: global.document,
			console, // Allow console for debugging

			// Node.js timers that controllers may use
			setTimeout,
			clearTimeout,
			setInterval,
			clearInterval,

			global: {
				_frappe_form_handlers: global._frappe_form_handlers
			}
		});

		// Execute with timeout and error handling
		vm.runInContext(controllerContent, context, {
			filename: absolutePath,
			timeout: 5000, // 5 second timeout to prevent infinite loops
			displayErrors: true
		});

		// Return the registered handlers from the shared global object
		return global._frappe_form_handlers || {};
	} catch (error) {
		// Preserve stack trace and add context
		const detailedError = new Error(`Failed to load controller at ${absolutePath}: ${error.message}`);
		detailedError.originalError = error;
		detailedError.controllerPath = absolutePath;
		detailedError.stack = error.stack;
		console.error('Controller loading failed:', {
			path: absolutePath,
			error: error.message,
			stack: error.stack
		});
		throw detailedError;
	}
}

/**
 * Sets up minimal Frappe environment required for controller loading
 */
function setupMinimalFrappeEnvironment() {
	// Ensure global objects exist
	if (!global.frappe) {
		global.frappe = {};
	}

	if (!global.frappe.ui) {
		global.frappe.ui = {};
	}

	if (!global.frappe.ui.form) {
		global.frappe.ui.form = {};
	}

	// Mock the form registration function
	global.frappe.ui.form.on = function (doctype, handlers) {
		if (!global._frappe_form_handlers) {
			global._frappe_form_handlers = {};
		}

		// Store handlers by DocType
		global._frappe_form_handlers[doctype] = handlers;

		return {
			doctype,
			handlers
		};
	};

	// Mock other required Frappe globals
	global.__ = global.__ || ((text) => text);
	global.frappe._ = global.frappe._ || ((text) => text);

	// Mock essential Frappe objects that controllers might reference
	const mockFunction = (typeof jest !== 'undefined' && jest.fn) ? jest.fn() : (() => {});

	global.frappe.set_route = global.frappe.set_route || mockFunction;
	global.frappe.msgprint = global.frappe.msgprint || mockFunction;
	global.frappe.call = global.frappe.call || mockFunction;
	global.frappe.show_alert = global.frappe.show_alert || mockFunction;

	// Mock frappe.require for controllers that load external utility modules
	global.frappe.require = global.frappe.require || function (paths, callback) {
		// Mock the require function - in tests we don't actually need to load the utility files
		// since we're testing the controller logic, not the utilities
		if (callback && typeof callback === 'function') {
			// Call the callback immediately to simulate successful loading
			callback();
		}
		return Promise.resolve();
	};

	// Mock user context for role-based functionality
	global.frappe.user_roles = global.frappe.user_roles || ['Test User'];
	global.frappe.user = global.frappe.user || {
		has_role: mockFunction,
		get_roles: () => ['Test User']
	};
	global.frappe.datetime = global.frappe.datetime || {
		get_today: () => '2024-01-15',
		str_to_user: (date) => date,
		now_date: () => '2024-01-15',
		user_to_str: (date) => date,
		moment: (date) => ({
			format: (fmt) => date || '2024-01-15'
		})
	};

	// Mock contacts module
	global.frappe.contacts = global.frappe.contacts || {
		render_address_and_contact: mockFunction,
		clear_address_and_contact: mockFunction
	};

	// Mock model methods
	global.frappe.model = global.frappe.model || {
		add_child: mockFunction,
		get_value: mockFunction,
		set_value: mockFunction
	};

	// Mock dynamic_link global
	global.frappe.dynamic_link = null;

	// Mock jQuery with comprehensive DOM methods
	global.$ = global.$ || function (selector) {
		const jqueryMock = {
			// Core jQuery methods
			find: () => global.$(),
			closest: () => global.$(),
			parent: () => global.$(),
			children: () => global.$(),
			siblings: () => global.$(),

			// DOM manipulation
			append: mockFunction,
			prepend: mockFunction,
			appendTo: mockFunction,
			remove: mockFunction,
			empty: mockFunction,
			html: mockFunction,
			text: mockFunction,

			// CSS and styling
			css: mockFunction,
			addClass: mockFunction,
			removeClass: mockFunction,
			toggleClass: mockFunction,
			hasClass: () => false,

			// Attributes and properties
			attr: mockFunction,
			prop: mockFunction,
			val: mockFunction,
			data: mockFunction,

			// Events
			on: mockFunction,
			off: mockFunction,
			click: mockFunction,

			// jQuery properties
			length: 1,
			jquery: '3.6.0',

			// Common methods used in Frappe
			show: mockFunction,
			hide: mockFunction,
			toggle: mockFunction
		};

		return jqueryMock;
	};

	// Mock window and document for browser-dependent controller features
	global.window = global.window || {
		location: {
			href: 'https://test.example.com'
		},
		open: mockFunction,
		download: mockFunction,
		URL: {
			createObjectURL: mockFunction
		}
	};

	global.document = global.document || {
		createElement: () => ({
			href: '',
			download: '',
			click: mockFunction
		})
	};

	// Mock Blob for file downloads
	global.Blob = global.Blob || class MockBlob {
		constructor(data, options) {
			this.data = data;
			this.options = options;
		}
	};
}

/**
 * Tests a specific form event handler
 * @param {string} doctype - The DocType name
 * @param {string} event - The event name (e.g., 'refresh', 'member')
 * @param {Object} mockForm - Mock form object
 * @param {Object} handlers - The loaded handlers object
 * @returns {any} Result of the handler execution
 */
function testFormEvent(doctype, event, mockForm, handlers = null) {
	const formHandlers = handlers || global._frappe_form_handlers;

	if (!formHandlers || !formHandlers[doctype]) {
		throw new Error(`No handlers found for DocType: ${doctype}`);
	}

	const doctypeHandlers = formHandlers[doctype];

	if (!doctypeHandlers[event]) {
		throw new Error(`No handler found for ${doctype}.${event}`);
	}

	// Execute the handler with the mock form
	return doctypeHandlers[event](mockForm);
}

/**
 * Gets all available events for a DocType
 * @param {string} doctype - The DocType name
 * @param {Object} handlers - The loaded handlers object
 * @returns {Array<string>} Array of available event names
 */
function getAvailableEvents(doctype, handlers = null) {
	const formHandlers = handlers || global._frappe_form_handlers;

	if (!formHandlers || !formHandlers[doctype]) {
		return [];
	}

	return Object.keys(formHandlers[doctype]);
}

/**
 * Validates that a controller has expected events
 * @param {string} doctype - The DocType name
 * @param {Array<string>} expectedEvents - Expected event names
 * @param {Object} handlers - The loaded handlers object
 * @returns {Object} Validation result with missing events
 */
function validateControllerEvents(doctype, expectedEvents, handlers = null) {
	const availableEvents = getAvailableEvents(doctype, handlers);
	const missingEvents = expectedEvents.filter(event => !availableEvents.includes(event));

	return {
		valid: missingEvents.length === 0,
		availableEvents,
		missingEvents,
		extraEvents: availableEvents.filter(event => !expectedEvents.includes(event))
	};
}

/**
 * Loads multiple controllers from a directory pattern
 * @param {string} baseDirectory - Base directory containing controllers
 * @param {Array<string>} doctypes - Array of DocType names to load
 * @returns {Object} Object with all loaded handlers
 */
function loadMultipleControllers(baseDirectory, doctypes) {
	const allHandlers = {};

	for (const doctype of doctypes) {
		const controllerPath = path.join(
			baseDirectory,
			doctype.toLowerCase().replace(/ /g, '_'),
			`${doctype.toLowerCase().replace(/ /g, '_')}.js`
		);

		try {
			const handlers = loadFrappeController(controllerPath);
			Object.assign(allHandlers, handlers);
		} catch (error) {
			console.warn(`Could not load controller for ${doctype}: ${error.message}`);
		}
	}

	return allHandlers;
}

/**
 * Creates a test helper function for a specific controller
 * @param {string} controllerPath - Path to the controller file
 * @returns {Function} Test helper function
 */
function createControllerTester(controllerPath) {
	let loadedHandlers = null;

	return {
		loadController: () => {
			loadedHandlers = loadFrappeController(controllerPath);
			return loadedHandlers;
		},

		testEvent: (doctype, event, mockForm) => {
			if (!loadedHandlers) {
				throw new Error('Controller not loaded. Call loadController() first.');
			}
			return testFormEvent(doctype, event, mockForm, loadedHandlers);
		},

		getEvents: (doctype) => {
			if (!loadedHandlers) {
				throw new Error('Controller not loaded. Call loadController() first.');
			}
			return getAvailableEvents(doctype, loadedHandlers);
		},

		validateEvents: (doctype, expectedEvents) => {
			if (!loadedHandlers) {
				throw new Error('Controller not loaded. Call loadController() first.');
			}
			return validateControllerEvents(doctype, expectedEvents, loadedHandlers);
		}
	};
}

module.exports = {
	loadFrappeController,
	testFormEvent,
	getAvailableEvents,
	validateControllerEvents,
	loadMultipleControllers,
	createControllerTester,
	setupMinimalFrappeEnvironment
};
