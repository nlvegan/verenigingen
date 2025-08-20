/**
 * Dutch Validation Algorithms for Unit Testing
 * Implements proper BSN, RSIN, IBAN, and postal code validation according to Dutch regulations
 */

/**
 * Validates Dutch BSN (Burgerservicenummer) using the 11-proof algorithm
 * @param {string} bsn - BSN number to validate (can include spaces/dashes)
 * @returns {Object} Validation result with valid flag and error message
 */
function validateBSN(bsn) {
	if (!bsn) {
		return { valid: false, error: 'BSN is required' };
	}

	// Remove all non-digit characters
	const cleaned = bsn.replace(/\D/g, '');

	// Check length
	if (cleaned.length !== 9) {
		return { valid: false, error: 'BSN must be exactly 9 digits' };
	}

	// Convert to array of numbers
	const digits = cleaned.split('').map(Number);

	// Check for obvious invalid patterns (all same digits)
	if (digits.every(digit => digit === digits[0])) {
		return { valid: false, error: 'BSN cannot consist of identical digits' };
	}

	// BSN 11-proof validation algorithm
	const weights = [9, 8, 7, 6, 5, 4, 3, 2, -1];
	const sum = digits.reduce((total, digit, index) => {
		return total + (digit * weights[index]);
	}, 0);

	// The sum must be divisible by 11 and last digit cannot be 0
	const remainder = sum % 11;
	const isValid = remainder === 0 && digits[8] !== 0;

	if (!isValid) {
		return { valid: false, error: 'Invalid BSN checksum' };
	}

	return { valid: true, formatted: cleaned };
}

/**
 * Validates Dutch RSIN (Rechtspersonen Samenwerkingsverbanden Informatie Nummer)
 * Uses same algorithm as BSN but for organizations
 * @param {string} rsin - RSIN number to validate
 * @returns {Object} Validation result with valid flag and error message
 */
function validateRSIN(rsin) {
	if (!rsin) {
		return { valid: false, error: 'RSIN is required' };
	}

	// Remove all non-digit characters
	const cleaned = rsin.replace(/\D/g, '');

	// Check length
	if (cleaned.length !== 9) {
		return { valid: false, error: 'RSIN must be exactly 9 digits' };
	}

	// Convert to array of numbers
	const digits = cleaned.split('').map(Number);

	// RSIN uses same 11-proof algorithm as BSN
	const weights = [9, 8, 7, 6, 5, 4, 3, 2, -1];
	const sum = digits.reduce((total, digit, index) => {
		return total + (digit * weights[index]);
	}, 0);

	// The sum must be divisible by 11
	const remainder = sum % 11;
	const isValid = remainder === 0;

	if (!isValid) {
		return { valid: false, error: 'Invalid RSIN checksum' };
	}

	return { valid: true, formatted: cleaned };
}

/**
 * Validates Dutch IBAN (International Bank Account Number)
 * @param {string} iban - IBAN to validate
 * @returns {Object} Validation result with valid flag and error message
 */
function validateDutchIBAN(iban) {
	if (!iban) {
		return { valid: false, error: 'IBAN is required' };
	}

	// Remove spaces and convert to uppercase
	const cleaned = iban.replace(/\s/g, '').toUpperCase();

	// Check if it starts with NL
	if (!cleaned.startsWith('NL')) {
		return { valid: false, error: 'Dutch IBAN must start with NL' };
	}

	// Check length (Dutch IBAN is always 18 characters)
	if (cleaned.length !== 18) {
		return { valid: false, error: 'Dutch IBAN must be exactly 18 characters' };
	}

	// Extract parts: NL + 2 check digits + 4 bank code + 10 account number
	const checkDigits = cleaned.substring(2, 4);
	const bankCode = cleaned.substring(4, 8);
	const accountNumber = cleaned.substring(8, 18);

	// Validate format (bank code should be letters, account number should be digits)
	if (!/^[A-Z]{4}$/.test(bankCode)) {
		return { valid: false, error: 'Invalid bank code format' };
	}

	if (!/^\d{10}$/.test(accountNumber)) {
		return { valid: false, error: 'Invalid account number format' };
	}

	// IBAN checksum validation (mod 97 algorithm)
	// Move first 4 characters to end and convert letters to numbers
	const rearranged = cleaned.substring(4) + cleaned.substring(0, 4);

	// Convert letters to numbers (A=10, B=11, ..., Z=35)
	const numericString = rearranged.replace(/[A-Z]/g, (char) => {
		return (char.charCodeAt(0) - 55).toString();
	});

	// Calculate mod 97
	let remainder = 0;
	for (let i = 0; i < numericString.length; i++) {
		remainder = (remainder * 10 + parseInt(numericString[i])) % 97;
	}

	if (remainder !== 1) {
		return { valid: false, error: 'Invalid IBAN checksum' };
	}

	return {
		valid: true,
		formatted: cleaned,
		bank_code: bankCode,
		account_number: accountNumber
	};
}

