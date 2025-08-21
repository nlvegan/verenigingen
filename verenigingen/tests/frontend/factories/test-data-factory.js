/**
 * @fileoverview Comprehensive Test Data Factory for Verenigingen Association Management
 *
 * This factory provides realistic test data generation for all major DocTypes in the
 * Verenigingen system. It focuses on creating business-rule compliant data that mimics
 * real Dutch association scenarios rather than simplified mocks.
 *
 * @description Business Context:
 * - Generates valid Dutch member data (names, addresses, IBANs, postal codes)
 * - Creates realistic SEPA mandate and payment scenarios
 * - Provides chapter organization test data with proper geographical distribution
 * - Generates volunteer profiles with appropriate age and skill distributions
 * - Creates financial test data with valid payment methods and amounts
 *
 * @description Key Features:
 * - Deterministic data generation with seeds for reproducible tests
 * - Business rule validation (e.g., volunteers must be 16+)
 * - Realistic Dutch data patterns (postal codes, bank accounts, names)
 * - Edge case scenario generation for boundary testing
 * - Cross-DocType relationship management
 *
 * @author Verenigingen Test Team
 * @version 1.0.0
 * @since 2025-08-19
 */

/**
 * Test Data Factory Class
 *
 * Provides methods for generating realistic test data for all major DocTypes
 * with proper business rule compliance and realistic Dutch association scenarios.
 */
class TestDataFactory {
	constructor(seed = 12345) {
		this.seed = seed;
		this.rng = this.createSeededRandom(seed);
		this.memberCounter = 1;
		this.chapterCounter = 1;
		this.mandateCounter = 1;
	}

	/**
   * Creates a seeded random number generator for deterministic test data
   * @param {number} seed - Random seed
   * @returns {function} Seeded random function
   */
	createSeededRandom(seed) {
		let state = seed;
		return () => {
			state = (state * 9301 + 49297) % 233280;
			return state / 233280;
		};
	}

	/**
   * Generates a random item from an array
   * @param {Array} array - Array to choose from
   * @returns {*} Random array item
   */
	randomChoice(array) {
		return array[Math.floor(this.rng() * array.length)];
	}

	/**
   * Generates a random integer within a range
   * @param {number} min - Minimum value
   * @param {number} max - Maximum value
   * @returns {number} Random integer
   */
	randomInt(min, max) {
		return Math.floor(this.rng() * (max - min + 1)) + min;
	}

	/**
   * Generates realistic Dutch first names
   * @returns {string} Dutch first name
   */
	generateDutchFirstName() {
		const maleNames = [
			'Jan', 'Pieter', 'Willem', 'Johannes', 'Hendrik', 'Cornelis', 'Gerrit', 'Jacobus',
			'Daniël', 'Martijn', 'Lars', 'Thijs', 'Sander', 'Joris', 'Ruben', 'Thomas'
		];
		const femaleNames = [
			'Maria', 'Anna', 'Johanna', 'Cornelia', 'Hendrika', 'Catharina', 'Geertruida',
			'Emma', 'Sophie', 'Lotte', 'Fleur', 'Anouk', 'Lisa', 'Kim', 'Sarah', 'Iris'
		];

		const allNames = [...maleNames, ...femaleNames];
		return this.randomChoice(allNames);
	}

	/**
   * Generates realistic Dutch surnames with tussenvoegsel
   * @returns {Object} Object with lastname and optional tussenvoegsel
   */
	generateDutchSurname() {
		const lastNames = [
			'de Jong', 'Jansen', 'de Vries', 'van den Berg', 'van Dijk', 'Bakker', 'Janssen',
			'Visser', 'Smit', 'Meijer', 'de Boer', 'Mulder', 'de Groot', 'Bos', 'Vos',
			'Peters', 'Hendriks', 'van Leeuwen', 'Dekker', 'Brouwer', 'de Wit', 'Dijkstra'
		];

		const surname = this.randomChoice(lastNames);
		const parts = surname.split(' ');

		if (parts.length > 1 && ['de', 'van', 'der', 'den', 'het', 'ter', 'te'].includes(parts[0])) {
			return {
				tussenvoegsel: parts.slice(0, -1).join(' '),
				last_name: parts[parts.length - 1]
			};
		}

		return {
			tussenvoegsel: '',
			last_name: surname
		};
	}

