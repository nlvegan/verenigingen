/**
 * @fileoverview IBAN Validator Unit Tests - Real-world Banking Validation
 *
 * This test suite validates the IBAN validation utility using realistic European
 * banking data that members would actually use. Tests focus on business-critical
 * validation scenarios without mocking the underlying validation logic.
 *
 * Business Context:
 * IBAN validation is essential for SEPA direct debit processing. Invalid IBANs
 * cause payment failures, member dissatisfaction, and administrative overhead.
 * These tests ensure the validator catches real-world banking errors before
 * they cause payment problems.
 *
 * Test Strategy:
 * - Use real IBAN formats from major European banks
 * - Test actual member scenarios (Dutch focus, European support)
 * - Validate business-critical edge cases (typos, format errors)
 * - No mocking - test the actual validation algorithms
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

const IBANValidator = require('../../public/js/utils/iban-validator.js');

describe('IBAN Validator - Real Banking Scenarios', () => {
	describe('Dutch Banking (Primary Member Base)', () => {
		describe('Major Dutch Banks', () => {
			test('should validate ING Bank IBAN', () => {
				const result = IBANValidator.validate('NL61 INGB 0417 1643 00');

				expect(result.valid).toBe(true);
				expect(result.error).toBeNull();
				expect(result.formatted).toBe('NL61 INGB 0417 1643 00');
			});

			test('should validate ABN AMRO IBAN', () => {
				const result = IBANValidator.validate('NL91 ABNA 0417 1643 00');

				expect(result.valid).toBe(true);
				expect(result.error).toBeNull();
				expect(result.formatted).toBe('NL91 ABNA 0417 1643 00');
			});

			test('should validate Rabobank IBAN', () => {
				const result = IBANValidator.validate('NL39 RABO 0300 0652 64');

				expect(result.valid).toBe(true);
				expect(result.error).toBeNull();
				expect(result.formatted).toBe('NL39 RABO 0300 0652 64');
			});

			test('should validate Triodos Bank IBAN', () => {
				const result = IBANValidator.validate('NL90 TRIO 0338 3343 21');

				expect(result.valid).toBe(true);
				expect(result.error).toBeNull();
				expect(result.formatted).toBe('NL90 TRIO 0338 3343 21');
			});
		});

		describe('Dutch Bank Information Extraction', () => {
			test('should extract BIC code for ING', () => {
				const bic = IBANValidator.deriveBIC('NL61 INGB 0417 1643 00');
				expect(bic).toBe('INGBNL2A');
			});

			test('should extract bank name for ABN AMRO', () => {
				const bankName = IBANValidator.getBankName('NL91 ABNA 0417 1643 00');
				expect(bankName).toBe('ABN AMRO');
			});

			test('should extract bank name for Rabobank', () => {
				const bankName = IBANValidator.getBankName('NL39 RABO 0300 0652 64');
				expect(bankName).toBe('Rabobank');
			});

			test('should return null for unknown Dutch bank code', () => {
				const bankName = IBANValidator.getBankName('NL91 UNKNOWN 0417 1643 00');
				expect(bankName).toBeNull();
			});
		});

		describe('Common Dutch IBAN Errors', () => {
			test('should reject IBAN with incorrect checksum', () => {
				const result = IBANValidator.validate('NL61 INGB 0417 1643 01'); // Changed last digit - should fail checksum

				expect(result.valid).toBe(false);
				expect(result.error).toContain('checksum');
			});

			test('should reject IBAN with wrong length', () => {
				const result = IBANValidator.validate('NL91 INGB 0417 1643 0'); // Too short

				expect(result.valid).toBe(false);
				expect(result.error).toContain('Dutch IBAN must be 18 characters');
			});

			test('should handle IBAN with spaces correctly', () => {
				const result = IBANValidator.validate('  NL61   INGB  0417  1643  00  ');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('NL61 INGB 0417 1643 00');
			});
		});
	});

	describe('European Banking (International Members)', () => {
		describe('Major European Countries', () => {
			test('should validate German IBAN', () => {
				const result = IBANValidator.validate('DE89 3704 0044 0532 0130 00');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('DE89 3704 0044 0532 0130 00');
			});

			test('should validate Belgian IBAN', () => {
				const result = IBANValidator.validate('BE68 5390 0754 7034');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('BE68 5390 0754 7034');
			});

			test('should validate French IBAN', () => {
				const result = IBANValidator.validate('FR14 2004 1010 0505 0001 3M02 606');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('FR14 2004 1010 0505 0001 3M02 606');
			});

			test('should validate British IBAN', () => {
				const result = IBANValidator.validate('GB82 WEST 1234 5698 7654 32');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('GB82 WEST 1234 5698 7654 32');
			});
		});

		describe('European Country Length Validation', () => {
			test('should reject German IBAN with wrong length', () => {
				const result = IBANValidator.validate('DE89 3704 0044 0532 0130'); // Too short

				expect(result.valid).toBe(false);
				expect(result.error).toContain('German IBAN must be 22 characters');
			});

			test('should reject Belgian IBAN with wrong length', () => {
				const result = IBANValidator.validate('BE68 5390 0754 7034 00'); // Too long

				expect(result.valid).toBe(false);
				expect(result.error).toContain('Belgian IBAN must be 16 characters');
			});
		});
	});

	describe('Input Validation and Error Handling', () => {
		describe('Invalid Input Types', () => {
			test('should handle empty IBAN', () => {
				const result = IBANValidator.validate('');

				expect(result.valid).toBe(false);
				expect(result.error).toBe('IBAN is required');
			});

			test('should handle null IBAN', () => {
				const result = IBANValidator.validate(null);

				expect(result.valid).toBe(false);
				expect(result.error).toBe('IBAN is required');
			});

			test('should handle undefined IBAN', () => {
				const result = IBANValidator.validate(undefined);

				expect(result.valid).toBe(false);
				expect(result.error).toBe('IBAN is required');
			});
		});

		describe('Format Validation', () => {
			test('should reject IBAN with invalid characters', () => {
				const result = IBANValidator.validate('NL91 INGB 0417 1643 0!');

				expect(result.valid).toBe(false);
				expect(result.error).toContain('invalid characters');
			});

			test('should reject IBAN with incorrect country format', () => {
				const result = IBANValidator.validate('1L91 INGB 0417 1643 00'); // Number instead of letter

				expect(result.valid).toBe(false);
				expect(result.error).toContain('Invalid IBAN format');
			});

			test('should reject IBAN with unsupported country', () => {
				const result = IBANValidator.validate('XX91 INGB 0417 1643 00');

				expect(result.valid).toBe(false);
				expect(result.error).toContain('Unsupported country code: XX');
			});
		});
	});

	describe('Real Member Data Scenarios', () => {
		describe('Member Registration Edge Cases', () => {
			test('should handle IBAN entered with mixed case', () => {
				const result = IBANValidator.validate('nl61 ingb 0417 1643 00');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('NL61 INGB 0417 1643 00');
			});

			test('should handle IBAN entered without spaces', () => {
				const result = IBANValidator.validate('NL61INGB0417164300');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('NL61 INGB 0417 1643 00');
			});

			test('should handle IBAN with irregular spacing', () => {
				const result = IBANValidator.validate('NL61ING B041 71643 00');

				expect(result.valid).toBe(true);
				expect(result.formatted).toBe('NL61 INGB 0417 1643 00');
			});
		});

		describe('Multi-National Member Support', () => {
			test('should validate member from Germany', () => {
				const result = IBANValidator.validate('DE89 3704 0044 0532 0130 00');

				expect(result.valid).toBe(true);
				expect(result.error).toBeNull();
			});

			test('should validate member from Belgium', () => {
				const result = IBANValidator.validate('BE68 5390 0754 7034');

				expect(result.valid).toBe(true);
				expect(result.error).toBeNull();
			});

			test('should provide helpful error for Belgian member with wrong format', () => {
				const result = IBANValidator.validate('BE68 5390 0754 7034 00');

				expect(result.valid).toBe(false);
				expect(result.error).toContain('Belgian IBAN must be 16 characters');
			});
		});
	});

	describe('Checksum Algorithm Validation', () => {
		describe('Mod-97 Algorithm Edge Cases', () => {
			test('should correctly validate checksum with leading zeros', () => {
				const result = IBANValidator.validate('NL02 ABNA 0123 4567 89');

				expect(result.valid).toBe(true);
			});

			test('should handle large account numbers in checksum calculation', () => {
				const result = IBANValidator.validate('DE50 3704 0044 0999 9999 99');

				// This tests the chunked mod-97 calculation for large numbers
				expect(result.valid).toBe(true);
			});

			test('should detect single digit errors in checksum', () => {
				const validIBAN = 'NL61 INGB 0417 1643 00';
				const invalidIBAN = 'NL62 INGB 0417 1643 00'; // Changed checksum from 61 to 62

				expect(IBANValidator.validate(validIBAN).valid).toBe(true);
				expect(IBANValidator.validate(invalidIBAN).valid).toBe(false);
			});
		});
	});

	describe('Format Utility Functions', () => {
		describe('IBAN Formatting', () => {
			test('should format clean IBAN with spaces', () => {
				const formatted = IBANValidator.format('NL61INGB0417164300');
				expect(formatted).toBe('NL61 INGB 0417 1643 00');
			});

			test('should reformat already spaced IBAN', () => {
				const formatted = IBANValidator.format('NL61 ING B041 7164 300');
				expect(formatted).toBe('NL61 INGB 0417 1643 00');
			});

			test('should handle lowercase formatting', () => {
				const formatted = IBANValidator.format('nl61ingb0417164300');
				expect(formatted).toBe('NL61 INGB 0417 1643 00');
			});
		});
	});
});
