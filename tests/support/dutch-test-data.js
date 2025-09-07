/**
 * @fileoverview Dutch Test Data Generator for E2E Testing
 *
 * This module generates realistic Dutch test data for association management
 * testing, including proper names with tussenvoegsel, valid postal codes,
 * and business-compliant data patterns.
 *
 * Features:
 * - Realistic Dutch names with proper tussenvoegsel handling
 * - Valid Dutch postal codes and addresses
 * - Test phone numbers using reserved ranges
 * - Deterministic generation with seeds for reproducible tests
 * - Integration with Enhanced Test Factory patterns
 *
 * @module DutchTestDataGenerator
 * @version 1.0.0
 */

class DutchTestDataGenerator {
	constructor(options = {}) {
		this.seed = options.seed || Date.now();
		this.useFaker = options.useFaker !== false;

		// Dutch name data
		this.dutchFirstNames = [
			'Jan', 'Pieter', 'Klaas', 'Willem', 'Hendrik', 'Johannes', 'Gerrit', 'Cornelis',
			'Maria', 'Anna', 'Johanna', 'Elisabeth', 'Catharina', 'Margaretha', 'Geertje', 'Antje',
			'Daan', 'Luuk', 'Bram', 'Thijs', 'Sem', 'Milan', 'Stijn', 'Tim',
			'Emma', 'Lieke', 'Sophie', 'Saar', 'Isa', 'Fleur', 'Femke', 'Maud'
		];

		this.dutchLastNames = [
			'Jansen', 'Hansen', 'Bakker', 'Visser', 'Smit', 'Meijer', 'Boer', 'Mulder',
			'Groot', 'Peters', 'Hendriks', 'Dekker', 'Vink', 'Kok', 'Brouwer', 'Wit',
			'Heuvel', 'Dijk', 'Berg', 'Vries', 'Hoek', 'Koning', 'Prins', 'Roos'
		];

		this.tussenvoegsel = [
			'de', 'van', 'van de', 'van der', 'der', 'den', 'te', 'ter', 'op de', 'in de',
			'van het', 'op het', 'aan de', 'bij de', 'onder de', 'over de'
		];

		this.dutchCities = [
			{ name: 'Amsterdam', postalPrefix: '10' },
			{ name: 'Rotterdam', postalPrefix: '30' },
			{ name: 'Den Haag', postalPrefix: '25' },
			{ name: 'Utrecht', postalPrefix: '35' },
			{ name: 'Eindhoven', postalPrefix: '56' },
			{ name: 'Groningen', postalPrefix: '97' },
			{ name: 'Tilburg', postalPrefix: '50' },
			{ name: 'Almere', postalPrefix: '13' }
		];

		this.streetNames = [
			'Hoofdstraat', 'Kerkstraat', 'Schoolstraat', 'Dorpsstraat', 'Molenstraat',
			'Nieuwstraat', 'Herenstraat', 'Marktstraat', 'Koningstraat', 'Stationsstraat',
			'Prins Hendriklaan', 'Wilhelminalaan', 'Beatrixstraat', 'Oranjeplein'
		];

		this.currentIndex = 0;
	}

	/**
   * Generate a seeded random number
   */
	seededRandom() {
		const x = Math.sin(this.seed + this.currentIndex++) * 10000;
		return x - Math.floor(x);
	}

	/**
   * Get random item from array using seeded random
   */
	randomFromArray(arr) {
		const index = Math.floor(this.seededRandom() * arr.length);
		return arr[index];
	}

	/**
   * Generate random number within range
   */
	randomInRange(min, max) {
		return Math.floor(this.seededRandom() * (max - min + 1)) + min;
	}

	/**
   * Generate a valid Dutch postal code
   */
	generatePostalCode(cityPrefix = null) {
		const prefix = cityPrefix || this.randomInRange(10, 99).toString();
		const suffix = this.randomInRange(10, 99);
		const letters = String.fromCharCode(
			65 + this.randomInRange(0, 25),
			65 + this.randomInRange(0, 25)
		);
		return `${prefix}${suffix} ${letters}`;
	}

	/**
   * Generate a test phone number using reserved ranges
   */
	generatePhoneNumber() {
		// Use 06-1234xxxx range reserved for testing
		const base = '06-1234';
		const suffix = this.randomInRange(1000, 9999);
		return `${base}${suffix}`;
	}

	/**
   * Generate a test email address
   */
	generateEmail(firstName, lastName, tussenvoegsel = null) {
		const cleanFirstName = firstName.toLowerCase().replace(/[^a-z]/g, '');
		const cleanLastName = lastName.toLowerCase().replace(/[^a-z]/g, '');
		const domain = 'test-verenigingen.nl';
		const timestamp = Math.floor(this.seededRandom() * 10000);

		return `${cleanFirstName}.${cleanLastName}.${timestamp}@${domain}`;
	}