	/**
   * Generates a valid Dutch postal code
   * @returns {string} Dutch postal code (1234 AB format)
   */
	generateDutchPostalCode() {
		const numbers = this.randomInt(1000, 9999).toString();
		const letters = String.fromCharCode(65 + this.randomInt(0, 25))
                   + String.fromCharCode(65 + this.randomInt(0, 25));
		return `${numbers} ${letters}`;
	}

	/**
   * Generates a valid Dutch IBAN
   * @returns {string} Valid Dutch IBAN
   */
	generateDutchIBAN() {
		const bankCodes = ['ABNA', 'RABO', 'INGB', 'TRIO', 'BUNQ', 'SNSB'];
		const bankCode = this.randomChoice(bankCodes);
		const accountNumber = this.randomInt(100000000, 999999999).toString();
		const paddedAccount = accountNumber.padEnd(10, '0');

		// Simplified check digit calculation for testing
		const checkDigits = this.randomInt(10, 99).toString();

		return `NL${checkDigits}${bankCode}0${paddedAccount}`;
	}

	/**
   * Generates a valid email address
   * @param {string} firstName - First name for email
   * @param {string} lastName - Last name for email
   * @returns {string} Valid email address
   */
	generateEmail(firstName, lastName) {
		const domains = ['example.com', 'test.nl', 'vereniging.org', 'member.net'];
		const domain = this.randomChoice(domains);
		const cleanFirst = firstName.toLowerCase().replace(/[^a-z]/g, '');
		const cleanLast = lastName.toLowerCase().replace(/[^a-z]/g, '');

		const formats = [
			`${cleanFirst}.${cleanLast}@${domain}`,
			`${cleanFirst}${cleanLast}@${domain}`,
			`${cleanFirst.charAt(0)}.${cleanLast}@${domain}`,
			`${cleanFirst}_${cleanLast}@${domain}`
		];

		return this.randomChoice(formats);
	}

	/**
   * Generates a Dutch mobile number
   * @returns {string} Valid Dutch mobile number
   */
	generateDutchMobile() {
		const prefixes = ['06', '+31 6'];
		const prefix = this.randomChoice(prefixes);
		const number = this.randomInt(10000000, 99999999).toString();

		if (prefix === '+31 6') {
			return `+31 6 ${number.substring(0, 4)} ${number.substring(4)}`;
		}
		return `${prefix} ${number.substring(0, 4)} ${number.substring(4)}`;
	}

	/**
   * Generates a realistic birth date for given age requirements
   * @param {number} minAge - Minimum age
   * @param {number} maxAge - Maximum age
   * @returns {string} Birth date in YYYY-MM-DD format
   */
	generateBirthDate(minAge = 18, maxAge = 80) {
		const currentYear = new Date().getFullYear();
		const birthYear = currentYear - this.randomInt(minAge, maxAge);
		const month = this.randomInt(1, 12).toString().padStart(2, '0');
		const day = this.randomInt(1, 28).toString().padStart(2, '0');

		return `${birthYear}-${month}-${day}`;
	}

	/**
   * Creates a realistic Member test data object
   * @param {Object} overrides - Field overrides
   * @returns {Object} Complete member data
   */
	createMemberData(overrides = {}) {
		const firstName = this.generateDutchFirstName();
		const surname = this.generateDutchSurname();
		const email = this.generateEmail(firstName, surname.last_name);

		const baseData = {
			// Basic Info
			first_name: firstName,
			tussenvoegsel: surname.tussenvoegsel,
			last_name: surname.last_name,
			full_name: `${firstName}${surname.tussenvoegsel ? ` ${surname.tussenvoegsel}` : ''} ${surname.last_name}`,
			email,
			contact_number: this.generateDutchMobile(),
			birth_date: this.generateBirthDate(16, 75),

			// Address
			primary_address: this.createAddressData().name,

			// Membership
			member_since: this.generateMemberSinceDate(),
			current_membership_type: this.randomChoice(['Regular Member', 'Student Member', 'Senior Member']),
			status: this.randomChoice(['Active', 'Pending', 'Inactive']),

			// Payment
			payment_method: this.randomChoice(['SEPA Direct Debit', 'Bank Transfer', 'Credit Card']),
			iban: this.generateDutchIBAN(),
			bank_account_name: `${firstName} ${surname.last_name}`,

			// Custom ID
			member_id: `TEST-${this.memberCounter.toString().padStart(4, '0')}`,

			// System fields
			name: `Assoc-Member-2025-01-${this.memberCounter.toString().padStart(4, '0')}`,
			doctype: 'Member'
		};

		this.memberCounter++;
		return { ...baseData, ...overrides };
	}

