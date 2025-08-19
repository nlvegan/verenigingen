/**
 * @fileoverview Dutch Business Logic Validation E2E Tests - Compliance and Standards Testing
 *
 * This comprehensive test suite validates Dutch-specific business rules, regulatory
 * compliance, and cultural conventions implemented in the JavaScript controllers.
 * Tests focus on real Dutch data patterns, banking standards, and association
 * governance requirements without mocking.
 *
 * Business Context:
 * The verenigingen system must comply with Dutch legal requirements, banking
 * standards, and cultural conventions. This includes IBAN validation, SEPA
 * compliance, Dutch naming conventions, postal code systems, and association
 * governance regulations.
 *
 * Test Strategy:
 * - Tests run against real JavaScript validation logic
 * - Uses authentic Dutch data (IBANs, postal codes, names, addresses)
 * - Validates regulatory compliance (SEPA, Dutch banking, association law)
 * - Tests cultural conventions (tussenvoegsel, name formatting)
 * - Verifies geographic logic (postal codes, municipalities)
 *
 * Prerequisites:
 * - Development server with Dutch localization
 * - Valid Dutch bank configuration
 * - Sample Dutch geographic data
 * - Test accounts with appropriate permissions
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Dutch Business Logic Validation - Compliance and Standards', () => {
	beforeEach(() => {
		// Login with administrative privileges
		cy.login('administrator@example.com', 'admin');

		// Ensure clean state for Dutch validation tests
		cy.clearLocalStorage();
		cy.clearCookies();

		// Clear test data to prevent validation conflicts
		cy.clear_test_data();
	});

	describe('Dutch Banking Standards and IBAN Validation', () => {
		it('should validate Dutch IBANs against all major Dutch banks', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test comprehensive Dutch bank IBAN validation
			const dutchBanks = [
				{
					bank: 'ABN AMRO',
					iban: 'NL91 ABNA 0417 1643 00',
					bic: 'ABNANL2A',
					valid: true
				},
				{
					bank: 'Rabobank',
					iban: 'NL91 RABO 0315 2648 11',
					bic: 'RABONL2U',
					valid: true
				},
				{
					bank: 'ING Bank',
					iban: 'NL91 INGB 0002 4458 88',
					bic: 'INGBNL2A',
					valid: true
				},
				{
					bank: 'Volksbank (SNS)',
					iban: 'NL91 SNSB 0902 6158 03',
					bic: 'SNSBNL2A',
					valid: true
				},
				{
					bank: 'Triodos Bank',
					iban: 'NL91 TRIO 0391 9424 00',
					bic: 'TRIONL2U',
					valid: true
				},
				{
					bank: 'Invalid Dutch IBAN',
					iban: 'NL91 FAKE 1234 5678 90',
					bic: '',
					valid: false
				}
			];

			dutchBanks.forEach((bank) => {
				// Navigate to SEPA mandate creation
				cy.get('button[data-label="Create SEPA Mandate"]').click();
				cy.wait(1000);

				// Test IBAN validation for each bank
				cy.get('input[data-fieldname="iban"]').clear().type(bank.iban);
				cy.get('input[data-fieldname="iban"]').blur();
				cy.wait(500);

				if (bank.valid) {
					// Verify valid Dutch IBAN detection
					cy.get('input[data-fieldname="iban"]').should('have.class', 'is-valid');
					cy.get('.bank-info-display').should('contain', bank.bank);
					cy.get('input[data-fieldname="bic"]').should('have.value', bank.bic);
					cy.get('.iban-checksum-status').should('contain', 'Valid Dutch IBAN');

					// Test SEPA compliance indicators
					cy.get('.sepa-compliance-status').should('contain', 'SEPA compliant');
					cy.get('.euro-zone-status').should('contain', 'Eurozone bank');
				} else {
					// Verify invalid IBAN detection
					cy.get('input[data-fieldname="iban"]').should('have.class', 'is-invalid');
					cy.get('.invalid-feedback').should('contain', 'Invalid IBAN');
					cy.get('.bank-info-display').should('contain', 'Unknown bank');
				}

				// Close mandate form for next iteration
				cy.get('button[data-label="Cancel"]').click();
				cy.wait(500);
			});
		});

		it('should validate SEPA creditor identifier format compliance', () => {
			cy.visit('/app/direct-debit-batch/new');
			cy.wait(2000);

			// Test Dutch SEPA creditor identifier validation
			const creditorIds = [
				{
					id: 'NL98ZZZ123456780001',
					description: 'Valid Dutch SEPA creditor ID',
					valid: true
				},
				{
					id: 'NL12ABC987654321000',
					description: 'Valid format with different organization code',
					valid: true
				},
				{
					id: 'DE98ZZZ123456780001',
					description: 'German creditor ID (valid format but wrong country)',
					valid: false,
					reason: 'Not a Dutch creditor identifier'
				},
				{
					id: 'NL98ZZ123456780001',
					description: 'Too short organization code',
					valid: false,
					reason: 'Invalid organization code length'
				},
				{
					id: 'INVALID123',
					description: 'Completely invalid format',
					valid: false,
					reason: 'Invalid SEPA creditor identifier format'
				}
			];

			creditorIds.forEach((cred) => {
				cy.get('input[data-fieldname="creditor_identifier"]').clear().type(cred.id);
				cy.get('input[data-fieldname="creditor_identifier"]').blur();
				cy.wait(500);

				if (cred.valid) {
					cy.get('input[data-fieldname="creditor_identifier"]').should('have.class', 'is-valid');
					cy.get('.creditor-validation-status').should('contain', 'Valid Dutch creditor ID');
					cy.get('.sepa-compliance-indicator').should('have.class', 'compliant');
				} else {
					cy.get('input[data-fieldname="creditor_identifier"]').should('have.class', 'is-invalid');
					cy.get('.invalid-feedback').should('contain', cred.reason);
					cy.get('.sepa-compliance-indicator').should('have.class', 'non-compliant');
				}
			});
		});
	});

	describe('Dutch Naming Conventions and Cultural Standards', () => {
		it('should handle Dutch tussenvoegsel (name particles) correctly', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test common Dutch tussenvoegsels
			const dutchNames = [
				{
					first_name: 'Jan',
					tussenvoegsel: 'van der',
					last_name: 'Berg',
					expected_display: 'Jan van der Berg',
					expected_sort: 'Berg, van der, Jan'
				},
				{
					first_name: 'Maria',
					tussenvoegsel: 'de',
					last_name: 'Jong',
					expected_display: 'Maria de Jong',
					expected_sort: 'Jong, de, Maria'
				},
				{
					first_name: 'Pieter',
					tussenvoegsel: 'van den',
					last_name: 'Broek',
					expected_display: 'Pieter van den Broek',
					expected_sort: 'Broek, van den, Pieter'
				},
				{
					first_name: 'Sophie',
					tussenvoegsel: 'ter',
					last_name: 'Haar',
					expected_display: 'Sophie ter Haar',
					expected_sort: 'Haar, ter, Sophie'
				},
				{
					first_name: 'Willem',
					tussenvoegsel: '\'t',
					last_name: 'Hart',
					expected_display: 'Willem \'t Hart',
					expected_sort: 'Hart, \'t, Willem'
				}
			];

			dutchNames.forEach((name) => {
				// Fill name fields
				cy.get('input[data-fieldname="first_name"]').clear().type(name.first_name);
				cy.get('input[data-fieldname="tussenvoegsel"]').clear().type(name.tussenvoegsel);
				cy.get('input[data-fieldname="last_name"]').clear().type(name.last_name);

				// Trigger JavaScript name formatting
				cy.get('input[data-fieldname="last_name"]').blur();
				cy.wait(500);

				// Test JavaScript display name generation
				cy.get('.full-name-display').should('contain', name.expected_display);
				cy.get('[data-fieldname="full_name"]').should('have.value', name.expected_display);

				// Test sorting name generation (for alphabetical lists)
				cy.get('[data-fieldname="sort_name"]').should('have.value', name.expected_sort);

				// Test address formatting
				cy.get('.address-display').should('contain', `Dhr./Mevr. ${name.expected_display}`);
			});
		});

		it('should validate Dutch roepnaam (calling name) conventions', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test roepnaam scenarios
			const roepnaamTests = [
				{
					first_name: 'Johannes Petrus',
					roepnaam: 'Jan',
					expected_display: 'Jan (Johannes Petrus)',
					valid: true
				},
				{
					first_name: 'Elisabeth Maria',
					roepnaam: 'Lies',
					expected_display: 'Lies (Elisabeth Maria)',
					valid: true
				},
				{
					first_name: 'Wilhelmus',
					roepnaam: 'Wim',
					expected_display: 'Wim (Wilhelmus)',
					valid: true
				},
				{
					first_name: 'Jan',
					roepnaam: 'Jan',
					expected_display: 'Jan',
					note: 'Same as first name - roepnaam not needed'
				}
			];

			roepnaamTests.forEach((test) => {
				cy.get('input[data-fieldname="first_name"]').clear().type(test.first_name);
				cy.get('input[data-fieldname="roepnaam"]').clear().type(test.roepnaam);

				cy.get('input[data-fieldname="roepnaam"]').blur();
				cy.wait(500);

				// Test JavaScript roepnaam logic
				cy.get('.display-name-preview').should('contain', test.expected_display);

				if (test.note) {
					cy.get('.roepnaam-note').should('contain', test.note);
				}
			});
		});
	});

	describe('Dutch Postal Code and Geographic Validation', () => {
		it('should validate Dutch postal code format and geographic logic', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test Dutch postal code validation
			const postalCodeTests = [
				{
					code: '1016 GV',
					city: 'Amsterdam',
					province: 'Noord-Holland',
					valid: true,
					region: 'Amsterdam Centrum'
				},
				{
					code: '3011 AB',
					city: 'Rotterdam',
					province: 'Zuid-Holland',
					valid: true,
					region: 'Rotterdam Centrum'
				},
				{
					code: '2500 GA',
					city: 'Den Haag',
					province: 'Zuid-Holland',
					valid: true,
					region: 'Den Haag Centrum'
				},
				{
					code: '9700 AA',
					city: 'Groningen',
					province: 'Groningen',
					valid: true,
					region: 'Groningen Centrum'
				},
				{
					code: '1234',
					city: '',
					valid: false,
					error: 'Invalid postal code format'
				},
				{
					code: '9999 ZZ',
					city: '',
					valid: false,
					error: 'Postal code does not exist'
				}
			];

			postalCodeTests.forEach((test) => {
				cy.get('input[data-fieldname="postal_code"]').clear().type(test.code);
				cy.get('input[data-fieldname="postal_code"]').blur();
				cy.wait(1000); // Allow time for postal code lookup

				if (test.valid) {
					// Test valid postal code processing
					cy.get('input[data-fieldname="postal_code"]').should('have.class', 'is-valid');
					cy.get('[data-fieldname="city"]').should('have.value', test.city);
					cy.get('[data-fieldname="state"]').should('have.value', test.province);

					// Test geographic information display
					cy.get('.geographic-info').should('contain', test.region);
					cy.get('.postal-validation-status').should('contain', 'Valid Dutch postal code');

					// Test chapter suggestion based on postal code
					cy.get('.chapter-suggestion').should('be.visible');
				} else {
					// Test invalid postal code handling
					cy.get('input[data-fieldname="postal_code"]').should('have.class', 'is-invalid');
					cy.get('.invalid-feedback').should('contain', test.error);
					cy.get('.chapter-suggestion').should('not.exist');
				}
			});
		});

		it('should handle special Dutch postal code cases and territories', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test special Dutch territories and cases
			const specialCases = [
				{
					code: '1000 AA',
					description: 'Amsterdam range start',
					expected_city: 'Amsterdam',
					special_note: 'Major city center'
				},
				{
					code: '8000 AA',
					description: 'Zwolle area',
					expected_city: 'Zwolle',
					province: 'Overijssel'
				},
				{
					code: '6000 AA',
					description: 'Weert area',
					expected_city: 'Weert',
					province: 'Limburg'
				}
			];

			specialCases.forEach((testCase) => {
				cy.get('input[data-fieldname="postal_code"]').clear().type(testCase.code);
				cy.get('input[data-fieldname="postal_code"]').blur();
				cy.wait(1000);

				// Verify geographic lookup works for special cases
				cy.get('[data-fieldname="city"]').should('have.value', testCase.expected_city);

				if (testCase.province) {
					cy.get('[data-fieldname="state"]').should('have.value', testCase.province);
				}

				if (testCase.special_note) {
					cy.get('.location-notes').should('contain', testCase.special_note);
				}
			});
		});
	});

	describe('Dutch Association Governance and Legal Compliance', () => {
		it('should validate Dutch association membership age requirements', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test Dutch legal age requirements for association membership
			const ageTests = [
				{
					birth_date: '2010-01-01', // 15 years old
					expected_status: 'Minor - requires parental consent',
					volunteer_eligible: false,
					voting_eligible: false
				},
				{
					birth_date: '2007-01-01', // 18 years old
					expected_status: 'Adult member',
					volunteer_eligible: true,
					voting_eligible: true
				},
				{
					birth_date: '2009-01-01', // 16 years old
					expected_status: 'Minor - limited rights',
					volunteer_eligible: true, // 16+ can volunteer
					voting_eligible: false // Must be 18+ to vote
				},
				{
					birth_date: '1950-01-01', // 75 years old
					expected_status: 'Senior member',
					volunteer_eligible: true,
					voting_eligible: true,
					special_considerations: 'May qualify for senior discounts'
				}
			];

			ageTests.forEach((test) => {
				cy.get('input[data-fieldname="birth_date"]').clear().type(test.birth_date);
				cy.get('input[data-fieldname="birth_date"]').blur();
				cy.wait(500);

				// Test JavaScript age calculation and status determination
				cy.get('.membership-status-indicator').should('contain', test.expected_status);

				// Test volunteer eligibility
				if (test.volunteer_eligible) {
					cy.get('.volunteer-eligibility').should('contain', 'Eligible for volunteer activities');
					cy.get('button[data-label="Create Volunteer Profile"]').should('not.be.disabled');
				} else {
					cy.get('.volunteer-eligibility').should('contain', 'Too young for volunteer activities');
					cy.get('button[data-label="Create Volunteer Profile"]').should('be.disabled');
				}

				// Test voting eligibility
				if (test.voting_eligible) {
					cy.get('.voting-rights').should('contain', 'Eligible to vote');
				} else {
					cy.get('.voting-rights').should('contain', 'Not eligible to vote');
				}

				// Test special considerations
				if (test.special_considerations) {
					cy.get('.special-member-notes').should('contain', test.special_considerations);
				}
			});
		});

		it('should validate Dutch GDPR and privacy compliance', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test GDPR compliance features
			cy.get('.gdpr-compliance-section').should('be.visible');

			// Test privacy consent checkboxes
			cy.get('input[data-fieldname="newsletter_consent"]').should('not.be.checked');
			cy.get('input[data-fieldname="data_processing_consent"]').should('be.checked'); // Required
			cy.get('input[data-fieldname="marketing_consent"]').should('not.be.checked');

			// Test that data processing consent is mandatory
			cy.get('input[data-fieldname="data_processing_consent"]').uncheck();

			// Try to save without required consent
			cy.fill_field('first_name', 'GDPR');
			cy.fill_field('last_name', 'Test');
			cy.fill_field('email', 'gdpr.test@example.com');

			cy.get('button[data-label="Save"]').click();
			cy.wait(1000);

			// Verify JavaScript prevents save without required consent
			cy.get('.gdpr-validation-error').should('be.visible');
			cy.get('.gdpr-validation-error').should('contain', 'Data processing consent is required');

			// Test consent date tracking
			cy.get('input[data-fieldname="data_processing_consent"]').check();
			cy.get('[data-fieldname="consent_date"]').should('not.be.empty');

			// Test privacy policy link
			cy.get('.privacy-policy-link').should('be.visible');
			cy.get('.privacy-policy-link').should('have.attr', 'href').and('include', 'privacy');
		});
	});

	describe('Dutch Financial and Tax Compliance', () => {
		it('should validate Dutch tax number (BSN) format when provided', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Test Dutch BSN (Burgerservicenummer) validation
			const bsnTests = [
				{
					bsn: '123456782', // Valid BSN (passes 11-test)
					valid: true,
					description: 'Valid BSN format'
				},
				{
					bsn: '111222333', // Invalid BSN (fails 11-test)
					valid: false,
					error: 'Invalid BSN - fails validation test'
				},
				{
					bsn: '12345678', // Too short
					valid: false,
					error: 'BSN must be 9 digits'
				},
				{
					bsn: '1234567890', // Too long
					valid: false,
					error: 'BSN must be 9 digits'
				}
			];

			bsnTests.forEach((test) => {
				if (cy.get('input[data-fieldname="tax_number"]').should('exist')) {
					cy.get('input[data-fieldname="tax_number"]').clear().type(test.bsn);
					cy.get('input[data-fieldname="tax_number"]').blur();
					cy.wait(500);

					if (test.valid) {
						cy.get('input[data-fieldname="tax_number"]').should('have.class', 'is-valid');
						cy.get('.bsn-validation-status').should('contain', 'Valid BSN');
					} else {
						cy.get('input[data-fieldname="tax_number"]').should('have.class', 'is-invalid');
						cy.get('.invalid-feedback').should('contain', test.error);
					}
				}
			});
		});

		it('should handle Dutch membership fee calculation and VAT rules', () => {
			cy.visit('/app/membership-dues-schedule/new');
			cy.wait(2000);

			// Test Dutch VAT rules for association membership fees
			cy.fill_field('title', 'Dutch VAT Test Schedule');
			cy.fill_field('base_amount', '25.00');

			// Test that membership fees are VAT-exempt in Netherlands
			cy.get('.vat-calculation').should('contain', 'VAT-exempt (association membership)');
			cy.get('[data-fieldname="vat_amount"]').should('have.value', '0.00');
			cy.get('[data-fieldname="total_amount"]').should('have.value', '25.00');

			// Test donation component (which may have different VAT rules)
			cy.get('input[data-fieldname="include_donation"]').check();
			cy.fill_field('donation_amount', '10.00');

			// Donations are also typically VAT-exempt for qualifying organizations
			cy.get('.donation-vat-status').should('contain', 'VAT-exempt (charitable donation)');
			cy.get('[data-fieldname="total_amount"]').should('have.value', '35.00');

			// Test ANBI (tax-deductible donation) status indication
			cy.get('.anbi-status').should('be.visible');
			cy.get('.anbi-status').should('contain', 'ANBI qualified organization');
		});
	});

	describe('Integration Test - Complete Dutch Member Registration', () => {
		it('should complete full Dutch member registration with all validations', () => {
			cy.visit('/app/member/new');
			cy.wait(2000);

			// Complete Dutch member profile
			const dutchMember = {
				first_name: 'Johannes Petrus',
				roepnaam: 'Jan',
				tussenvoegsel: 'van der',
				last_name: 'Berg',
				birth_date: '1985-03-15',
				email: 'jan.vandeberg@example.nl',
				phone: '+31 6 12345678',
				postal_code: '1016 GV',
				address_line_1: 'Prinsengracht 263',
				city: 'Amsterdam', // Should auto-fill from postal code
				state: 'Noord-Holland' // Should auto-fill from postal code
			};

			// Fill all member fields with Dutch-specific validation
			Object.keys(dutchMember).forEach(field => {
				if (dutchMember[field] && field !== 'city' && field !== 'state') {
					cy.fill_field(field, dutchMember[field]);
				}
			});

			// Verify all Dutch validations pass
			cy.get('.dutch-name-validation').should('contain', 'Valid Dutch name format');
			cy.get('.postal-code-validation').should('contain', 'Valid Amsterdam postal code');
			cy.get('.age-validation').should('contain', 'Adult member (39 years)');
			cy.get('.email-validation').should('contain', 'Valid .nl email address');

			// Test GDPR compliance
			cy.get('input[data-fieldname="data_processing_consent"]').should('be.checked');
			cy.get('input[data-fieldname="newsletter_consent"]').check();

			// Save member
			cy.save();
			cy.wait(3000);

			// Verify successful creation with Dutch formatting
			cy.get('.member-summary-card').should('contain', 'Jan van der Berg');
			cy.get('.full-address').should('contain', 'Prinsengracht 263, 1016 GV Amsterdam');
			cy.get('.member-status').should('contain', 'Active Dutch Member');

			// Test SEPA mandate creation with Dutch bank
			cy.get('button[data-label="Create SEPA Mandate"]').click();
			cy.wait(1000);

			cy.fill_field('iban', 'NL91 ABNA 0417 1643 00');
			cy.fill_field('account_holder_name', 'J.P. van der Berg');

			// Verify Dutch SEPA compliance
			cy.get('.sepa-compliance-status').should('contain', 'Dutch SEPA compliant');
			cy.get('.mandate-validation').should('contain', 'Valid for Dutch direct debit');

			cy.save();
			cy.wait(2000);

			// Final verification - complete Dutch member with SEPA
			cy.get('.member-payment-status').should('contain', 'SEPA Direct Debit Active');
			cy.get('.dutch-compliance-indicator').should('have.class', 'fully-compliant');
		});
	});
});

/**
 * Enhanced Custom Commands for Dutch Business Logic Testing
 */

// Validate Dutch postal code format
Cypress.Commands.add('validateDutchPostalCode', (postalCode) => {
	const dutchPostalRegex = /^\d{4}\s?[A-Z]{2}$/;
	return dutchPostalRegex.test(postalCode);
});

// Create member with Dutch cultural data
Cypress.Commands.add('createDutchTestMember', (memberData) => {
	return cy.request({
		method: 'POST',
		url: '/api/method/verenigingen.tests.create_dutch_member',
		body: {
			...memberData,
			locale: 'nl_NL',
			validate_dutch_rules: true
		}
	}).then((response) => {
		return response.body.message;
	});
});
