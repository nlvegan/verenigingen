// Global test setup
global.__ = jest.fn(str => str);
global.cur_frm = {};

// Mock jQuery globally
global.$ = jest.fn(() => ({
    html: jest.fn(),
    on: jest.fn(),
    off: jest.fn().mockReturnThis(),
    find: jest.fn().mockReturnThis(),
    addClass: jest.fn().mockReturnThis(),
    removeClass: jest.fn().mockReturnThis(),
    val: jest.fn(),
    prop: jest.fn().mockReturnThis(),
    toggle: jest.fn(),
    show: jest.fn(),
    hide: jest.fn()
}));

// Mock moment if used
global.moment = jest.fn((date) => ({
    format: jest.fn(() => date || '2024-01-01'),
    diff: jest.fn(() => 0),
    add: jest.fn().mockReturnThis(),
    subtract: jest.fn().mockReturnThis()
}));