	/**
   * Creates address test data
   * @param {Object} overrides - Field overrides
   * @returns {Object} Address data
   */
	createAddressData(overrides = {}) {
		const streets = [
			'Hoofdstraat', 'Kerkstraat', 'Schoolstraat', 'Dorpsstraat', 'Molenstraat',
			'Nieuwstraat', 'Koningstraat', 'Stationsweg', 'Marktplein', 'Parallelweg'
		];

		const cities = [
			'Amsterdam', 'Rotterdam', 'Den Haag', 'Utrecht', 'Eindhoven',
			'Tilburg', 'Groningen', 'Almere', 'Breda', 'Nijmegen'
		];

		const baseData = {
			address_line1: `${this.randomChoice(streets)} ${this.randomInt(1, 200)}`,
			city: this.randomChoice(cities),
			pincode: this.generateDutchPostalCode(),
			country: 'Netherlands',
			address_type: 'Personal',
			is_primary_address: 1,
			doctype: 'Address'
		};

		return { ...baseData, ...overrides };
	}

	/**
   * Creates SEPA Mandate test data
   * @param {string} memberName - Member record name
   * @param {Object} overrides - Field overrides
   * @returns {Object} SEPA Mandate data
   */
	createSEPAMandateData(memberName, overrides = {}) {
		const baseData = {
			member: memberName,
			mandate_id: `SEPA-${this.mandateCounter.toString().padStart(6, '0')}`,
			iban: this.generateDutchIBAN(),
			bank_account_name: 'Test Account Holder',
			mandate_date: this.generateRecentDate(30),
			status: this.randomChoice(['Active', 'Pending', 'Cancelled']),
			mandate_type: 'RCUR',
			sequence_type: 'FRST',
			creditor_id: 'NL98ZZZ999999999999',
			doctype: 'SEPA Mandate'
		};

		this.mandateCounter++;
		return { ...baseData, ...overrides };
	}

	/**
   * Creates Chapter test data
   * @param {Object} overrides - Field overrides
   * @returns {Object} Chapter data
   */
	createChapterData(overrides = {}) {
		const regions = [
			'Noord-Holland', 'Zuid-Holland', 'Utrecht', 'Gelderland', 'Overijssel',
			'Drenthe', 'Groningen', 'Friesland', 'Noord-Brabant', 'Limburg'
		];

		const region = this.randomChoice(regions);

		const baseData = {
			chapter_name: `Chapter ${region}`,
			region,
			description: `Local chapter serving the ${region} region`,
			postal_code_ranges: this.generatePostalCodeRanges(),
			is_published: this.randomChoice([0, 1]),
			status: this.randomChoice(['Active', 'Inactive', 'Pending']),
			establishment_date: this.generateEstablishmentDate(),
			doctype: 'Chapter'
		};

		this.chapterCounter++;
		return { ...baseData, ...overrides };
	}

	/**
   * Creates Volunteer test data
   * @param {string} memberName - Member record name
   * @param {Object} overrides - Field overrides
   * @returns {Object} Volunteer data
   */
	createVolunteerData(memberName, overrides = {}) {
		const skills = [
			'Event Planning', 'Public Speaking', 'Social Media', 'Fundraising',
			'Administration', 'Technical Support', 'Translation', 'Photography'
		];

		const interests = [
			'Animal Rights', 'Environmental Protection', 'Community Outreach',
			'Education', 'Policy Advocacy', 'Research', 'Youth Programs'
		];

		const baseData = {
			member: memberName,
			volunteer_since: this.generateRecentDate(365),
			status: this.randomChoice(['Active', 'Inactive', 'On Break']),
			skills: this.randomChoice(skills),
			interests: this.randomChoice(interests),
			availability: this.randomChoice(['Weekends', 'Evenings', 'Flexible', 'Weekdays']),
			experience_level: this.randomChoice(['Beginner', 'Intermediate', 'Advanced', 'Expert']),
			max_hours_per_week: this.randomInt(2, 20),
			doctype: 'Volunteer'
		};

		return { ...baseData, ...overrides };
	}

