// Login command
Cypress.Commands.add('login', (email = 'Administrator', password = 'admin') => {
	cy.session([email, password], () => {
		cy.visit('/login');
		cy.get('#login_email').clear().type(email);
		cy.get('#login_password').clear().type(password);
		cy.get('.btn-login').click();
		cy.location('pathname').should('eq', '/app');
	});
});

// Navigate to doctype list
Cypress.Commands.add('visit_list', (doctype) => {
	cy.visit(`/app/${frappe.router.slug(doctype)}`);
	cy.wait(1000);
});

// Create a new document
Cypress.Commands.add('new_doc', (doctype) => {
	cy.visit(`/app/${frappe.router.slug(doctype)}/new`);
	cy.wait(1000);
});

// Fill field
Cypress.Commands.add('fill_field', (fieldname, value, fieldtype = 'Data') => {
	if (fieldtype === 'Link' || fieldtype === 'Select') {
		cy.get(`[data-fieldname="${fieldname}"] input`).clear().type(value);
		cy.wait(500);
		cy.get('.awesomplete li').first().click();
	} else if (fieldtype === 'Check') {
		if (value) {
			cy.get(`[data-fieldname="${fieldname}"] input`).check();
		} else {
			cy.get(`[data-fieldname="${fieldname}"] input`).uncheck();
		}
	} else {
		cy.get(`[data-fieldname="${fieldname}"] input`).clear().type(value);
	}
});

// Save document
Cypress.Commands.add('save', () => {
	cy.get('.primary-action').contains('Save').click();
	cy.wait(2000);
});

// Submit document
Cypress.Commands.add('submit', () => {
	cy.get('.actions-btn-group button').contains('Submit').click();
	cy.get('.modal-footer button').contains('Yes').click();
	cy.wait(2000);
});

// Verify field value
Cypress.Commands.add('verify_field', (fieldname, value) => {
	cy.get(`[data-fieldname="${fieldname}"]`).should('contain', value);
});

// Clear all test data
Cypress.Commands.add('clear_test_data', () => {
	cy.window().then((win) => {
		return win.frappe.call({
			method: 'verenigingen.tests.clear_test_data',
			args: {},
		});
	});
});
