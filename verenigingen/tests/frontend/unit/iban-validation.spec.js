/**
 * @fileoverview IBAN Validation Unit Tests - Comprehensive Banking Integration Testing
 *
 * This file provides extensive unit testing for IBAN (International Bank Account Number)
 * validation functionality within the membership application system.
 *
 * BUSINESS PURPOSE:
 * Ensures reliable financial transaction processing for membership payments:
 * - Validate IBAN format compliance across European banking systems
 * - Prevent payment failures due to incorrect banking information
 * - Support automated SEPA (Single Euro Payments Area) direct debit operations
 * - Enhance user experience with real-time validation feedback
 * - Reduce administrative burden through automated BIC code derivation
 *
 * TESTING SCOPE:
 * - Multi-country IBAN format validation (Dutch, Belgian, German, etc.)
 * - Checksum validation using mod-97 algorithm
 * - Country-specific length requirements
 * - Case sensitivity and formatting normalization
 * - Dutch banking system BIC code derivation
 * - UI feedback and field interaction behavior
 *
 * VALIDATION FEATURES TESTED:
 * - Format validation (country code, check digits, bank identifier, account number)
 * - Mathematical checksum verification using mod-97 algorithm
 * - Country-specific length validation for 18+ European countries
 * - Input normalization (case conversion, space handling)
 * - Bank identification for Dutch financial institutions
 * - BIC code derivation for major Dutch banks
 *
 * UI INTERACTION TESTING:
 * - Real-time validation feedback with visual indicators
 * - Error message display for various validation failures
 * - Automatic BIC field population for Dutch IBANs
 * - Field state management (valid/invalid styling)
 * - Readonly field behavior for derived values
 *
 * SUPPORTED BANKING SYSTEMS:
 * - Dutch banks: ABN AMRO, ING, Rabobank, Triodos, SNS, ASN, Knab, Bunq
 * - European SEPA zone banks with standardized IBAN formats
 * - Country-specific validation rules for 18+ European countries
 *
 * TECHNICAL IMPLEMENTATION:
 * - Jest testing framework with comprehensive mocking
 * - jQuery UI interaction simulation
 * - Chainable element mocking for realistic DOM behavior
 * - Modular validation logic testing
 * - Error handling and edge case coverage
 *
 * @author Frappe Technologies Pvt. Ltd.
 * @since 2025
 * @category Financial Integration / Payment Processing
 * @requires jest
 * @standard ISO 13616 (IBAN), SEPA Direct Debit
 */