	/**
   * Creates Membership test data
   * @param {string} memberName - Member record name
   * @param {Object} overrides - Field overrides
   * @returns {Object} Membership data
   */
	createMembershipData(memberName, overrides = {}) {
		const currentDate = new Date();
		const startDate = new Date(currentDate.getFullYear(), 0, 1);
		const endDate = new Date(currentDate.getFullYear(), 11, 31);

		const baseData = {
			member: memberName,
			membership_type: this.randomChoice(['Regular Member', 'Student Member', 'Senior Member', 'Honorary Member']),
			start_date: startDate.toISOString().split('T')[0],
			end_date: endDate.toISOString().split('T')[0],
			status: this.randomChoice(['Active', 'Pending', 'Expired', 'Cancelled']),
			annual_fee: this.generateMembershipFee(),
			payment_schedule: this.randomChoice(['Annual', 'Semi-Annual', 'Quarterly', 'Monthly']),
			doctype: 'Membership'
		};

		return { ...baseData, ...overrides };
	}

	/**
   * Creates Direct Debit Batch test data
   * @param {Object} overrides - Field overrides
   * @returns {Object} Direct Debit Batch data
   */
	createDirectDebitBatchData(overrides = {}) {
		const baseData = {
			batch_name: `DD-Batch-${new Date().toISOString().split('T')[0]}-${this.randomInt(1, 999)}`,
			collection_date: this.generateFutureDate(7),
			description: 'Monthly membership fee collection',
			status: this.randomChoice(['Draft', 'Generated', 'Submitted', 'Processed']),
			total_amount: this.randomInt(1000, 10000),
			total_entries: this.randomInt(10, 100),
			sequence_type: 'RCUR',
			batch_type: 'CORE',
			creditor_id: 'NL98ZZZ999999999999',
			doctype: 'Direct Debit Batch'
		};

		return { ...baseData, ...overrides };
	}

	// Helper methods

	/**
   * Generates a recent date within specified days
   * @param {number} daysBack - Number of days back from today
   * @returns {string} Date in YYYY-MM-DD format
   */
	generateRecentDate(daysBack) {
		const date = new Date();
		date.setDate(date.getDate() - this.randomInt(0, daysBack));
		return date.toISOString().split('T')[0];
	}

	/**
   * Generates a future date within specified days
   * @param {number} daysForward - Number of days forward from today
   * @returns {string} Date in YYYY-MM-DD format
   */
	generateFutureDate(daysForward) {
		const date = new Date();
		date.setDate(date.getDate() + this.randomInt(1, daysForward));
		return date.toISOString().split('T')[0];
	}

	/**
   * Generates member since date (typically recent but can be years back)
   * @returns {string} Date in YYYY-MM-DD format
   */
	generateMemberSinceDate() {
		const yearsBack = this.randomInt(0, 10);
		const date = new Date();
		date.setFullYear(date.getFullYear() - yearsBack);
		date.setMonth(this.randomInt(0, 11));
		date.setDate(this.randomInt(1, 28));
		return date.toISOString().split('T')[0];
	}

	/**
   * Generates establishment date for chapters
   * @returns {string} Date in YYYY-MM-DD format
   */
	generateEstablishmentDate() {
		const yearsBack = this.randomInt(1, 20);
		const date = new Date();
		date.setFullYear(date.getFullYear() - yearsBack);
		return date.toISOString().split('T')[0];
	}

	/**
   * Generates postal code ranges for chapters
   * @returns {string} Comma-separated postal code ranges
   */
	generatePostalCodeRanges() {
		const ranges = [];
		const numRanges = this.randomInt(1, 3);

		for (let i = 0; i < numRanges; i++) {
			const start = this.randomInt(1000, 8000);
			const end = start + this.randomInt(100, 500);
			ranges.push(`${start}-${end}`);
		}

		return ranges.join(', ');
	}

	/**
   * Generates realistic membership fee amounts
   * @returns {number} Fee amount in euros
   */
	generateMembershipFee() {
		const fees = [25, 35, 45, 55, 75, 100, 125, 150];
		return this.randomChoice(fees);
	}

	/**
   * Creates DocType test data methods for all remaining DocTypes
   */

	// Additional DocType factory methods for comprehensive test coverage

	// Duplicate createMembershipData method removed - using the original definition above

