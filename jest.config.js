module.exports = {
  testEnvironment: 'jsdom',
  moduleFileExtensions: ['js', 'json'],
  transform: {
    '^.+\\.js$': 'babel-jest',
  },
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/verenigingen/$1',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
  },
  testMatch: [
    '**/tests/unit/**/*.spec.js',
    '**/tests/unit/**/*.test.js',
    '**/tests/integration/**/*.js',
  ],
  testPathIgnorePatterns: [
    '/node_modules/',
    'tests/unit/member-form.spec.js',
    'tests/unit/chapter-form.spec.js',
    'tests/unit/membership-form.spec.js',
    'tests/unit/volunteer-form.spec.js',
    'tests/integration/test_doctype_js_integration.js'
  ],
  collectCoverageFrom: [
    'verenigingen/**/*.js',
    '!verenigingen/public/dist/**',
    '!**/node_modules/**',
    '!**/tests/**',
  ],
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'lcov', 'html'],
  setupFilesAfterEnv: ['<rootDir>/tests/setup.js'],
  globals: {
    frappe: {},
  },
  transformIgnorePatterns: [
    'node_modules/(?!(.*\\.mjs$))'
  ],
};
