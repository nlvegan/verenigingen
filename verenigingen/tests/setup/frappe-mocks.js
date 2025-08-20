/**
 * Comprehensive Frappe Framework Mocks for Unit Testing
 * Provides realistic mock implementations of Frappe framework objects and methods
 */

/**
 * Creates a mock form object with common Frappe form methods
 * @param {Object} overrides - Properties to override in the mock form
 * @returns {Object} Mock form object
 */
function createMockForm(overrides = {}) {
    const mockForm = {
        doc: {
            name: 'TEST-001',
            doctype: 'Test DocType',
            docstatus: 0,
            owner: 'test@example.com',
            creation: '2024-01-15 10:00:00',
            modified: '2024-01-15 10:00:00',
            ...overrides.doc
        },
        
        // Form manipulation methods
        set_value: jest.fn((field, value) => {
            mockForm.doc[field] = value;
            return Promise.resolve();
        }),
        get_value: jest.fn((field) => mockForm.doc[field]),
        get_field: jest.fn((field) => {
            // Create comprehensive jQuery mock for form field wrappers
            const jqueryMock = {
                // Core jQuery methods
                find: jest.fn(() => jqueryMock),
                closest: jest.fn(() => jqueryMock),
                parent: jest.fn(() => jqueryMock),
                children: jest.fn(() => jqueryMock),
                siblings: jest.fn(() => jqueryMock),
                
                // DOM manipulation
                append: jest.fn(() => jqueryMock),
                prepend: jest.fn(() => jqueryMock),
                remove: jest.fn(() => jqueryMock),
                empty: jest.fn(() => jqueryMock),
                html: jest.fn(() => jqueryMock),
                text: jest.fn(() => jqueryMock),
                
                // CSS and styling
                css: jest.fn(() => jqueryMock),
                addClass: jest.fn(() => jqueryMock),
                removeClass: jest.fn(() => jqueryMock),
                toggleClass: jest.fn(() => jqueryMock),
                hasClass: jest.fn(() => false),
                
                // Attributes and properties
                attr: jest.fn(() => jqueryMock),
                prop: jest.fn(() => jqueryMock),
                val: jest.fn(() => ''),
                data: jest.fn(() => jqueryMock),
                
                // Events
                on: jest.fn(() => jqueryMock),
                off: jest.fn(() => jqueryMock),
                click: jest.fn(() => jqueryMock),
                
                // jQuery properties
                length: 1,
                jquery: '3.6.0',
                
                // Common methods used in Frappe
                show: jest.fn(() => jqueryMock),
                hide: jest.fn(() => jqueryMock),
                toggle: jest.fn(() => jqueryMock)
            };
            
            return {
                ...mockForm.fields_dict[field] || { df: { fieldtype: 'Data' } },
                $wrapper: jqueryMock,
                wrapper: jqueryMock
            };
        }),
        refresh: jest.fn(),
        reload_doc: jest.fn(),
        refresh_field: jest.fn(),
        refresh_fields: jest.fn(),
        
        // Display control methods
        toggle_enable: jest.fn(),
        toggle_display: jest.fn(),
        toggle_reqd: jest.fn(),
        set_df_property: jest.fn(),
        
        // Query and filtering
        set_query: jest.fn(),
        
        // UI elements
        add_custom_button: jest.fn(() => ({
            addClass: jest.fn(),
            removeClass: jest.fn()
        })),
        remove_custom_button: jest.fn(),
        clear_custom_buttons: jest.fn(),
        set_intro: jest.fn(),
        
        // Fields dictionary
        fields_dict: {},
        
        // Form state
        is_new: () => !mockForm.doc.name || mockForm.doc.name.startsWith('new-'),
        is_dirty: jest.fn(() => false),
        
        // Permission system (perm levels)
        perm: [
            { read: 1, write: 1, create: 1, delete: 1 }, // Level 0 permissions
            { read: 1, write: 1, create: 1, delete: 1 }  // Level 1 permissions
        ],
        
        // Save and submit
        save: jest.fn(() => Promise.resolve()),
        submit: jest.fn(() => Promise.resolve()),
        cancel: jest.fn(() => Promise.resolve()),
        
        // Dashboard and timeline
        dashboard: {
            add_indicator: jest.fn(),
            set_headline: jest.fn(),
            hide: jest.fn(),
            show: jest.fn(),
            add_comment: jest.fn()
        },
        
        timeline: {
            add: jest.fn(),
            refresh: jest.fn()
        },
        
        // Page actions
        page: {
            add_inner_button: jest.fn(),
            clear_inner_toolbar: jest.fn(),
            set_primary_action: jest.fn(),
            add_action_icon: jest.fn(),
            set_indicator: jest.fn(),
            clear_indicator: jest.fn(),
            set_title: jest.fn(),
            clear_menu: jest.fn(),
            add_menu_item: jest.fn()
        },
        
        // Events
        trigger: jest.fn(),
        
        ...overrides
    };
    
    return mockForm;
}

/**
 * Creates comprehensive Frappe framework mock
 * @returns {Object} Complete Frappe mock object
 */