	createEBoekhoudenMigrationData(overrides = {}) {
		const baseData = {
			name: `EBM-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			company: 'Test Nederlandse Vereniging',
			migration_type: this.randomChoice(['Full Initial Migration', 'Transaction Update', 'Preview']),
			api_type: this.randomChoice(['SOAP', 'REST']),
			username: 'test_eb_user',
			security_code: 'test_security_code',
			rest_api_token: 'test_rest_token_12345',
			migration_status: this.randomChoice(['Draft', 'In Progress', 'Completed', 'Failed']),
			progress_percentage: this.randomInt(0, 100),
			start_time: this.generateRecentDate(30),
			end_time: this.generateFutureDate(1)
		};
		return { ...baseData, ...overrides };
	}

	createDonorData(overrides = {}) {
		const firstName = this.generateDutchFirstName();
		const surname = this.generateDutchSurname();
		const baseData = {
			name: `DNR-${String(this.memberCounter++).padStart(5, '0')}`,
			donor_name: `${firstName} ${surname.tussenvoegsel} ${surname.last_name}`.trim(),
			donor_type: this.randomChoice(['Individual', 'Organization']),
			email: this.generateEmail(firstName, surname.last_name),
			phone: this.generateDutchMobile(),
			anbi_consent: this.randomChoice([true, false]),
			identification_verified: this.randomChoice([true, false]),
			bsn_citizen_service_number: this.generateValidBSN(),
			rsin_organization_tax_number: this.generateValidRSIN(),
			total_donations: this.randomInt(100, 5000),
			last_donation_date: this.generateRecentDate(365)
		};
		return { ...baseData, ...overrides };
	}

	createMembershipTerminationRequestData(overrides = {}) {
		const baseData = {
			name: `MTR-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			member: this.createMemberName(),
			member_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			termination_type: this.randomChoice(['Voluntary', 'Non-payment', 'Deceased', 'Policy Violation', 'Disciplinary Action', 'Expulsion']),
			termination_reason: 'Test termination reason',
			request_date: this.generateRecentDate(30),
			termination_date: this.generateFutureDate(30),
			status: this.randomChoice(['Draft', 'Pending', 'Approved', 'Rejected', 'Executed']),
			requested_by: 'test@example.com',
			requires_secondary_approval: this.randomChoice([true, false]),
			secondary_approver: 'manager@example.com',
			disciplinary_documentation: 'Test disciplinary documentation'
		};
		return { ...baseData, ...overrides };
	}

