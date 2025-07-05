const { defineConfig } = require('cypress');

module.exports = defineConfig({
  projectId: 'verenigingen-tests',
  viewportHeight: 960,
  viewportWidth: 1400,
  defaultCommandTimeout: 20000,
  pageLoadTimeout: 15000,
  video: true,
  videoUploadOnPasses: false,
  retries: {
    runMode: 2,
    openMode: 0,
  },
  e2e: {
    baseUrl: 'http://dev.veganisme.net:8000',
    specPattern: 'cypress/integration/**/*.js',
    supportFile: 'cypress/support/index.js',
    experimentalStudio: true,
    setupNodeEvents(on, config) {
      // Setup code coverage
      require('@cypress/code-coverage/task')(on, config);

      // Custom tasks
      on('task', {
        log(message) {
          console.log(message);
          return null;
        },
      });

      return config;
    },
  },
});