	/**
   * Generate complete donor data with Dutch characteristics
   */
	generateDonorData(options = {}) {
		const {
			includeDetails = false,
			donationType = 'single',
			useTussenvoegsel = Math.random() > 0.7 // 30% chance of tussenvoegsel
		} = options;

		const firstName = this.randomFromArray(this.dutchFirstNames);
		const lastName = this.randomFromArray(this.dutchLastNames);
		const tussenv = useTussenvoegsel ? this.randomFromArray(this.tussenvoegsel) : null;

		const city = this.randomFromArray(this.dutchCities);
		const street = this.randomFromArray(this.streetNames);
		const houseNumber = this.randomInRange(1, 299);

		const testId = `test-${this.seed}-${this.currentIndex}`;

		const baseData = {
			testId,
			firstName,
			lastName,
			tussenvoegsel: tussenv,
			fullName: tussenv ? `${firstName} ${tussenv} ${lastName}` : `${firstName} ${lastName}`,
			email: this.generateEmail(firstName, lastName, tussenv),
			phone: this.generatePhoneNumber(),
			donationType
		};

		if (includeDetails) {
			baseData.address = {
				street: `${street} ${houseNumber}`,
				postalCode: this.generatePostalCode(city.postalPrefix),
				city: city.name,
				country: 'Nederland'
			};

			baseData.birthDate = this.generateBirthDate();
			baseData.donationPreferences = this.generateDonationPreferences(donationType);
		}

		return baseData;
	}

	/**
   * Generate a realistic birth date (18-80 years old)
   */
	generateBirthDate() {
		const currentYear = new Date().getFullYear();
		const birthYear = currentYear - this.randomInRange(18, 80);
		const birthMonth = this.randomInRange(1, 12);
		const birthDay = this.randomInRange(1, 28); // Safe day for all months

		return `${birthYear}-${birthMonth.toString().padStart(2, '0')}-${birthDay.toString().padStart(2, '0')}`;
	}

	/**
   * Generate donation preferences based on type
   */
	generateDonationPreferences(donationType) {
		const preferences = {
			communicationPreference: this.randomFromArray(['Email', 'Post', 'Phone']),
			anbiOptIn: this.seededRandom() > 0.3, // 70% opt in for ANBI
			newsletterOptIn: this.seededRandom() > 0.4 // 60% opt in for newsletter
		};

		if (donationType === 'recurring') {
			preferences.recurringFrequency = this.randomFromArray(['Monthly', 'Quarterly', 'Yearly']);
			preferences.recurringAmount = this.randomFromArray([15.00, 25.00, 50.00, 100.00]);
		}

		return preferences;
	}

	/**
   * Generate batch of test donors for performance testing
   */
	generateBatch(count, options = {}) {
		const batch = [];
		for (let i = 0; i < count; i++) {
			// Use different seed for each donor in batch
			const originalSeed = this.seed;
			this.seed = originalSeed + i * 1000;
			this.currentIndex = 0;

			batch.push(this.generateDonorData({
				...options,
				batchIndex: i
			}));

			this.seed = originalSeed;
		}
		return batch;
	}

	/**
   * Generate test data that matches Enhanced Test Factory patterns
   */
	generateEnhancedTestData(memberType = 'regular') {
		const data = this.generateDonorData({ includeDetails: true });

		// Add Enhanced Test Factory compatible fields
		return {
			...data,
			memberType,
			validationRules: {
				minAge: 18,
				maxAge: 120,
				emailRequired: true,
				phoneRequired: false
			},
			businessRules: {
				canBeVolunteer: this.calculateAge(data.birthDate) >= 16,
				eligibleForMembership: this.calculateAge(data.birthDate) >= 18,
				requiresParentalConsent: this.calculateAge(data.birthDate) < 18
			}
		};
	}

	/**
   * Calculate age from birth date
   */
	calculateAge(birthDate) {
		const birth = new Date(birthDate);
		const today = new Date();
		let age = today.getFullYear() - birth.getFullYear();
		const monthDiff = today.getMonth() - birth.getMonth();

		if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
			age--;
		}

		return age;
	}

	/**
   * Generate IBAN for testing (using Dutch test IBAN format)
   */
	generateTestIBAN() {
		// Dutch test IBAN format: NL##TEST0000000###
		const accountNumber = this.randomInRange(100000000, 999999999);
		const checkDigits = this.randomInRange(10, 99);
		return `NL${checkDigits}TEST${accountNumber}`;
	}

	/**
   * Reset generator state for reproducible tests
   */
	reset(newSeed = null) {
		if (newSeed !== null) {
			this.seed = newSeed;
		}
		this.currentIndex = 0;
	}
}

module.exports = { DutchTestDataGenerator };
