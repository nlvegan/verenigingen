// Jest setup file for frontend tests
import '@testing-library/jest-dom';

// Mock global objects that might be used in tests
global.frappe = {
  _: (str) => str, // Mock translation function
  msgprint: jest.fn(),
  throw: jest.fn(),
  call: jest.fn(),
  require: jest.fn(),
  ready: jest.fn(),
  ui: {
    toolbar: {
      add_dropdown_button: jest.fn(),
      show_progress: jest.fn(),
      hide_progress: jest.fn(),
    }
  }
};

// Mock jQuery if needed
global.$ = jest.fn(() => ({
  ready: jest.fn(),
  on: jest.fn(),
  off: jest.fn(),
  find: jest.fn(),
  addClass: jest.fn(),
  removeClass: jest.fn(),
  show: jest.fn(),
  hide: jest.fn(),
  val: jest.fn(),
  text: jest.fn(),
  html: jest.fn(),
  attr: jest.fn(),
  prop: jest.fn(),
  click: jest.fn(),
  submit: jest.fn(),
  each: jest.fn(),
}));

// Mock window.location
delete window.location;
window.location = {
  href: 'http://localhost:8000',
  origin: 'http://localhost:8000',
  pathname: '/',
  search: '',
  hash: '',
  reload: jest.fn(),
  assign: jest.fn(),
  replace: jest.fn(),
};

// Mock console methods to avoid noise in tests
global.console = {
  ...console,
  log: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
  info: jest.fn(),
};