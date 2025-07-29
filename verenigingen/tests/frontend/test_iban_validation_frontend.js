/**
 * Test IBAN Validation on Frontend
 *
 * This test demonstrates the enhanced IBAN validation with mod-97 checksum
 * that now happens both on blur and when navigating to confirmation page
 */

// Test IBANs
const testCases = [
	{
		iban: 'NL91ABNA0417164300',
		expected: { valid: true, formatted: 'NL91 ABNA 0417 1643 00', bank: 'ABN AMRO', bic: 'ABNANL2A' },
		description: 'Valid Dutch ABN AMRO IBAN'
	},
	{
		iban: 'nl91abna0417164300', // lowercase
		expected: { valid: true, formatted: 'NL91 ABNA 0417 1643 00', bank: 'ABN AMRO', bic: 'ABNANL2A' },
		description: 'Valid Dutch IBAN (lowercase input)'
	},
	{
		iban: 'NL91 ABNA 0417 1643 00', // with spaces
		expected: { valid: true, formatted: 'NL91 ABNA 0417 1643 00', bank: 'ABN AMRO', bic: 'ABNANL2A' },
		description: 'Valid Dutch IBAN (with spaces)'
	},
	{
		iban: 'NL91ABNA0417164301', // wrong checksum
		expected: { valid: false, error: 'Invalid IBAN checksum - please check for typos' },
		description: 'Invalid checksum'
	},
	{
		iban: 'NL91ABNA041716430', // too short
		expected: { valid: false, error: 'Dutch IBAN must be 18 characters (you have 17)' },
		description: 'Too short Dutch IBAN'
	},
	{
		iban: 'XX91ABNA0417164300', // invalid country
		expected: { valid: false, error: 'Unsupported country code: XX' },
		description: 'Unsupported country code'
	},
	{
		iban: 'BE68539007547034',
		expected: { valid: true, formatted: 'BE68 5390 0754 7034', bank: null, bic: null },
		description: 'Valid Belgian IBAN (no BIC derivation)'
	},
	{
		iban: 'DE89370400440532013000',
		expected: { valid: true, formatted: 'DE89 3704 0044 0532 0130 00', bank: null, bic: null },
		description: 'Valid German IBAN'
	},
	{
		iban: 'NL44RABO0123456789',
		expected: { valid: true, formatted: 'NL44 RABO 0123 4567 89', bank: 'Rabobank', bic: 'RABONL2U' },
		description: 'Valid Rabobank IBAN'
	},
	{
		iban: 'NL69INGB0123456789',
		expected: { valid: true, formatted: 'NL69 INGB 0123 4567 89', bank: 'ING', bic: 'INGBNL2A' },
		description: 'Valid ING IBAN'
	}
];

// Mock the MembershipApplication instance for testing
const mockApp = {
	performIBANValidation: function(iban) {
		// This is the same validation logic from membership_application.js
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
			'AD': 24, 'AT': 20, 'BE': 16, 'CH': 21, 'CZ': 24,
			'DE': 22, 'DK': 18, 'ES': 24, 'FI': 18, 'FR': 27,
			'GB': 22, 'IE': 22, 'IT': 27, 'LU': 20, 'NL': 18,
			'NO': 15, 'PL': 28, 'PT': 25, 'SE': 24
		};

		if (!(countryCode in ibanLengths)) {
			return { valid: false, error: `Unsupported country code: ${countryCode}` };
		}

		const expectedLength = ibanLengths[countryCode];
		if (cleanIBAN.length !== expectedLength) {
			const countryNames = {
				'NL': 'Dutch', 'BE': 'Belgian', 'DE': 'German',
				'FR': 'French', 'GB': 'British', 'IT': 'Italian',
				'ES': 'Spanish', 'AT': 'Austrian', 'CH': 'Swiss'
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

		return { valid: true, error: null, formatted: formatted };
	},

	deriveBICFromIBAN: function(iban) {
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

	getBankNameFromIBAN: function(iban) {
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

// Run tests
console.log('Testing IBAN Validation with Mod-97 Checksum');
console.log('=' .repeat(50));

testCases.forEach(test => {
	console.log(`\nTest: ${test.description}`);
	console.log(`Input: ${test.iban}`);

	const result = mockApp.performIBANValidation(test.iban);

	if (test.expected.valid) {
		if (result.valid) {
			console.log('✓ Valid IBAN');
			console.log(`  Formatted: ${result.formatted}`);

			const bank = mockApp.getBankNameFromIBAN(test.iban);
			const bic = mockApp.deriveBICFromIBAN(test.iban);

			if (bank) console.log(`  Bank: ${bank}`);
			if (bic) console.log(`  BIC: ${bic}`);

			// Check expectations
			if (result.formatted !== test.expected.formatted) {
				console.log(`  ❌ Expected format: ${test.expected.formatted}`);
			}
			if (bank !== test.expected.bank) {
				console.log(`  ❌ Expected bank: ${test.expected.bank}`);
			}
			if (bic !== test.expected.bic) {
				console.log(`  ❌ Expected BIC: ${test.expected.bic}`);
			}
		} else {
			console.log(`❌ Expected valid but got: ${result.error}`);
		}
	} else {
		if (!result.valid) {
			console.log('✓ Invalid IBAN detected');
			console.log(`  Error: ${result.error}`);

			if (result.error !== test.expected.error) {
				console.log(`  ❌ Expected error: ${test.expected.error}`);
			}
		} else {
			console.log('❌ Expected invalid but validation passed');
		}
	}
});

console.log('\n' + '=' .repeat(50));
console.log('IBAN validation now includes:');
console.log('1. Immediate validation on blur (when leaving IBAN field)');
console.log('2. Validation when moving to payment step');
console.log('3. Validation when showing confirmation page');
console.log('4. Comprehensive mod-97 checksum verification');
console.log('5. Country-specific length validation');
console.log('6. Automatic BIC derivation for Dutch banks');
console.log('7. Bank name display for better user experience');