/**
 * Validates Dutch postal code format
 * @param {string} postalCode - Postal code to validate
 * @returns {Object} Validation result with valid flag and error message
 */
function validateDutchPostalCode(postalCode) {
	if (!postalCode) {
		return { valid: false, error: 'Postal code is required' };
	}

	// Remove spaces and convert to uppercase
	const cleaned = postalCode.replace(/\s/g, '').toUpperCase();

	// Dutch postal code pattern: 4 digits + 2 letters
	const pattern = /^(\d{4})([A-Z]{2})$/;
	const match = cleaned.match(pattern);

	if (!match) {
		return { valid: false, error: 'Invalid Dutch postal code format (should be 1234 AB)' };
	}

	const [, digits, letters] = match;

	// First digit cannot be 0
	if (digits[0] === '0') {
		return { valid: false, error: 'Postal code cannot start with 0' };
	}

	// Certain combinations are not used
	const excludedCombinations = ['SA', 'SD', 'SS'];
	if (excludedCombinations.includes(letters)) {
		return { valid: false, error: `Letter combination ${letters} is not used in Dutch postal codes` };
	}

	return {
		valid: true,
		formatted: `${digits} ${letters}`,
		digits,
		letters
	};
}

/**
 * Validates Dutch phone number format
 * @param {string} phoneNumber - Phone number to validate
 * @returns {Object} Validation result with valid flag and error message
 */
function validateDutchPhoneNumber(phoneNumber) {
	if (!phoneNumber) {
		return { valid: false, error: 'Phone number is required' };
	}

	// Remove all non-digit characters except +
	const cleaned = phoneNumber.replace(/[^\d+]/g, '');

	// Dutch mobile patterns
	const mobilePattern = /^(\+31|0031|0)6\d{8}$/;
	// Dutch landline patterns
	const landlinePattern = /^(\+31|0031|0)[1-9]\d{7,8}$/;

	if (mobilePattern.test(cleaned)) {
		return {
			valid: true,
			type: 'mobile',
			formatted: cleaned.replace(/^(\+31|0031)/, '+31 ').replace(/^0/, '+31 ')
		};
	}

	if (landlinePattern.test(cleaned)) {
		return {
			valid: true,
			type: 'landline',
			formatted: cleaned.replace(/^(\+31|0031)/, '+31 ').replace(/^0/, '+31 ')
		};
	}

	return { valid: false, error: 'Invalid Dutch phone number format' };
}

/**
 * Validates BIC (Bank Identifier Code) used in SEPA transactions
 * @param {string} bic - BIC code to validate
 * @returns {Object} Validation result with valid flag and error message
 */
function validateBIC(bic) {
	if (!bic) {
		return { valid: false, error: 'BIC is required' };
	}

	// Remove spaces and convert to uppercase
	const cleaned = bic.replace(/\s/g, '').toUpperCase();

	// BIC format: 4 letters (bank code) + 2 letters (country code) + 2 alphanumeric (location) + optional 3 alphanumeric (branch)
	// Length should be 8 or 11 characters
	if (cleaned.length !== 8 && cleaned.length !== 11) {
		return { valid: false, error: 'BIC must be 8 or 11 characters long' };
	}

	// Check format: AAAA CC LL [BBB]
	const bicPattern = /^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$/;

	if (!bicPattern.test(cleaned)) {
		return { valid: false, error: 'Invalid BIC format' };
	}

	return {
		valid: true,
		formatted: cleaned,
		bank_code: cleaned.substring(0, 4),
		country_code: cleaned.substring(4, 6),
		location_code: cleaned.substring(6, 8),
		branch_code: cleaned.length === 11 ? cleaned.substring(8, 11) : null
	};
}

/**
 * Validates Dutch email address with additional Netherlands-specific checks
 * @param {string} email - Email address to validate
 * @returns {Object} Validation result with valid flag and error message
 */