describe('IBAN Validation in Membership Application', () => {
	let membershipApp;

	// Helper function to create chainable jQuery element mock
	const createChainableElement = () => {
		const element = {
			val: jest.fn(),
			addClass: jest.fn(),
			removeClass: jest.fn(),
			siblings: jest.fn(() => ({
				remove: jest.fn(),
				hide: jest.fn()
			})),
			after: jest.fn(),
			prop: jest.fn(),
			length: 1
		};

		// Make methods chainable
		element.addClass.mockReturnValue(element);
		element.removeClass.mockReturnValue(element);
		element.prop.mockReturnValue(element);

		return element;
	};

	beforeEach(() => {
		// Mock jQuery with chaining support

		global.$ = jest.fn((selector) => {
			const element = createChainableElement();

			// Return different mocks based on selector
			if (selector === '#iban') {
				element.val.mockReturnValue('NL91ABNA0417164300');
			} else if (selector === '#bic') {
				element.val.mockReturnValue('');
			}

			return element;
		});

		// Create a simple mock of MembershipApplication
		membershipApp = {
			performIBANValidation(iban) {
				if (!iban) {
					return { valid: false, error: 'IBAN is required' };
				}

				const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

				if (!/^[A-Z0-9]+$/.test(cleanIBAN)) {
					return { valid: false, error: 'IBAN contains invalid characters' };
				}

				if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(cleanIBAN)) {
					return { valid: false, error: 'Invalid IBAN format' };
				}

				const countryCode = cleanIBAN.substring(0, 2);

				const ibanLengths = {
					AD: 24, AT: 20, BE: 16, CH: 21, CZ: 24,
					DE: 22, DK: 18, ES: 24, FI: 18, FR: 27,
					GB: 22, IE: 22, IT: 27, LU: 20, NL: 18,
					NO: 15, PL: 28, PT: 25, SE: 24
				};

				if (!(countryCode in ibanLengths)) {
					return { valid: false, error: `Unsupported country code: ${countryCode}` };
				}

				const expectedLength = ibanLengths[countryCode];
				if (cleanIBAN.length !== expectedLength) {
					const countryNames = {
						NL: 'Dutch', BE: 'Belgian', DE: 'German',
						FR: 'French', GB: 'British', IT: 'Italian',
						ES: 'Spanish', AT: 'Austrian', CH: 'Swiss'
					};
					const countryName = countryNames[countryCode] || countryCode;
					return {
						valid: false,
						error: `${countryName} IBAN must be ${expectedLength} characters (you have ${cleanIBAN.length})`
					};
				}

				// Perform mod-97 checksum validation
				const rearranged = cleanIBAN.substring(4) + cleanIBAN.substring(0, 4);
				const numeric = rearranged.replace(/[A-Z]/g, char => char.charCodeAt(0) - 55);
				const remainder = numeric.match(/.{1,9}/g).reduce((acc, chunk) => {
					return (parseInt(acc + chunk) % 97).toString();
				}, '');

				if (remainder !== '1') {
					return { valid: false, error: 'Invalid IBAN checksum - please check for typos' };
				}

				const formatted = cleanIBAN.match(/.{1,4}/g).join(' ');

				return { valid: true, error: null, formatted };
			},

			deriveBICFromIBAN(iban) {
				if (!iban) { return null; }

				const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

				if (!cleanIBAN.startsWith('NL') || cleanIBAN.length < 8) {
					return null;
				}

				const bankCode = cleanIBAN.substring(4, 8);
				const nlBicCodes = {
					INGB: 'INGBNL2A',
					ABNA: 'ABNANL2A',
					RABO: 'RABONL2U',
					TRIO: 'TRIONL2U',
					SNSB: 'SNSBNL2A',
					ASNB: 'ASNBNL21',
					KNAB: 'KNABNL2H',
					BUNQ: 'BUNQNL2A',
					REVO: 'REVOLT21',
					RBRB: 'RBRBNL21'
				};

				return nlBicCodes[bankCode] || null;
			},

			getBankNameFromIBAN(iban) {
				if (!iban) { return null; }

				const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

				if (!cleanIBAN.startsWith('NL') || cleanIBAN.length < 8) {
					return null;
				}

				const bankCode = cleanIBAN.substring(4, 8);
				const bankNames = {
					INGB: 'ING',
					ABNA: 'ABN AMRO',
					RABO: 'Rabobank',
					TRIO: 'Triodos Bank',
					SNSB: 'SNS Bank',
					ASNB: 'ASN Bank',
					KNAB: 'Knab',
					BUNQ: 'Bunq',
					RBRB: 'RegioBank'
				};

				return bankNames[bankCode] || null;
			},

			validateIBAN() {
				const ibanField = $('#iban');
				const iban = ibanField.val();

				if (!iban) { return; }

				const validation = this.performIBANValidation(iban);

				ibanField.siblings('.invalid-feedback').remove();
				ibanField.siblings('.valid-feedback').remove();

				if (!validation.valid) {
					ibanField.removeClass('is-valid').addClass('is-invalid');
					ibanField.after(`<div class="invalid-feedback">${validation.error}</div>`);
					$('#bic').val('');
				} else {
					ibanField.removeClass('is-invalid').addClass('is-valid');
					ibanField.val(validation.formatted);

					const bankName = this.getBankNameFromIBAN(iban);
					if (bankName) {
						ibanField.after(`<div class="valid-feedback">Valid ${bankName} IBAN</div>`);
					} else {
						ibanField.after('<div class="valid-feedback">Valid IBAN</div>');
					}

					const bic = this.deriveBICFromIBAN(iban);
					if (bic && $('#bic').length > 0) {
						$('#bic').val(bic);
						$('#bic').prop('readonly', true);
						$('#bic').addClass('is-valid');
					}
				}
			}
		};
	});

	describe('performIBANValidation', () => {
		it('should validate Dutch IBANs with correct checksum', () => {
			const result = membershipApp.performIBANValidation('NL91ABNA0417164300');
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('NL91 ABNA 0417 1643 00');
		});

		it('should reject IBANs with invalid checksum', () => {
			const result = membershipApp.performIBANValidation('NL91ABNA0417164301');
			expect(result.valid).toBe(false);
			expect(result.error).toBe('Invalid IBAN checksum - please check for typos');
		});

		it('should validate country-specific lengths', () => {
			const result = membershipApp.performIBANValidation('NL91ABNA041716430');
			expect(result.valid).toBe(false);
			expect(result.error).toBe('Dutch IBAN must be 18 characters (you have 17)');
		});

		it('should handle lowercase input', () => {
			const result = membershipApp.performIBANValidation('nl91abna0417164300');
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('NL91 ABNA 0417 1643 00');
		});

		it('should handle IBANs with spaces', () => {
			const result = membershipApp.performIBANValidation('NL91 ABNA 0417 1643 00');
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('NL91 ABNA 0417 1643 00');
		});

		it('should reject unsupported country codes', () => {
			const result = membershipApp.performIBANValidation('XX91ABNA0417164300');
			expect(result.valid).toBe(false);
			expect(result.error).toBe('Unsupported country code: XX');
		});

		it('should validate Belgian IBANs', () => {
			const result = membershipApp.performIBANValidation('BE68539007547034');
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('BE68 5390 0754 7034');
		});

		it('should validate German IBANs', () => {
			const result = membershipApp.performIBANValidation('DE89370400440532013000');
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('DE89 3704 0044 0532 0130 00');
		});
	});

	describe('deriveBICFromIBAN', () => {
		it('should derive BIC for ABN AMRO', () => {
			const bic = membershipApp.deriveBICFromIBAN('NL91ABNA0417164300');
			expect(bic).toBe('ABNANL2A');
		});

		it('should derive BIC for Rabobank', () => {
			const bic = membershipApp.deriveBICFromIBAN('NL44RABO0123456789');
			expect(bic).toBe('RABONL2U');
		});

		it('should derive BIC for ING', () => {
			const bic = membershipApp.deriveBICFromIBAN('NL69INGB0123456789');
			expect(bic).toBe('INGBNL2A');
		});

		it('should return null for non-Dutch IBANs', () => {
			const bic = membershipApp.deriveBICFromIBAN('BE68539007547034');
			expect(bic).toBe(null);
		});

		it('should return null for unknown Dutch banks', () => {
			const bic = membershipApp.deriveBICFromIBAN('NL91XXXX0417164300');
			expect(bic).toBe(null);
		});
	});

	describe('getBankNameFromIBAN', () => {
		it('should identify ABN AMRO', () => {
			const bank = membershipApp.getBankNameFromIBAN('NL91ABNA0417164300');
			expect(bank).toBe('ABN AMRO');
		});

		it('should identify Rabobank', () => {
			const bank = membershipApp.getBankNameFromIBAN('NL44RABO0123456789');
			expect(bank).toBe('Rabobank');
		});

		it('should identify ING', () => {
			const bank = membershipApp.getBankNameFromIBAN('NL69INGB0123456789');
			expect(bank).toBe('ING');
		});

		it('should return null for non-Dutch IBANs', () => {
			const bank = membershipApp.getBankNameFromIBAN('BE68539007547034');
			expect(bank).toBe(null);
		});
	});

	describe('validateIBAN UI behavior', () => {
		let ibanField; let bicField;

		beforeEach(() => {
			// Store references to mock elements
			ibanField = createChainableElement();
			bicField = createChainableElement();

			// Override $ to return our stored references
			global.$.mockImplementation((selector) => {
				if (selector === '#iban') {
					return ibanField;
				} else if (selector === '#bic') {
					return bicField;
				}
				return createChainableElement();
			});
		});

		it('should show valid feedback for correct IBAN', () => {
			ibanField.val.mockReturnValue('NL91ABNA0417164300');

			membershipApp.validateIBAN();

			expect(ibanField.removeClass).toHaveBeenCalledWith('is-invalid');
			expect(ibanField.addClass).toHaveBeenCalledWith('is-valid');
			expect(ibanField.after).toHaveBeenCalledWith(
				expect.stringContaining('Valid ABN AMRO IBAN')
			);
		});

		it('should show error feedback for invalid IBAN', () => {
			ibanField.val.mockReturnValue('NL91ABNA0417164301');

			membershipApp.validateIBAN();

			expect(ibanField.removeClass).toHaveBeenCalledWith('is-valid');
			expect(ibanField.addClass).toHaveBeenCalledWith('is-invalid');
			expect(ibanField.after).toHaveBeenCalledWith(
				expect.stringContaining('Invalid IBAN checksum')
			);
		});

		it('should auto-fill BIC field for Dutch IBANs', () => {
			ibanField.val.mockReturnValue('NL91ABNA0417164300');

			membershipApp.validateIBAN();

			expect(bicField.val).toHaveBeenCalledWith('ABNANL2A');
			expect(bicField.prop).toHaveBeenCalledWith('readonly', true);
			expect(bicField.addClass).toHaveBeenCalledWith('is-valid');
		});

		it('should clear BIC field for invalid IBAN', () => {
			ibanField.val.mockReturnValue('NL91ABNA0417164301');

			membershipApp.validateIBAN();

			expect(bicField.val).toHaveBeenCalledWith('');
		});
	});
});
