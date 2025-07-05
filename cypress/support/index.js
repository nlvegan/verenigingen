// Import commands
import './commands';
import '@cypress/code-coverage/support';
import '@testing-library/cypress/add-commands';
import 'cypress-real-events/support';

// Global before hook
before(() => {
	cy.login();
	cy.visit('/app');
});

// Handle uncaught exceptions
Cypress.on('uncaught:exception', (err, runnable) => {
	// Ignore ResizeObserver errors
	if (err.message.includes('ResizeObserver loop limit exceeded')) {
		return false;
	}
	// Ignore other known Frappe framework errors
	if (err.message.includes('Cannot read properties of undefined')) {
		console.warn('Uncaught exception:', err.message);
		return false;
	}
	// Let other errors fail the test
	return true;
});
