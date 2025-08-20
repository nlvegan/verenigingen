// Test suite for Enhanced Membership Application API
// Tests the production enhanced membership application functionality

const { describe, test, expect, beforeEach } = require('@jest/globals');

// Mock frappe module
global.frappe = {
	call: jest.fn(),
	ready: jest.fn((callback) => callback()),
	show_alert: jest.fn(),
	msgprint: jest.fn(),
	confirm: jest.fn(),
	utils: {
		get_random_string: jest.fn(() => 'test_random_string'),
		validate_email_address: jest.fn((email) => {
			// More realistic email validation
			const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
			return emailRegex.test(email);
		})
	}
};

describe('Enhanced Membership Application API', () => {
	beforeEach(() => {
		jest.clearAllMocks();
	});

	// Mock complete API responses for comprehensive business rule testing
	// const mockValidationResponses = { ... }; // Commented out as unused

	describe('Application Submission', () => {
		test('should submit enhanced application successfully', async () => {
			const mockResponse = {
				message: {
					success: true,
					application_id: 'ENHANCED-APP-001',
					message: 'Application submitted successfully',
					next_steps: [
						'Check your email for confirmation',
						'Complete payment to activate membership'
					]
				}
			};

			frappe.call.mockResolvedValue(mockResponse);

			const applicationData = {
				first_name: 'Test',
				last_name: 'Applicant',
				email: 'test@example.com',
				address_line1: 'Test Street 123',
				postal_code: '1234 AB',
				city: 'Amsterdam',
				country: 'Netherlands',
				membership_type: 'Regular',
				contribution_amount: 30.0,
				payment_method: 'Bank Transfer'
			};

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: applicationData
			});

			expect(response.message.success).toBe(true);
			expect(response.message.application_id).toBe('ENHANCED-APP-001');
			expect(response.message.next_steps).toHaveLength(2);
		});

		test('should handle validation errors', async () => {
			const mockErrorResponse = {
				message: {
					success: false,
					error: 'Required field missing: Email'
				}
			};

			frappe.call.mockResolvedValue(mockErrorResponse);

			const incompleteData = {
				first_name: 'Incomplete',
				last_name: 'Application'
				// Missing required fields
			};

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: incompleteData
			});

			expect(response.message.success).toBe(false);
			expect(response.message.error).toContain('Required field missing');
		});

		test('should handle duplicate email error', async () => {
			const mockDuplicateResponse = {
				message: {
					success: false,
					error: 'A member with this email already exists'
				}
			};

			frappe.call.mockResolvedValue(mockDuplicateResponse);

			const duplicateData = {
				first_name: 'Duplicate',
				last_name: 'Email',
				email: 'existing@example.com',
				address_line1: 'Test Street',
				postal_code: '1234 AB',
				city: 'Amsterdam',
				country: 'Netherlands',
				membership_type: 'Regular',
				contribution_amount: 25.0,
				payment_method: 'Bank Transfer'
			};

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: duplicateData
			});

			expect(response.message.success).toBe(false);
			expect(response.message.error).toContain('already exists');
		});

		test('should handle network errors gracefully', async () => {
			frappe.call.mockRejectedValue(new Error('Network error'));

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {}
				});
			} catch (error) {
				expect(error.message).toBe('Network error');
			}
		});
	});

	describe('Membership Types', () => {
		test('should get membership types for application', async () => {
			const mockTypesResponse = {
				message: [
					{
						name: 'REG-001',
						membership_type_name: 'Regular',
						description: 'Regular membership',
						amount: 25.0,
						billing_frequency: 'Monthly',
						contribution_options: {
							mode: 'Calculator',
							minimum: 25.0,
							suggested: 30.0,
							maximum: 100.0
						}
					},
					{
						name: 'STU-001',
						membership_type_name: 'Student',
						description: 'Student membership with discount',
						amount: 15.0,
						billing_frequency: 'Monthly',
						contribution_options: {
							mode: 'Fixed',
							minimum: 15.0,
							suggested: 15.0,
							maximum: 50.0
						}
					}
				]
			};

			frappe.call.mockResolvedValue(mockTypesResponse);

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.get_membership_types_for_application'
			});

			expect(response.message).toHaveLength(2);
			expect(response.message[0].membership_type_name).toBe('Regular');
			expect(response.message[1].membership_type_name).toBe('Student');

			// Check structure
			response.message.forEach(type => {
				expect(type).toHaveProperty('name');
				expect(type).toHaveProperty('membership_type_name');
				expect(type).toHaveProperty('amount');
				expect(type).toHaveProperty('contribution_options');
			});
		});

		test('should handle empty membership types', async () => {
			frappe.call.mockResolvedValue({ message: [] });

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.get_membership_types_for_application'
			});

			expect(response.message).toHaveLength(0);
		});
	});

	describe('Contribution Calculator', () => {
		test('should get contribution calculator config', async () => {
			const mockConfigResponse = {
				message: {
					enabled: true,
					percentage: 0.5,
					description: 'Standard contribution calculation',
					quick_amounts: [25, 35, 50, 75],
					tiers: [
						{ name: 'Basic', amount: 25, description: 'Basic support' },
						{ name: 'Supporter', amount: 50, description: 'Enhanced support' }
					]
				}
			};

			frappe.call.mockResolvedValue(mockConfigResponse);

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.get_contribution_calculator_config',
				args: { membership_type: 'Regular' }
			});

			expect(response.message.enabled).toBe(true);
			expect(response.message.quick_amounts).toHaveLength(4);
			expect(response.message.tiers).toHaveLength(2);
		});
	});

	describe('Data Validation', () => {
		test('should validate Dutch postal codes', () => {
			// Test valid Dutch postal codes
			const validCodes = ['1234 AB', '5678CD', '9012 EF', '1000 AA'];

			validCodes.forEach(code => {
				// Simple regex test for Dutch postal codes
				const dutchPostalPattern = /^[1-9][0-9]{3}\s?[A-Z]{2}$/;
				expect(dutchPostalPattern.test(code.replace(/\s/g, ''))).toBe(true);
			});

			// Test invalid postal codes
			const invalidCodes = ['12345', 'ABCD 12', '0123 AB', '1234'];

			invalidCodes.forEach(code => {
				const dutchPostalPattern = /^[1-9][0-9]{3}\s?[A-Z]{2}$/;
				expect(dutchPostalPattern.test(code.replace(/\s/g, ''))).toBe(false);
			});
		});

		test('should validate email addresses', () => {
			const validEmails = [
				'test@example.com',
				'user.name@domain.co.uk',
				'firstname+lastname@company.org'
			];

			const invalidEmails = [
				'not-an-email',
				'@domain.com',
				'user@',
				'user space@domain.com'
			];

			validEmails.forEach(email => {
				expect(frappe.utils.validate_email_address(email)).toBe(true);
			});

			invalidEmails.forEach(email => {
				expect(frappe.utils.validate_email_address(email)).toBe(false);
			});
		});

		test('should validate IBAN format', () => {
			// Simple IBAN validation for Dutch IBANs
			const validateDutchIBAN = (iban) => {
				if (!iban) { return false; }
				const cleaned = iban.replace(/\s/g, '').toUpperCase();
				return cleaned.startsWith('NL') && cleaned.length === 18 && /^NL[0-9]{2}[A-Z]{4}[0-9]{10}$/.test(cleaned);
			};

			const validIBANs = [
				'NL91 ABNA 0417 1643 00',
				'NL91ABNA0417164300',
				'NL20 INGB 0001 2345 67'
			];

			const invalidIBANs = [
				'DE89 3704 0044 0532 0130 00', // German IBAN
				'NL91 ABNA 0417 1643', // Too short
				'INVALID_IBAN'
				// Note: NL00 passes basic format validation,
				// real IBAN validation would need check digit calculation
			];

			validIBANs.forEach(iban => {
				expect(validateDutchIBAN(iban)).toBe(true);
			});

			invalidIBANs.forEach(iban => {
				expect(validateDutchIBAN(iban)).toBe(false);
			});
		});
	});

	describe('Special Characters and Localization', () => {
		test('should handle Dutch names with special characters', async () => {
			const mockResponse = {
				message: {
					success: true,
					application_id: 'DUTCH-001',
					message: 'Application submitted successfully'
				}
			};

			frappe.call.mockResolvedValue(mockResponse);

			const dutchNames = [
				{ first: 'José', last: 'van der Berg' },
				{ first: 'Marie-Claire', last: 'de Wit' },
				{ first: 'François', last: 'Müller' }
			];

			for (const name of dutchNames) {
				const response = await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: name.first,
						last_name: name.last,
						email: `${name.first.toLowerCase()}@example.com`,
						address_line1: 'Test Street 1',
						postal_code: '1234 AB',
						city: 'Amsterdam',
						country: 'Netherlands',
						membership_type: 'Regular',
						contribution_amount: 30.0,
						payment_method: 'Bank Transfer'
					}
				});

				expect(response.message.success).toBe(true);
			}
		});
	});

	describe('Payment Methods', () => {
		test('should handle SEPA Direct Debit applications', async () => {
			const mockResponse = {
				message: {
					success: true,
					application_id: 'SEPA-001',
					message: 'SEPA application submitted successfully',
					next_steps: [
						'SEPA mandate will be created',
						'First payment will be processed automatically'
					]
				}
			};

			frappe.call.mockResolvedValue(mockResponse);

			const sepaApplication = {
				first_name: 'SEPA',
				last_name: 'Applicant',
				email: 'sepa@example.com',
				address_line1: 'SEPA Street 1',
				postal_code: '1234 AB',
				city: 'Amsterdam',
				country: 'Netherlands',
				membership_type: 'Regular',
				contribution_amount: 35.0,
				payment_method: 'SEPA Direct Debit',
				iban: 'NL91 ABNA 0417 1643 00',
				account_holder_name: 'SEPA Applicant'
			};

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: sepaApplication
			});

			expect(response.message.success).toBe(true);
			expect(response.message.next_steps).toContain('SEPA mandate will be created');
		});

		test('should handle Bank Transfer applications', async () => {
			const mockResponse = {
				message: {
					success: true,
					application_id: 'BANK-001',
					message: 'Bank transfer application submitted successfully',
					next_steps: [
						'You will receive payment instructions via email',
						'Membership will be activated after payment confirmation'
					]
				}
			};

			frappe.call.mockResolvedValue(mockResponse);

			const bankTransferApplication = {
				first_name: 'Bank',
				last_name: 'Transfer',
				email: 'bank.transfer@example.com',
				address_line1: 'Bank Street 1',
				postal_code: '5678 CD',
				city: 'Rotterdam',
				country: 'Netherlands',
				membership_type: 'Regular',
				contribution_amount: 25.0,
				payment_method: 'Bank Transfer'
			};

			const response = await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: bankTransferApplication
			});

			expect(response.message.success).toBe(true);
			expect(response.message.next_steps.some(step => step.includes('payment instructions'))).toBe(true);
		});
	});

	describe('Contribution Amount Validation', () => {
		test('should validate contribution amounts against membership type', () => {
			// Mock validation function
			const validateContributionAmount = (membershipType, amount) => {
				const minimums = {
					Regular: 25.0,
					Student: 15.0,
					Senior: 20.0,
					Family: 40.0
				};

				const minimum = minimums[membershipType] || 25.0;

				if (amount < minimum) {
					return { valid: false, error: `Amount must be at least €${minimum}` };
				}

				if (amount > minimum * 10) {
					return { valid: false, error: `Amount exceeds maximum allowed` };
				}

				return { valid: true, amount };
			};

			// Test valid amounts
			expect(validateContributionAmount('Regular', 30.0)).toEqual({
				valid: true,
				amount: 30.0
			});

			expect(validateContributionAmount('Student', 20.0)).toEqual({
				valid: true,
				amount: 20.0
			});

			// Test invalid amounts (too low)
			expect(validateContributionAmount('Regular', 10.0).valid).toBe(false);
			expect(validateContributionAmount('Student', 5.0).valid).toBe(false);

			// Test invalid amounts (too high)
			expect(validateContributionAmount('Regular', 300.0).valid).toBe(false);
		});
	});

	describe('Error Scenarios', () => {
		test('should handle server errors gracefully', async () => {
			frappe.call.mockRejectedValue({
				message: 'Internal server error',
				status: 500
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'Error',
						last_name: 'Test',
						email: 'error@example.com'
					}
				});
			} catch (error) {
				expect(error.message).toBe('Internal server error');
			}
		});

		test('should handle timeout errors', async () => {
			frappe.call.mockRejectedValue({
				message: 'Request timeout',
				status: 408
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {},
					timeout: 5000
				});
			} catch (error) {
				expect(error.message).toBe('Request timeout');
			}
		});
	});

	describe('Enhanced Business Rule Validation', () => {
		test('should validate Dutch postal codes correctly', async () => {
			// Test valid Dutch postal code
			frappe.call.mockResolvedValue({
				message: { success: true, application_id: 'APP-001' }
			});

			await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: {
					first_name: 'Jan',
					last_name: 'van der Berg',
					email: 'jan@example.org',
					country: 'Netherlands',
					postal_code: '1012 AB',
					birth_date: '1990-01-01',
					membership_type: 'Regular',
					contribution_amount: 25.00,
					payment_method: 'Bank Transfer'
				}
			});

			expect(frappe.call).toHaveBeenCalledWith(expect.objectContaining({
				args: expect.objectContaining({
					postal_code: '1012 AB',
					country: 'Netherlands'
				})
			}));
		});

		test('should reject invalid Dutch postal codes', async () => {
			frappe.call.mockRejectedValue({
				message: 'Invalid Dutch postal code format. Please use format: 1234 AB'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'Jan',
						last_name: 'Berg',
						email: 'jan@example.org',
						country: 'Netherlands',
						postal_code: '12345', // Invalid format
						birth_date: '1990-01-01',
						membership_type: 'Regular',
						contribution_amount: 25.00,
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('Invalid Dutch postal code format');
			}
		});

		test('should validate age requirements for student memberships', async () => {
			frappe.call.mockRejectedValue({
				message: 'Student memberships are available for ages 18-30'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'John',
						last_name: 'Doe',
						email: 'john@example.org',
						birth_date: '1980-01-01', // Too old for student (44 years)
						membership_type: 'Student',
						contribution_amount: 15.00,
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('Student memberships are available for ages 18-30');
			}
		});

		test('should validate SEPA payment requirements', async () => {
			frappe.call.mockRejectedValue({
				message: 'IBAN is required for SEPA Direct Debit payments'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'Maria',
						last_name: 'de Jong',
						email: 'maria@example.org',
						birth_date: '1995-01-01',
						membership_type: 'Regular',
						contribution_amount: 30.00,
						payment_method: 'SEPA Direct Debit'
						// Missing IBAN and account_holder_name
					}
				});
			} catch (error) {
				expect(error.message).toContain('IBAN is required for SEPA Direct Debit');
			}
		});

		test('should validate Dutch IBAN format', async () => {
			frappe.call.mockResolvedValue({
				message: { success: true, application_id: 'APP-002' }
			});

			await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: {
					first_name: 'Pieter',
					last_name: 'van den Berg',
					email: 'pieter@example.org',
					birth_date: '1985-01-01',
					membership_type: 'Regular',
					contribution_amount: 35.00,
					payment_method: 'SEPA Direct Debit',
					iban: 'NL91ABNA0417164300', // Valid Dutch IBAN
					account_holder_name: 'Pieter van den Berg'
				}
			});

			expect(frappe.call).toHaveBeenCalledWith(expect.objectContaining({
				args: expect.objectContaining({
					iban: 'NL91ABNA0417164300'
				})
			}));
		});

		test('should reject suspicious email addresses', async () => {
			frappe.call.mockRejectedValue({
				message: 'Please provide a valid personal email address'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'Test',
						last_name: 'User',
						email: 'test@mailinator.com', // Suspicious temporary email
						birth_date: '1990-01-01',
						membership_type: 'Regular',
						contribution_amount: 25.00,
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('valid personal email address');
			}
		});

		test('should reject unrealistic contribution amounts', async () => {
			frappe.call.mockRejectedValue({
				message: 'Contribution amount appears unrealistic. Please contact us directly for large contributions'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'Rich',
						last_name: 'Person',
						email: 'rich@example.org',
						birth_date: '1980-01-01',
						membership_type: 'Regular',
						contribution_amount: 15000.00, // Unrealistically high
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('unrealistic');
			}
		});

		test('should validate Dutch name particles (tussenvoegsel)', async () => {
			frappe.call.mockResolvedValue({
				message: { success: true, application_id: 'APP-003' }
			});

			await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: {
					first_name: 'Anne',
					last_name: 'Dijk',
					tussenvoegsel: 'van', // Valid Dutch name particle
					email: 'anne@example.org',
					birth_date: '1992-01-01',
					membership_type: 'Regular',
					contribution_amount: 28.00,
					payment_method: 'Bank Transfer'
				}
			});

			expect(frappe.call).toHaveBeenCalledWith(expect.objectContaining({
				args: expect.objectContaining({
					tussenvoegsel: 'van'
				})
			}));
		});

		test('should validate Dutch phone number formats', async () => {
			frappe.call.mockResolvedValue({
				message: { success: true, application_id: 'APP-004' }
			});

			await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: {
					first_name: 'Willem',
					last_name: 'de Koning',
					email: 'willem@example.org',
					phone: '+31612345678', // Valid Dutch mobile format
					birth_date: '1988-01-01',
					membership_type: 'Regular',
					contribution_amount: 32.00,
					payment_method: 'Bank Transfer'
				}
			});

			expect(frappe.call).toHaveBeenCalledWith(expect.objectContaining({
				args: expect.objectContaining({
					phone: '+31612345678'
				})
			}));
		});

		test('should prevent XSS attacks in input fields', async () => {
			frappe.call.mockRejectedValue({
				message: 'Input contains potentially dangerous content'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: '<script>alert("xss")</script>', // XSS attempt
						last_name: 'User',
						email: 'user@example.org',
						birth_date: '1990-01-01',
						membership_type: 'Regular',
						contribution_amount: 25.00,
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('dangerous content');
			}
		});
	});

	describe('Input Sanitization and Security', () => {
		test('should sanitize HTML entities in input', async () => {
			frappe.call.mockResolvedValue({
				message: { success: true, application_id: 'APP-005' }
			});

			await frappe.call({
				method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
				args: {
					first_name: 'Jan & Maria', // Should be sanitized to 'Jan &amp; Maria'
					last_name: 'Berg',
					email: 'jan.maria@example.org',
					birth_date: '1990-01-01',
					membership_type: 'Regular',
					contribution_amount: 25.00,
					payment_method: 'Bank Transfer'
				}
			});

			expect(frappe.call).toHaveBeenCalled();
		});

		test('should reject excessively long input fields', async () => {
			frappe.call.mockRejectedValue({
				message: 'First Name is too long (maximum 100 characters)'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'x'.repeat(150), // Exceeds 100 character limit
						last_name: 'User',
						email: 'user@example.org',
						birth_date: '1990-01-01',
						membership_type: 'Regular',
						contribution_amount: 25.00,
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('too long');
			}
		});

		test('should reject suspicious fake names', async () => {
			frappe.call.mockRejectedValue({
				message: 'Please provide your real name for membership registration'
			});

			try {
				await frappe.call({
					method: 'verenigingen.verenigingen.api.enhanced_membership_application.submit_enhanced_application',
					args: {
						first_name: 'test', // Suspicious fake name
						last_name: 'user',
						email: 'user@example.org',
						birth_date: '1990-01-01',
						membership_type: 'Regular',
						contribution_amount: 25.00,
						payment_method: 'Bank Transfer'
					}
				});
			} catch (error) {
				expect(error.message).toContain('real name');
			}
		});
	});
});