function createFrappeMock() {
    return {
        // Core API methods
        call: jest.fn(({ callback, error_callback }) => {
            // Default success response
            if (callback) {
                callback({ message: { success: true } });
            }
            return Promise.resolve({ message: { success: true } });
        }),
        
        // Database methods
        db: {
            get_value: jest.fn(() => Promise.resolve({ message: 'test-value' })),
            get_list: jest.fn(() => Promise.resolve({ message: [] })),
            get_doc: jest.fn(() => Promise.resolve({ message: {} })),
            exists: jest.fn(() => Promise.resolve({ message: true })),
            count: jest.fn(() => Promise.resolve({ message: 0 })),
            set_value: jest.fn(() => Promise.resolve()),
            delete: jest.fn(() => Promise.resolve())
        },
        
        // Model methods
        model: {
            get_value: jest.fn(),
            set_value: jest.fn(),
            get_doc: jest.fn(),
            make_new_doc_and_get_name: jest.fn(() => 'NEW-001'),
            clear_doc: jest.fn(),
            add_child: jest.fn(),
            get_list: jest.fn(() => Promise.resolve([])),
            with_doc: jest.fn(),
            get_new_doc: jest.fn(() => ({}))
        },
        
        // UI methods
        show_alert: jest.fn(),
        msgprint: jest.fn(),
        throw: jest.fn((message) => {
            throw new Error(message);
        }),
        confirm: jest.fn((message, callback) => {
            if (callback) callback();
            return Promise.resolve(true);
        }),
        prompt: jest.fn((fields, callback) => {
            if (callback) callback({ test_field: 'test_value' });
            return Promise.resolve({ test_field: 'test_value' });
        }),
        
        // User and session
        user: {
            has_role: jest.fn(() => true),
            name: 'test@example.com',
            roles: ['Test Role', 'System Manager'],
            email: 'test@example.com',
            full_name: 'Test User'
        },
        
        session: {
            user: 'test@example.com',
            csrf_token: 'test-csrf-token'
        },
        
        // Permissions
        perm: {
            has_perm: jest.fn(() => true),
            get_perm: jest.fn(() => ({ read: 1, write: 1, create: 1, delete: 1 }))
        },
        
        // Utilities
        utils: {
            get_datetime: jest.fn(() => '2024-01-15 10:00:00'),
            get_today: jest.fn(() => '2024-01-15'),
            add_days: jest.fn((date, days) => {
                const d = new Date(date);
                d.setDate(d.getDate() + days);
                return d.toISOString().split('T')[0];
            }),
            format_date: jest.fn(date => date),
            get_datetime_str: jest.fn(() => '2024-01-15 10:00:00'),
            nowdate: jest.fn(() => '2024-01-15'),
            validate_email: jest.fn(email => email.includes('@')),
            flt: jest.fn(val => parseFloat(val) || 0),
            cint: jest.fn(val => parseInt(val) || 0),
            cstr: jest.fn(val => String(val || '')),
            format_currency: jest.fn((amount, currency) => `${currency} ${amount}`),
            get_url: jest.fn(path => `https://test.example.com${path}`)
        },
        
        // Date and time
        datetime: {
            now_datetime: jest.fn(() => '2024-01-15 10:00:00'),
            get_today: jest.fn(() => '2024-01-15'),
            add_to_date: jest.fn((date, obj) => {
                const d = new Date(date);
                if (obj.days) d.setDate(d.getDate() + obj.days);
                if (obj.months) d.setMonth(d.getMonth() + obj.months);
                if (obj.years) d.setFullYear(d.getFullYear() + obj.years);
                return d.toISOString().split('T')[0];
            }),
            str_to_obj: jest.fn(dateStr => new Date(dateStr)),
            obj_to_str: jest.fn(dateObj => dateObj.toISOString().split('T')[0])
        },
        
        // UI form events
        ui: {
            form: {
                on: jest.fn((doctype, handlers) => {
                    // Store registered form handlers for testing
                    if (!global._frappe_form_handlers) {
                        global._frappe_form_handlers = {};
                    }
                    global._frappe_form_handlers[doctype] = handlers;
                    
                    // Return a mock form controller object
                    return {
                        doctype: doctype,
                        handlers: handlers,
                        trigger: jest.fn((event, ...args) => {
                            if (handlers && handlers[event]) {
                                return handlers[event](...args);
                            }
                        })
                    };
                }),
                trigger: jest.fn(),
                make_dialog: jest.fn(() => ({
                    show: jest.fn(),
                    hide: jest.fn(),
                    set_value: jest.fn(),
                    get_values: jest.fn(() => ({})),
                    fields_dict: {},
                    $wrapper: {
                        find: jest.fn(() => ({
                            css: jest.fn(),
                            click: jest.fn(),
                            on: jest.fn()
                        }))
                    }
                }))
            },
            toolbar: {
                add_button: jest.fn(),
                remove_button: jest.fn(),
                toggle_button: jest.fn()
            }
        },
        
        // Meta information
        meta: {
            get_docfield: jest.fn(() => ({ fieldtype: 'Data', options: '' })),
            has_field: jest.fn(() => true),
            get_meta: jest.fn(() => ({
                fields: [],
                permissions: []
            }))
        },
        
        // Internationalization
        _: jest.fn(text => text),
        
        // Configuration
        boot: {
            notification_settings: {
                terminate_member: 1,
                payment_reminder: 1
            },
            user: {
                name: 'test@example.com',
                roles: ['Test Role']
            },
            sysdefaults: {
                country: 'Netherlands',
                currency: 'EUR'
            }
        },
        
        // Real-time events
        realtime: {
            on: jest.fn(),
            off: jest.fn(),
            emit: jest.fn()
        },
        
        // Route and navigation
        route_options: {},
        get_route: jest.fn(() => ['List', 'Test DocType']),
        set_route: jest.fn(),
        
        // Web form methods
        web_form: {
            validate: jest.fn(() => true),
            set_value: jest.fn()
        }
    };
}