function validateDutchEmail(email) {
	if (!email) {
		return { valid: false, error: 'Email address is required' };
	}

	// Basic email pattern
	const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

	if (!emailPattern.test(email)) {
		return { valid: false, error: 'Invalid email format' };
	}

	// Convert to lowercase for validation
	const lowerEmail = email.toLowerCase();

	// Check for common Dutch domains
	const dutchDomains = ['.nl', '.eu'];
	const hasDutchDomain = dutchDomains.some(domain => lowerEmail.endsWith(domain));

	return {
		valid: true,
		formatted: lowerEmail,
		is_dutch_domain: hasDutchDomain
	};
}

/**
 * Generates organization email from Dutch name with proper particle handling
 * @param {string} fullName - The full name including particles
 * @param {string} domain - Email domain (default: example.org)
 * @returns {Object} Result with email and validation status
 */
function generateDutchOrganizationEmail(fullName, domain = 'example.org') {
	if (!fullName) {
		return { valid: false, error: 'Name is required' };
	}

	// Replace spaces with dots and convert to lowercase
	let nameForEmail = fullName.replace(/\s+/g, '.').toLowerCase();

	// Handle Dutch particles and special characters properly
	// Keep particles like 'van', 'de', 'der', 'den', 'van der', 'van den', etc.
	// Remove apostrophes but preserve the rest of the name structure
	nameForEmail = nameForEmail.replace(/'/g, ''); // Remove apostrophes
	nameForEmail = nameForEmail.replace(/[^a-z.-]/g, ''); // Keep letters, dots, hyphens

	// Clean up multiple consecutive dots and trim dots from ends
	nameForEmail = nameForEmail.replace(/\.+/g, '.').replace(/^\.+|\.+$/g, '');

	// Handle common hyphenated names (like Jong-van der Berg)
	nameForEmail = nameForEmail.replace(/-/g, '.'); // Replace hyphens with dots
	nameForEmail = nameForEmail.replace(/\.+/g, '.'); // Clean up multiple dots again

	if (!nameForEmail) {
		return { valid: false, error: 'Unable to generate valid email from name' };
	}

	const email = `${nameForEmail}@${domain}`;

	// Validate the generated email
	const emailValidation = validateDutchEmail(email);

	return {
		valid: emailValidation.valid,
		email,
		processed_name: nameForEmail,
		error: emailValidation.valid ? null : emailValidation.error
	};
}

/**
 * Collection of test data generators for Dutch validation scenarios
 */
const dutchTestDataGenerators = {
	/**
     * Generates valid BSN numbers for testing
     * @returns {Array<string>} Array of valid BSN numbers
     */
	validBSNs: [
		'123456782', // Standard test BSN
		'111222333', // Pattern-based test BSN
		'999991772' // Edge case test BSN
	],

	/**
     * Generates invalid BSN numbers for testing
     * @returns {Array<Object>} Array of invalid BSN test cases
     */
	invalidBSNs: [
		{ value: '123456789', error: 'Invalid BSN checksum' },
		{ value: '12345678', error: 'BSN must be exactly 9 digits' },
		{ value: '111111111', error: 'BSN cannot consist of identical digits' },
		{ value: '000000000', error: 'BSN cannot consist of identical digits' },
		{ value: '123456780', error: 'Invalid BSN checksum' },
		// Edge cases
		{ value: '012345678', error: 'Invalid BSN checksum' }, // Leading zero
		{ value: '999999999', error: 'BSN cannot consist of identical digits' },
		{ value: '1234567890', error: 'BSN must be exactly 9 digits' }, // Too long
		{ value: '12345678a', error: 'BSN must be exactly 9 digits' }, // Contains letter
		{ value: '123 456 782', error: 'BSN must be exactly 9 digits' }, // With spaces (should be cleaned)
		{ value: '', error: 'BSN is required' }, // Empty
		{ value: null, error: 'BSN is required' } // Null
	],

	/**
     * Generates valid Dutch IBANs for testing
     * @returns {Array<string>} Array of valid Dutch IBANs
     */
	validIBANs: [
		'NL91 ABNA 0417 1643 00',
		'NL02 RABO 0123 4567 89',
		'NL39 INGB 0001 2345 67'
	],

	/**
     * Generates invalid Dutch IBANs for testing
     * @returns {Array<Object>} Array of invalid IBAN test cases
     */
	invalidIBANs: [
		{ value: 'NL91 ABNA 0417 1643 01', error: 'Invalid IBAN checksum' },
		{ value: 'DE91 ABNA 0417 1643 00', error: 'Dutch IBAN must start with NL' },
		{ value: 'NL91 ABNA 041', error: 'Dutch IBAN must be exactly 18 characters' },
		{ value: 'NL91 1234 0417 1643 00', error: 'Invalid bank code format' },
		// Edge cases
		{ value: 'BE91 ABNA 0417 1643 00', error: 'Dutch IBAN must start with NL' }, // Belgian IBAN
		{ value: 'FR91 ABNA 0417 1643 00', error: 'Dutch IBAN must start with NL' }, // French IBAN
		{ value: 'NL91ABNA041716430012345', error: 'Dutch IBAN must be exactly 18 characters' }, // Too long
		{ value: 'NL91 abna 0417 1643 00', error: 'Invalid bank code format' }, // Lowercase bank code
		{ value: 'NL91 ABNA 041A 1643 00', error: 'Invalid account number format' }, // Letter in account number
		{ value: 'NL91 ABNA 0417 164Z 00', error: 'Invalid account number format' }, // Letter in account number
		{ value: '', error: 'IBAN is required' }, // Empty
		{ value: 'NL', error: 'Dutch IBAN must be exactly 18 characters' }, // Too short
		{ value: 'NL00 RABO 0000 0000 00', error: 'Invalid IBAN checksum' } // Invalid checksum
	],

	/**
     * Generates valid Dutch postal codes for testing
     * @returns {Array<string>} Array of valid postal codes
     */
	validPostalCodes: [
		'1012 AB',
		'2011 CD',
		'3511 EF',
		'9999 ZZ'
	],

	/**
     * Generates invalid Dutch postal codes for testing
     * @returns {Array<Object>} Array of invalid postal code test cases
     */
	invalidPostalCodes: [
		{ value: '0123 AB', error: 'Postal code cannot start with 0' },
		{ value: '1234 SA', error: 'Letter combination SA is not used in Dutch postal codes' },
		{ value: '12345', error: 'Invalid Dutch postal code format (should be 1234 AB)' },
		{ value: 'ABCD EF', error: 'Invalid Dutch postal code format (should be 1234 AB)' },
		// Edge cases
		{ value: '1234 SD', error: 'Letter combination SD is not used in Dutch postal codes' },
		{ value: '1234 SS', error: 'Letter combination SS is not used in Dutch postal codes' },
		{ value: '1234AB', error: 'Invalid Dutch postal code format (should be 1234 AB)' }, // No space
		{ value: '12340 AB', error: 'Invalid Dutch postal code format (should be 1234 AB)' }, // 5 digits
		{ value: '123 AB', error: 'Invalid Dutch postal code format (should be 1234 AB)' }, // 3 digits
		{ value: '1234 A', error: 'Invalid Dutch postal code format (should be 1234 AB)' }, // 1 letter
		{ value: '1234 ABC', error: 'Invalid Dutch postal code format (should be 1234 AB)' }, // 3 letters
		{ value: '', error: 'Postal code is required' }, // Empty
		{ value: null, error: 'Postal code is required' }, // Null
		{ value: '1234  AB', error: 'Invalid Dutch postal code format (should be 1234 AB)' }, // Double space
		{ value: '1234-AB', error: 'Invalid Dutch postal code format (should be 1234 AB)' } // Hyphen instead of space
	],

	/**
     * Generates test data for Dutch name email generation
     * @returns {Array<Object>} Array of name processing test cases
     */
	dutchNameTestCases: [
		{
			input: 'Jan van der Berg',
			expected: 'jan.van.der.berg@example.org',
			description: 'Standard Dutch name with particles'
		},
		{
			input: 'Maria de Jong',
			expected: 'maria.de.jong@example.org',
			description: 'Name with single particle'
		},
		{
			input: 'Peter van \'t Hof',
			expected: 'peter.van.t.hof@example.org',
			description: 'Name with apostrophe'
		},
		{
			input: 'André van den Broek',
			expected: 'andr.van.den.broek@example.org',
			description: 'Name with accented character'
		},
		{
			input: 'Anna-Maria de Jong-van der Berg',
			expected: 'anna.maria.de.jong.van.der.berg@example.org',
			description: 'Hyphenated compound name'
		},
		{
			input: 'Jos van \'t Veld',
			expected: 'jos.van.t.veld@example.org',
			description: 'Name with contracted particle'
		},
		{
			input: 'Pieter van der Meer-de Wit',
			expected: 'pieter.van.der.meer.de.wit@example.org',
			description: 'Complex hyphenated name with multiple particles'
		}
	]
};

module.exports = {
	validateBSN,
	validateRSIN,
	validateDutchIBAN,
	validateDutchPostalCode,
	validateDutchPhoneNumber,
	validateBIC,
	validateDutchEmail,
	generateDutchOrganizationEmail,
	dutchTestDataGenerators
};
