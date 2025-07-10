module.exports = {
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/verenigingen'],
  testMatch: [
    '**/tests/frontend/**/*.spec.js',
    '**/tests/frontend/**/*.test.js'
  ],
  collectCoverageFrom: [
    'verenigingen/public/js/**/*.js',
    'verenigingen/templates/**/*.js',
    '!**/node_modules/**',
    '!**/vendor/**',
    '!**/tests/**'
  ],
  coverageThreshold: {
    global: {
      branches: 70,
      functions: 70,
      lines: 70,
      statements: 70
    }
  },
  moduleNameMapper: {
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
  },
  setupFilesAfterEnv: ['<rootDir>/tests/frontend/setup.js'],
  transform: {
    '^.+\\.jsx?$': 'babel-jest',
  },
  coverageReporters: ['text', 'lcov', 'html', 'json'],
  reporters: [
    'default',
    ['jest-junit', {
      outputDirectory: './test-results',
      outputName: 'jest-junit.xml',
    }]
  ]
};