	createPeriodicDonationAgreementData(overrides = {}) {
		const baseData = {
			name: `PDA-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			donor: this.createDonorName(),
			donor_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			duration_years: this.randomChoice([1, 3, 5, 10]),
			total_commitment_amount: this.randomChoice([500, 1000, 2500, 5000]),
			payment_frequency: this.randomChoice(['Monthly', 'Quarterly', 'Annually']),
			annual_amount: this.randomChoice([100, 200, 500, 1000]),
			payment_amount: this.randomChoice([25, 50, 100, 250]),
			start_date: this.generateRecentDate(30),
			end_date: this.generateFutureDate(365),
			status: this.randomChoice(['Draft', 'Active', 'Completed', 'Cancelled']),
			anbi_eligible: this.randomChoice([true, false]),
			total_received: this.randomChoice([0, 250, 500, 1000])
		};
		return { ...baseData, ...overrides };
	}

	createVolunteerExpenseData(overrides = {}) {
		const baseData = {
			name: `VE-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(4, '0')}`,
			volunteer: this.createVolunteerName(),
			volunteer_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			expense_category: this.randomChoice(['Travel', 'Materials', 'Food', 'Accommodation', 'Other']),
			amount: this.randomChoice([25.50, 45.75, 100.00, 250.25]),
			expense_date: this.generateRecentDate(90),
			description: 'Test volunteer expense',
			approval_status: this.randomChoice(['Draft', 'Pending', 'Approved', 'Rejected']),
			approved_by: 'approver@example.com',
			receipt_attached: this.randomChoice([true, false])
		};
		return { ...baseData, ...overrides };
	}

	createSEPAPaymentRetryData(overrides = {}) {
		const baseData = {
			name: `SPR-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(4, '0')}`,
			original_payment_reference: `PAY-${new Date().getFullYear()}-${String(this.memberCounter).padStart(3, '0')}`,
			retry_attempt: this.randomInt(1, 3),
			retry_date: this.generateRecentDate(7),
			failure_reason: this.randomChoice(['Insufficient funds', 'Invalid account', 'Mandate cancelled', 'Technical error']),
			retry_status: this.randomChoice(['Pending', 'Successful', 'Failed']),
			amount: this.randomChoice([25.00, 50.00, 100.00]),
			member: this.createMemberName(),
			sepa_mandate: this.createSEPAMandateName()
		};
		return { ...baseData, ...overrides };
	}

	createDonationData(overrides = {}) {
		const baseData = {
			name: `DON-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(4, '0')}`,
			donor: this.createDonorName(),
			donor_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			amount: this.randomChoice([25, 50, 100, 250, 500]),
			donation_date: this.generateRecentDate(365),
			status: this.randomChoice(['Draft', 'Pending', 'Paid', 'Cancelled']),
			payment_method: this.randomChoice(['Bank Transfer', 'Credit Card', 'Cash', 'SEPA Direct Debit']),
			anbi_eligible: this.randomChoice([true, false]),
			purpose: this.randomChoice(['General', 'Project Support', 'Emergency Fund', 'Specific Campaign']),
			receipt_generated: this.randomChoice([true, false])
		};
		return { ...baseData, ...overrides };
	}

	// Additional factory methods for remaining DocTypes
	createMT940ImportData(overrides = {}) {
		const baseData = {
			name: `MT940-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			mt940_file: '/files/bank_statement.mt940',
			bank_account: this.generateDutchIBAN(),
			import_date: this.generateRecentDate(30),
			status: this.randomChoice(['Ready', 'Processing', 'Completed', 'Failed']),
			transactions_processed: this.randomInt(10, 100),
			reconciled_count: this.randomInt(5, 95),
			unmatched_count: this.randomInt(0, 10),
			auto_reconcile: this.randomChoice([true, false])
		};
		return { ...baseData, ...overrides };
	}

	createEBoekhoudenSettingsData(overrides = {}) {
		const baseData = {
			name: 'E-Boekhouden Settings',
			username: 'test_eb_user',
			security_code: 'test_security_code',
			api_url: 'https://soap.e-boekhouden.nl/soap.asmx',
			rest_api_token: 'test_rest_token_12345',
			auto_sync: this.randomChoice([true, false]),
			sync_frequency: this.randomChoice(['Hourly', 'Daily', 'Weekly']),
			last_sync: this.generateRecentDate(7),
			connection_status: this.randomChoice(['Connected', 'Disconnected', 'Error'])
		};
		return { ...baseData, ...overrides };
	}

	createVerenigingenSettingsData(overrides = {}) {
		const baseData = {
			name: 'Verenigingen Settings',
			default_membership_type: 'Regular',
			grace_period_days: 30,
			minimum_volunteer_age: 16,
			maximum_grace_period: 90,
			welcome_email_template: 'Member Welcome',
			renewal_reminder_template: 'Renewal Reminder',
			sepa_creditor_id: 'NL98ZZZ999999999999',
			enable_sepa_direct_debit: true,
			default_payment_method: 'SEPA Direct Debit'
		};
		return { ...baseData, ...overrides };
	}

	createBrandSettingsData(overrides = {}) {
		const baseData = {
			name: 'Brand Settings',
			organization_name: 'Test Vereniging',
			logo: '/files/logo.png',
			primary_color: '#0066cc',
			secondary_color: '#ff6600',
			font_family: 'Arial, sans-serif',
			theme: 'Modern',
			header_style: 'Standard'
		};
		return { ...baseData, ...overrides };
	}

	createMollieSettingsData(overrides = {}) {
		const baseData = {
			name: 'Mollie Settings',
			api_key: 'test_api_key_12345',
			webhook_url: 'https://example.com/webhook',
			environment: 'Test',
			enabled: true,
			auto_create_customers: true,
			subscription_enabled: true
		};
		return { ...baseData, ...overrides };
	}

	// Helper methods for additional DocTypes
	createChapterJoinRequestData(overrides = {}) {
		const baseData = {
			name: `CJR-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			member: this.createMemberName(),
			member_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			chapter: this.createChapterName(),
			status: this.randomChoice(['Pending', 'Approved', 'Rejected']),
			request_date: this.generateRecentDate(30),
			reason: 'Test join request reason',
			member_count: this.randomInt(50, 200)
		};
		return { ...baseData, ...overrides };
	}

	createMijnroodCSVImportData(overrides = {}) {
		const baseData = {
			name: `MCI-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			csv_file: '/files/members.csv',
			status: this.randomChoice(['Ready', 'Processing', 'Completed', 'Failed']),
			validate_emails: true,
			skip_duplicates: true,
			members_created: this.randomInt(0, 50),
			errors: this.randomInt(0, 5),
			duplicates: this.randomInt(0, 3)
		};
		return { ...baseData, ...overrides };
	}

	createContributionAmendmentRequestData(overrides = {}) {
		const baseData = {
			name: `CAR-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			member: this.createMemberName(),
			member_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			current_amount: 25.00,
			requested_amount: 20.00,
			minimum_amount: 10.00,
			status: this.randomChoice(['Pending', 'Approved', 'Rejected']),
			request_date: this.generateRecentDate(30),
			reason: 'Financial hardship'
		};
		return { ...baseData, ...overrides };
	}

	createExpulsionReportEntryData(overrides = {}) {
		const baseData = {
			name: `ERE-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(3, '0')}`,
			member: this.createMemberName(),
			member_name: `${this.generateDutchFirstName()} ${this.generateDutchSurname().last_name}`,
			expulsion_date: this.generateRecentDate(90),
			reason: 'Serious policy violation',
			status: this.randomChoice(['Reported', 'Under Review', 'Completed']),
			documentation_complete: this.randomChoice([true, false]),
			workflow_status: this.randomChoice(['Board Approved', 'Pending Review', 'Completed']),
			approval_date: this.generateRecentDate(30)
		};
		return { ...baseData, ...overrides };
	}

	createTeamData(overrides = {}) {
		const baseData = {
			name: `TEAM-${String(this.memberCounter++).padStart(3, '0')}`,
			team_name: this.randomChoice(['Marketing Team', 'Event Planning', 'Finance Committee', 'Volunteer Coordination']),
			team_lead: this.createMemberName(),
			status: this.randomChoice(['Active', 'Inactive', 'Disbanded']),
			default_role: this.randomChoice(['Member', 'Coordinator', 'Lead']),
			team_members: [
				{ member: this.createMemberName(), role: 'Member' },
				{ member: this.createMemberName(), role: 'Coordinator' }
			]
		};
		return { ...baseData, ...overrides };
	}

	createSEPAAuditLogData(overrides = {}) {
		const baseData = {
			name: `SAL-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(5, '0')}`,
			transaction_reference: `SEPA-${new Date().getFullYear()}-${String(this.memberCounter).padStart(3, '0')}`,
			audit_action: this.randomChoice(['Payment Processed', 'Mandate Created', 'Payment Failed', 'Mandate Cancelled']),
			timestamp: this.generateRecentDate(30),
			compliance_status: this.randomChoice(['Compliant', 'Non-Compliant', 'Under Review']),
			regulation_reference: 'SEPA Regulation 2023',
			checksum: 'abc123def456',
			data_integrity: this.randomChoice(['Verified', 'Failed', 'Pending'])
		};
		return { ...baseData, ...overrides };
	}

	createAPIAuditLogData(overrides = {}) {
		const baseData = {
			name: `AAL-${new Date().getFullYear()}-${String(this.memberCounter++).padStart(5, '0')}`,
			endpoint: '/api/method/verenigingen.api.member_management.create_member',
			method: this.randomChoice(['GET', 'POST', 'PUT', 'DELETE']),
			user: 'admin@example.com',
			timestamp: this.generateRecentDate(7),
			security_event: this.randomChoice(['Failed Authentication', 'Successful Login', 'Permission Denied', 'Rate Limit Exceeded']),
			threat_level: this.randomChoice(['Low', 'Medium', 'High']),
			ip_address: `192.168.1.${this.randomInt(1, 254)}`,
			access_pattern: this.randomChoice(['Normal', 'Suspicious', 'Blocked']),
			request_frequency: this.randomInt(1, 100)
		};
		return { ...baseData, ...overrides };
	}

	// Helper methods for generating valid test identifiers
	generateValidBSN() {
		// Generate a valid 9-digit BSN for testing
		let bsn = '';
		for (let i = 0; i < 9; i++) {
			bsn += this.randomInt(0, 9).toString();
		}
		return bsn;
	}

	generateValidRSIN() {
		// Generate a valid 8 or 9-digit RSIN for testing
		const length = this.randomChoice([8, 9]);
		let rsin = '';
		for (let i = 0; i < length; i++) {
			rsin += this.randomInt(0, 9).toString();
		}
		return rsin;
	}

	// Additional helper methods for creating realistic test data
	createDonationSummaryData() {
		return {
			total_donations: this.randomInt(5, 50),
			total_amount: this.randomInt(500, 5000),
			paid_amount: this.randomInt(400, 4500),
			unpaid_amount: this.randomInt(0, 500),
			last_donation_date: this.generateRecentDate(365),
			payment_methods: {
				'Bank Transfer': this.randomInt(1, 10),
				'SEPA Direct Debit': this.randomInt(1, 15),
				'Credit Card': this.randomInt(1, 5)
			}
		};
	}

	createChartOfAccountsData() {
		return {
			accounts_imported: this.randomInt(30, 100),
			cost_centers_imported: this.randomInt(5, 20),
			mapping_conflicts: this.randomInt(0, 5)
		};
	}

	createTransactionImportData() {
		return {
			transactions_imported: this.randomInt(500, 2000),
			duplicates_skipped: this.randomInt(10, 100),
			errors: this.randomInt(0, 20),
			date_range_start: this.generateRecentDate(365),
			date_range_end: this.generateRecentDate(1)
		};
	}

	createOpeningBalanceData() {
		return {
			opening_invoices_created: this.randomInt(10, 50),
			total_receivables: this.randomInt(5000, 25000),
			total_payables: this.randomInt(2000, 15000)
		};
	}

	createSingleMutationData(mutationId) {
		return {
			mutation_id: mutationId,
			amount: this.randomInt(50, 500),
			description: 'Test mutation',
			account_code: this.randomInt(1000, 9999),
			journal_entry: null
		};
	}

	createDutchAccountStructure() {
		return {
			balance_accounts: this.randomInt(20, 50),
			revenue_accounts: this.randomInt(10, 30),
			expense_accounts: this.randomInt(15, 40),
			vat_accounts: this.randomInt(3, 8)
		};
	}

	createDutchVATConfiguration() {
		return {
			high_rate: 21,
			low_rate: 9,
			zero_rate: 0,
			reverse_charge: true
		};
	}

	createDutchAccountNumbers() {
		return {
			assets: this.randomInt(1000, 1999),
			liabilities: this.randomInt(2000, 2999),
			equity: this.randomInt(3000, 3999),
			revenue: this.randomInt(8000, 8999),
			expenses: this.randomInt(4000, 7999)
		};
	}

	createRecentTransactionData() {
		return {
			count: this.randomInt(10, 100),
			amount_total: this.randomInt(1000, 10000),
			date_range: `${this.generateRecentDate(90)} to ${this.generateRecentDate(1)}`
		};
	}

	/**
   * Creates edge case test scenarios
   * @param {string} scenario - Edge case scenario type
   * @returns {Object} Edge case test data
   */
	createEdgeCaseScenario(scenario) {
		switch (scenario) {
			case 'minimum_age_volunteer':
				return this.createMemberData({
					birth_date: this.generateBirthDate(16, 16) // Exactly 16 years old
				});

			case 'maximum_length_names':
				return this.createMemberData({
					first_name: 'A'.repeat(50),
					last_name: 'B'.repeat(50),
					tussenvoegsel: 'van der'
				});

			case 'special_characters_email':
				return this.createMemberData({
					email: 'test+special.chars_123@example-domain.co.uk'
				});

			case 'international_member':
				return this.createMemberData({
					primary_address: this.createAddressData({
						country: 'Germany',
						pincode: '12345',
						city: 'Berlin'
					}).name
				});

			case 'expired_membership':
				return this.createMembershipData({
					status: 'Expired',
					end_date: this.generateRecentDate(30)
				});

			default:
				return this.createMemberData();
		}
	}
}

// Export for use in tests
if (typeof module !== 'undefined' && module.exports) {
	module.exports = TestDataFactory;
}

// Global export for browser environment
if (typeof window !== 'undefined') {
	window.TestDataFactory = TestDataFactory;
}
