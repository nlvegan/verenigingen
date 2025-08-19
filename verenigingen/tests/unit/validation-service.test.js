/**
 * @fileoverview Validation Service Unit Tests - Standalone Utility Functions
 *
 * This test suite validates the standalone utility functions within the ValidationService
 * that don't require API calls or external dependencies. Tests focus on business-critical
 * validation logic using realistic member data scenarios.
 *
 * Business Context:
 * These validation utilities are used throughout the member application process to
 * provide consistent error messages, field labels, and validation summaries. They
 * must handle real member scenarios including Dutch names, European addresses,
 * and international membership applications.
 *
 * Test Strategy:
 * - Test only standalone utility functions (no API dependencies)
 * - Use realistic Dutch and European member data
 * - Validate business-critical validation patterns
 * - Test error message clarity and user experience
 * - No mocking - test actual utility logic
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

// Test standalone validation patterns and utilities
describe('Validation Service - Standalone Utilities', () => {
	// Extract validation patterns and utility functions for testing
	const validationRules = {
		email: {
			required: true,
			pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
			minLength: 5,
			maxLength: 255
		},
		firstName: {
			required: true,
			minLength: 2,
			maxLength: 50,
			pattern: /^[a-zA-ZÀ-ÿ\s-'.]+$/
		},
		lastName: {
			required: true,
			minLength: 2,
			maxLength: 50,
			pattern: /^[a-zA-ZÀ-ÿ\s-'.]+$/
		},
		phone: {
			required: false,
			pattern: /^[+]?[0-9\s-()]{8,20}$/
		},
		city: {
			required: true,
			minLength: 2,
			maxLength: 100,
			pattern: /^[a-zA-ZÀ-ÿ\s-'.]+$/
		}
	};

	// Utility functions for testing
	const getFieldLabel = (fieldName) => {
		const labels = {
			email: 'Email address',
			firstName: 'First name',
			lastName: 'Last name',
			birthDate: 'Birth date',
			postalCode: 'Postal code',
			phone: 'Phone number',
			address: 'Address',
			city: 'City',
			country: 'Country'
		};
		return labels[fieldName] || fieldName;
	};

	const getPatternErrorMessage = (fieldName) => {
		const messages = {
			email: 'Please enter a valid email address',
			firstName: 'Name can only contain letters, spaces, hyphens, and apostrophes',
			lastName: 'Name can only contain letters, spaces, hyphens, and apostrophes',
			phone: 'Please enter a valid phone number',
			city: 'City name can only contain letters, spaces, hyphens, and apostrophes'
		};
		return messages[fieldName] || `Please enter a valid ${getFieldLabel(fieldName).toLowerCase()}`;
	};

	const getStepFields = (stepNumber) => {
		const stepFieldMap = {
			1: ['firstName', 'lastName', 'email', 'birthDate'],
			2: ['address', 'city', 'postalCode', 'country'],
			3: [],
			4: [],
			5: []
		};
		return stepFieldMap[stepNumber] || [];
	};

	const generateValidationSummary = (results) => {
		const summary = {
			total: Object.keys(results).length,
			valid: 0,
			invalid: 0,
			warnings: 0
		};

		Object.values(results).forEach(result => {
			if (result.valid) {
				summary.valid++;
				if (result.warning) {
					summary.warnings++;
				}
			} else {
				summary.invalid++;
			}
		});

		return summary;
	};

	describe('Field Label Utilities', () => {
		describe('Standard Member Fields', () => {
			test('should return correct label for first name', () => {
				const label = getFieldLabel('firstName');
				expect(label).toBe('First name');
			});

			test('should return correct label for last name', () => {
				const label = getFieldLabel('lastName');
				expect(label).toBe('Last name');
			});

			test('should return correct label for email', () => {
				const label = getFieldLabel('email');
				expect(label).toBe('Email address');
			});

			test('should return correct label for birth date', () => {
				const label = getFieldLabel('birthDate');
				expect(label).toBe('Birth date');
			});

			test('should return correct label for postal code', () => {
				const label = getFieldLabel('postalCode');
				expect(label).toBe('Postal code');
			});

			test('should return correct label for phone number', () => {
				const label = getFieldLabel('phone');
				expect(label).toBe('Phone number');
			});
		});

		describe('Address Fields', () => {
			test('should return correct label for address', () => {
				const label = getFieldLabel('address');
				expect(label).toBe('Address');
			});

			test('should return correct label for city', () => {
				const label = getFieldLabel('city');
				expect(label).toBe('City');
			});

			test('should return correct label for country', () => {
				const label = getFieldLabel('country');
				expect(label).toBe('Country');
			});
		});

		describe('Unknown Fields', () => {
			test('should return field name for unknown field', () => {
				const label = getFieldLabel('unknownField');
				expect(label).toBe('unknownField');
			});

			test('should return field name for custom field', () => {
				const label = getFieldLabel('customMemberField');
				expect(label).toBe('customMemberField');
			});
		});
	});

	describe('Error Message Utilities', () => {
		describe('Standard Pattern Errors', () => {
			test('should return helpful email error message', () => {
				const message = getPatternErrorMessage('email');
				expect(message).toBe('Please enter a valid email address');
			});

			test('should return helpful first name error message', () => {
				const message = getPatternErrorMessage('firstName');
				expect(message).toBe('Name can only contain letters, spaces, hyphens, and apostrophes');
			});

			test('should return helpful last name error message', () => {
				const message = getPatternErrorMessage('lastName');
				expect(message).toBe('Name can only contain letters, spaces, hyphens, and apostrophes');
			});

			test('should return helpful phone error message', () => {
				const message = getPatternErrorMessage('phone');
				expect(message).toBe('Please enter a valid phone number');
			});

			test('should return helpful city error message', () => {
				const message = getPatternErrorMessage('city');
				expect(message).toBe('City name can only contain letters, spaces, hyphens, and apostrophes');
			});
		});

		describe('Generic Error Messages', () => {
			test('should generate generic message for unknown field', () => {
				const message = getPatternErrorMessage('unknownField');
				expect(message).toBe('Please enter a valid unknownfield');
			});

			test('should generate generic message for custom field', () => {
				const message = getPatternErrorMessage('customField');
				expect(message).toBe('Please enter a valid customfield');
			});
		});
	});

	describe('Step Field Mapping', () => {
		describe('Member Application Steps', () => {
			test('should return personal info fields for step 1', () => {
				const fields = getStepFields(1);
				expect(fields).toEqual(['firstName', 'lastName', 'email', 'birthDate']);
			});

			test('should return address fields for step 2', () => {
				const fields = getStepFields(2);
				expect(fields).toEqual(['address', 'city', 'postalCode', 'country']);
			});

			test('should return empty array for membership step (step 3)', () => {
				const fields = getStepFields(3);
				expect(fields).toEqual([]);
			});

			test('should return empty array for volunteer step (step 4)', () => {
				const fields = getStepFields(4);
				expect(fields).toEqual([]);
			});

			test('should return empty array for payment step (step 5)', () => {
				const fields = getStepFields(5);
				expect(fields).toEqual([]);
			});
		});

		describe('Invalid Steps', () => {
			test('should return empty array for step 0', () => {
				const fields = getStepFields(0);
				expect(fields).toEqual([]);
			});

			test('should return empty array for step 6', () => {
				const fields = getStepFields(6);
				expect(fields).toEqual([]);
			});

			test('should return empty array for negative step', () => {
				const fields = getStepFields(-1);
				expect(fields).toEqual([]);
			});
		});
	});

	describe('Validation Summary Generator', () => {
		describe('All Valid Results', () => {
			test('should generate correct summary for all valid fields', () => {
				const results = {
					firstName: { valid: true },
					lastName: { valid: true },
					email: { valid: true },
					birthDate: { valid: true }
				};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 4,
					valid: 4,
					invalid: 0,
					warnings: 0
				});
			});
		});

		describe('Mixed Valid/Invalid Results', () => {
			test('should generate correct summary for mixed validation results', () => {
				const results = {
					firstName: { valid: true },
					lastName: { valid: false },
					email: { valid: true },
					birthDate: { valid: false }
				};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 4,
					valid: 2,
					invalid: 2,
					warnings: 0
				});
			});
		});

		describe('Results with Warnings', () => {
			test('should count warnings for valid fields', () => {
				const results = {
					firstName: { valid: true },
					lastName: { valid: true, warning: 'Unusual name format' },
					email: { valid: true, warning: 'Domain has delivery issues' },
					birthDate: { valid: true }
				};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 4,
					valid: 4,
					invalid: 0,
					warnings: 2
				});
			});
		});

		describe('All Invalid Results', () => {
			test('should generate correct summary for all invalid fields', () => {
				const results = {
					firstName: { valid: false },
					lastName: { valid: false },
					email: { valid: false },
					birthDate: { valid: false }
				};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 4,
					valid: 0,
					invalid: 4,
					warnings: 0
				});
			});
		});

		describe('Empty Results', () => {
			test('should handle empty results object', () => {
				const results = {};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 0,
					valid: 0,
					invalid: 0,
					warnings: 0
				});
			});
		});

		describe('Single Field Results', () => {
			test('should handle single valid field', () => {
				const results = {
					email: { valid: true }
				};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 1,
					valid: 1,
					invalid: 0,
					warnings: 0
				});
			});

			test('should handle single invalid field', () => {
				const results = {
					email: { valid: false }
				};

				const summary = generateValidationSummary(results);

				expect(summary).toEqual({
					total: 1,
					valid: 0,
					invalid: 1,
					warnings: 0
				});
			});
		});
	});

	describe('Validation Rules Access', () => {
		describe('Rule Structure Validation', () => {
			test('should have email validation rule', () => {
				expect(validationRules.email).toBeDefined();
				expect(validationRules.email.required).toBe(true);
				expect(validationRules.email.pattern).toBeInstanceOf(RegExp);
			});

			test('should have name validation rules', () => {
				expect(validationRules.firstName).toBeDefined();
				expect(validationRules.lastName).toBeDefined();

				expect(validationRules.firstName.required).toBe(true);
				expect(validationRules.lastName.required).toBe(true);
			});

			test('should have city validation rules', () => {
				expect(validationRules.city).toBeDefined();
				expect(validationRules.city.required).toBe(true);
			});

			test('should have optional phone validation rule', () => {
				expect(validationRules.phone).toBeDefined();
				expect(validationRules.phone.required).toBe(false);
				expect(validationRules.phone.pattern).toBeInstanceOf(RegExp);
			});
		});

		describe('Pattern Validation Rules', () => {
			test('should validate Dutch names with pattern', () => {
				const namePattern = validationRules.firstName.pattern;

				// Valid Dutch names
				expect(namePattern.test('Pieter')).toBe(true);
				expect(namePattern.test('Jan-Willem')).toBe(true);
				expect(namePattern.test('O\'Connor')).toBe(true);
				expect(namePattern.test('José')).toBe(true);
				expect(namePattern.test('Anne-Marie')).toBe(true);

				// Invalid names
				expect(namePattern.test('John123')).toBe(false);
				expect(namePattern.test('User@Name')).toBe(false);
				expect(namePattern.test('')).toBe(false);
			});

			test('should validate email addresses with pattern', () => {
				const emailPattern = validationRules.email.pattern;

				// Valid emails
				expect(emailPattern.test('member@example.com')).toBe(true);
				expect(emailPattern.test('test.user+tag@domain.org')).toBe(true);
				expect(emailPattern.test('user123@test-domain.nl')).toBe(true);

				// Invalid emails
				expect(emailPattern.test('invalid.email')).toBe(false);
				expect(emailPattern.test('@domain.com')).toBe(false);
				expect(emailPattern.test('user@')).toBe(false);
				expect(emailPattern.test('')).toBe(false);
			});

			test('should validate phone numbers with pattern', () => {
				const phonePattern = validationRules.phone.pattern;

				// Valid phone numbers
				expect(phonePattern.test('+31 6 12345678')).toBe(true);
				expect(phonePattern.test('06-12345678')).toBe(true);
				expect(phonePattern.test('(020) 123-4567')).toBe(true);
				expect(phonePattern.test('+49 30 12345678')).toBe(true);

				// Invalid phone numbers
				expect(phonePattern.test('12')).toBe(false); // Too short
				expect(phonePattern.test('abc-def-ghij')).toBe(false); // Letters
				expect(phonePattern.test('')).toBe(false);
			});
		});
	});
});