/**
 * Dutch test data for realistic testing scenarios
 */
const dutchTestData = {
    members: [
        {
            full_name: 'Jan van der Berg',
            first_name: 'Jan',
            last_name: 'Berg',
            tussenvoegsel: 'van der',
            email: 'jan.vandeberg@example.nl',
            phone: '+31 6 12345678',
            postal_code: '1012 AB',
            city: 'Amsterdam',
            birth_date: '1985-06-15',
            bsn: '123456782', // Valid BSN with checksum
            member_since: '2020-01-15'
        },
        {
            full_name: 'Maria de Jong',
            first_name: 'Maria',
            last_name: 'Jong',
            tussenvoegsel: 'de',
            email: 'maria.dejong@example.nl',
            phone: '+31 6 87654321',
            postal_code: '2011 CD',
            city: 'Haarlem',
            birth_date: '1990-03-22',
            bsn: '987654321', // Valid BSN
            member_since: '2021-05-10'
        }
    ],
    
    organizations: [
        {
            name: 'Test Vereniging Nederland',
            rsin: '123456788', // Valid RSIN
            kvk_number: '12345678',
            postal_code: '1000 AA',
            city: 'Amsterdam',
            anbi_number: 'ANBI-12345'
        }
    ],
    
    ibans: [
        'NL91 ABNA 0417 1643 00', // Valid Dutch IBAN
        'NL02 RABO 0123 4567 89'  // Valid Dutch IBAN
    ],
    
    postal_codes: [
        '1012 AB', '2011 CD', '3011 EF', '4011 GH', '5011 IJ'
    ]
};

/**
 * Setup function to initialize mocks for testing
 */
function setupTestMocks() {
    // Setup global Frappe mock
    global.frappe = createFrappeMock();
    
    // Setup global functions
    global.__ = jest.fn(text => text);
    global.cur_frm = null; // Will be set by individual tests
    
    // Setup global constants
    global.flt = global.frappe.utils.flt;
    global.cint = global.frappe.utils.cint;
    global.cstr = global.frappe.utils.cstr;
    
    return {
        frappe: global.frappe,
        createMockForm,
        dutchTestData
    };
}

/**
 * Gets the registered form handlers for a DocType
 * @param {string} doctype - The DocType name
 * @returns {Object} The registered handlers
 */
function getFormHandlers(doctype) {
    if (!global._frappe_form_handlers) {
        return null;
    }
    return global._frappe_form_handlers[doctype];
}

/**
 * Tests a form handler by executing it with a mock form
 * @param {string} doctype - The DocType name
 * @param {string} event - The event name (e.g., 'refresh', 'member')
 * @param {Object} mockForm - Mock form object
 * @returns {any} Result of the handler execution
 */
function testFormHandler(doctype, event, mockForm) {
    const handlers = getFormHandlers(doctype);
    if (!handlers || !handlers[event]) {
        throw new Error(`No handler found for ${doctype}.${event}`);
    }
    
    return handlers[event](mockForm);
}

/**
 * Loads a controller file and returns the registered handlers
 * @param {string} controllerPath - Path to the controller file
 * @returns {Object} The registered handlers for the controller
 */
function loadControllerAndGetHandlers(controllerPath) {
    const { loadFrappeController } = require('./controller-loader');
    return loadFrappeController(controllerPath);
}

/**
 * Cleanup function to reset mocks between tests
 */
function cleanupTestMocks() {
    jest.clearAllMocks();
    
    // Clear form handlers
    if (global._frappe_form_handlers) {
        global._frappe_form_handlers = {};
    }
    
    if (global.frappe) {
        // Reset call counts and mock implementations
        Object.values(global.frappe).forEach(method => {
            if (typeof method === 'function' && method.mockClear) {
                method.mockClear();
            }
        });
    }
}

module.exports = {
    createMockForm,
    createFrappeMock,
    dutchTestData,
    setupTestMocks,
    cleanupTestMocks,
    getFormHandlers,
    testFormHandler,
    loadControllerAndGetHandlers,
    // Re-export controller loader utilities
    ...require('./controller-loader')
};