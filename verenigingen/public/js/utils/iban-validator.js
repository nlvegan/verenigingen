/**
 * @fileoverview IBAN Validation Utility for Verenigingen Association Management
 *
 * This utility provides comprehensive International Bank Account Number (IBAN) validation
 * with mod-97 checksum verification, country-specific length validation, and formatting
 * support. It ensures banking information compliance with European SEPA standards.
 *
 * @description Business Context:
 * IBAN validation is critical for SEPA direct debit processing and payment collection
 * from association members. The utility ensures that banking information is valid
 * before creating SEPA mandates or processing payments, preventing failed transactions
 * and maintaining compliance with European banking regulations.
 *
 * @description Validation Features:
 * - ISO 13616 IBAN standard compliance
 * - Mod-97 checksum verification algorithm
 * - Country-specific length validation
 * - Character format validation (alphanumeric only)
 * - Comprehensive error reporting with localized messages
 * - IBAN formatting and cleanup utilities
 *
 * @description Supported Countries:
 * Validates IBANs for all major European countries including Netherlands (NL),
 * Germany (DE), Belgium (BE), France (FR), and other SEPA member states.
 *
 * @description Integration Points:
 * - Used by member registration forms for banking information
 * - Integrated with SEPA mandate creation workflows
 * - Supports payment method validation in donation forms
 * - Coordinates with BIC/SWIFT validation utilities
 *
 * @author Verenigingen Development Team
 * @version 2025-01-13
 * @since 1.0.0
 *
 * @requires None - Standalone utility
 *
 * @example
 * // Validate an IBAN:
 * const result = IBANValidator.validate('NL91 ABNA 0417 1643 00');
 * if (result.valid) {
 *   console.log('Formatted IBAN:', result.formatted);
 * } else {
 *   console.error('Validation error:', result.error);
 * }
 */

/**
 * IBAN Validation Utility Object
 *
 * Provides comprehensive IBAN validation, formatting, and error reporting
 * with support for European SEPA banking standards.
 */
const IBANValidator = {
	// IBAN length specifications by country
	ibanLengths: {
		'AD': 24, 'AT': 20, 'BE': 16, 'CH': 21, 'CZ': 24,
		'DE': 22, 'DK': 18, 'ES': 24, 'FI': 18, 'FR': 27,
		'GB': 22, 'IE': 22, 'IT': 27, 'LU': 20, 'NL': 18,
		'NO': 15, 'PL': 28, 'PT': 25, 'SE': 24
	},

	// Country name mapping for better error messages
	countryNames: {
		'NL': 'Dutch',
		'BE': 'Belgian',
		'DE': 'German',
		'FR': 'French',
		'GB': 'British',
		'IT': 'Italian',
		'ES': 'Spanish',
		'AT': 'Austrian',
		'CH': 'Swiss'
	},

	/**
     * Validate IBAN with comprehensive checks including mod-97
     * @param {string} iban - The IBAN to validate
     * @returns {Object} - { valid: boolean, error: string, formatted: string }
     */
	validate(iban) {
		if (!iban) {
			return { valid: false, error: 'IBAN is required' };
		}

		// Remove spaces and convert to uppercase
		const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

		// Check for invalid characters
		if (!/^[A-Z0-9]+$/.test(cleanIBAN)) {
			return { valid: false, error: 'IBAN contains invalid characters' };
		}

		// Basic format check
		if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(cleanIBAN)) {
			return { valid: false, error: 'Invalid IBAN format' };
		}

		// Extract country code
		const countryCode = cleanIBAN.substring(0, 2);

		// Check if country is supported
		if (!(countryCode in this.ibanLengths)) {
			return { valid: false, error: `Unsupported country code: ${countryCode}` };
		}

		// Check length
		const expectedLength = this.ibanLengths[countryCode];
		if (cleanIBAN.length !== expectedLength) {
			const countryName = this.countryNames[countryCode] || countryCode;
			return {
				valid: false,
				error: `${countryName} IBAN must be ${expectedLength} characters (you have ${cleanIBAN.length})`
			};
		}

		// Perform mod-97 checksum validation
		if (!this.validateChecksum(cleanIBAN)) {
			return { valid: false, error: 'Invalid IBAN checksum - please check for typos' };
		}

		return {
			valid: true,
			error: null,
			formatted: this.format(cleanIBAN)
		};
	},

	/**
     * Validate IBAN checksum using mod-97 algorithm
     * @param {string} iban - Clean IBAN without spaces
     * @returns {boolean} - True if checksum is valid
     */
	validateChecksum(iban) {
		// Move first 4 characters to end
		const rearranged = iban.substring(4) + iban.substring(0, 4);

		// Convert letters to numbers (A=10, B=11, ..., Z=35)
		const numeric = rearranged.replace(/[A-Z]/g, char => char.charCodeAt(0) - 55);

		// Calculate mod 97 using chunks to avoid JavaScript number precision issues
		const remainder = numeric.match(/.{1,9}/g).reduce((acc, chunk) => {
			return (parseInt(acc + chunk) % 97).toString();
		}, '');

		return remainder === '1';
	},

	/**
     * Format IBAN with spaces every 4 characters
     * @param {string} iban - IBAN to format
     * @returns {string} - Formatted IBAN
     */
	format(iban) {
		const clean = iban.replace(/\s/g, '').toUpperCase();
		return clean.match(/.{1,4}/g).join(' ');
	},

	/**
     * Derive BIC from Dutch IBAN
     * @param {string} iban - The IBAN
     * @returns {string|null} - BIC code or null
     */
	deriveBIC(iban) {
		if (!iban) return null;

		const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

		if (!cleanIBAN.startsWith('NL') || cleanIBAN.length < 8) {
			return null;
		}

		const bankCode = cleanIBAN.substring(4, 8);
		const nlBicCodes = {
			'INGB': 'INGBNL2A',
			'ABNA': 'ABNANL2A',
			'RABO': 'RABONL2U',
			'TRIO': 'TRIONL2U',
			'SNSB': 'SNSBNL2A',
			'ASNB': 'ASNBNL21',
			'KNAB': 'KNABNL2H',
			'BUNQ': 'BUNQNL2A',
			'REVO': 'REVOLT21',
			'RBRB': 'RBRBNL21'
		};

		return nlBicCodes[bankCode] || null;
	},

	/**
     * Get bank name from IBAN
     * @param {string} iban - The IBAN
     * @returns {string|null} - Bank name or null
     */
	getBankName(iban) {
		if (!iban) return null;

		const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

		if (!cleanIBAN.startsWith('NL') || cleanIBAN.length < 8) {
			return null;
		}

		const bankCode = cleanIBAN.substring(4, 8);
		const bankNames = {
			'INGB': 'ING',
			'ABNA': 'ABN AMRO',
			'RABO': 'Rabobank',
			'TRIO': 'Triodos Bank',
			'SNSB': 'SNS Bank',
			'ASNB': 'ASN Bank',
			'KNAB': 'Knab',
			'BUNQ': 'Bunq',
			'RBRB': 'RegioBank'
		};

		return bankNames[bankCode] || null;
	}
};

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
	module.exports = IBANValidator;
}

// Also make it globally available for Frappe forms
if (typeof window !== 'undefined') {
	window.IBANValidator = IBANValidator;
}
