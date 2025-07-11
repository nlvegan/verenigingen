/**
 * IBAN Lifecycle Tests
 *
 * Tests for IBAN validation, history tracking, and mandate management
 * throughout the member lifecycle
 */

describe('IBAN Lifecycle Management', () => {
	let mockFrappe;

	beforeEach(() => {
		mockFrappe = {
			call: jest.fn(),
			db: {
				get_list: jest.fn(),
				get_value: jest.fn()
			},
			show_alert: jest.fn(),
			msgprint: jest.fn(),
			datetime: {
				nowdate: () => '2025-01-05',
				now_datetime: () => '2025-01-05 10:00:00'
			}
		};
		global.frappe = mockFrappe;
		global.__ = (str) => str;
	});

	describe('IBAN Validation', () => {
		const validateIBAN = (iban) => {
			if (!iban) return { valid: false, error: 'IBAN is required' };

			// Remove spaces and convert to uppercase
			const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

			// Basic format check
			if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(cleanIBAN)) {
				return { valid: false, error: 'Invalid IBAN format' };
			}

			// Length check by country
			const ibanLengths = {
				'NL': 18, // Netherlands
				'BE': 16, // Belgium
				'DE': 22, // Germany
				'FR': 27, // France
				'ES': 24, // Spain
				'IT': 27  // Italy
			};

			const countryCode = cleanIBAN.substring(0, 2);
			const expectedLength = ibanLengths[countryCode];

			if (expectedLength && cleanIBAN.length !== expectedLength) {
				return { valid: false, error: `IBAN for ${countryCode} should be ${expectedLength} characters` };
			}

			// Mod-97 validation
			const rearranged = cleanIBAN.substring(4) + cleanIBAN.substring(0, 4);
			const numeric = rearranged.replace(/[A-Z]/g, char => char.charCodeAt(0) - 55);
			const remainder = numeric.match(/.{1,9}/g).reduce((acc, chunk) => {
				return (parseInt(acc + chunk) % 97).toString();
			}, '');

			if (remainder !== '1') {
				return { valid: false, error: 'Invalid IBAN checksum' };
			}

			return { valid: true, formatted: formatIBAN(cleanIBAN) };
		};

		const formatIBAN = (iban) => {
			// Format IBAN with spaces every 4 characters
			return iban.match(/.{1,4}/g).join(' ');
		};

		it('should validate Dutch IBANs correctly', () => {
			const validDutchIBAN = 'NL91ABNA0417164300';
			const result = validateIBAN(validDutchIBAN);
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('NL91 ABNA 0417 1643 00');
		});

		it('should reject invalid IBAN formats', () => {
			expect(validateIBAN('').valid).toBe(false);
			expect(validateIBAN('123456789').valid).toBe(false);
			expect(validateIBAN('NL12').valid).toBe(false);
			expect(validateIBAN('XX91ABNA0417164300').valid).toBe(false);
		});

		it('should validate IBANs from different countries', () => {
			const testCases = [
				{ iban: 'BE68539007547034', country: 'Belgium' },
				{ iban: 'DE89370400440532013000', country: 'Germany' },
				{ iban: 'FR1420041010050500013M02606', country: 'France' }
			];

			testCases.forEach(({ iban, country }) => {
				const result = validateIBAN(iban);
				expect(result.valid).toBe(true);
			});
		});

		it('should handle IBANs with spaces', () => {
			const ibanWithSpaces = 'NL91 ABNA 0417 1643 00';
			const result = validateIBAN(ibanWithSpaces);
			expect(result.valid).toBe(true);
			expect(result.formatted).toBe('NL91 ABNA 0417 1643 00');
		});
	});

	describe('BIC Derivation', () => {
		const deriveBICFromIBAN = (iban) => {
			const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();

			// Dutch bank BIC mapping
			const dutchBankCodes = {
				'ABNA': 'ABNANL2A', // ABN AMRO
				'RABO': 'RABONL2U', // Rabobank
				'INGB': 'INGBNL2A', // ING
				'TRIO': 'TRIONL2U', // Triodos
				'ASNB': 'ASNBNL21', // ASN Bank
				'BUNQ': 'BUNQNL2A', // Bunq
				'KNAB': 'KNABNL2H', // Knab
				'SNSB': 'SNSBNL2A', // SNS Bank
				'RBRB': 'RBRBNL21', // RegioBank
			};

			if (cleanIBAN.startsWith('NL')) {
				const bankCode = cleanIBAN.substring(4, 8);
				return dutchBankCodes[bankCode] || null;
			}

			// For non-Dutch IBANs, return null (would need manual entry)
			return null;
		};

		it('should derive BIC for major Dutch banks', () => {
			expect(deriveBICFromIBAN('NL91ABNA0417164300')).toBe('ABNANL2A');
			expect(deriveBICFromIBAN('NL44RABO0123456789')).toBe('RABONL2U');
			expect(deriveBICFromIBAN('NL18INGB0123456789')).toBe('INGBNL2A');
		});

		it('should return null for unknown banks', () => {
			expect(deriveBICFromIBAN('NL91XXXX0417164300')).toBe(null);
			expect(deriveBICFromIBAN('BE68539007547034')).toBe(null);
		});
	});

	describe('IBAN History Tracking', () => {
		const IBANHistoryTracker = {
			history: [],

			addEntry(memberName, oldIBAN, newIBAN, reason) {
				const entry = {
					member: memberName,
					old_iban: oldIBAN,
					new_iban: newIBAN,
					change_date: frappe.datetime.now_datetime(),
					change_reason: reason,
					changed_by: frappe.session?.user || 'System',
					mandates_updated: false
				};

				this.history.push(entry);
				return entry;
			},

			getMemberHistory(memberName) {
				return this.history.filter(entry => entry.member === memberName);
			},

			getLatestIBAN(memberName) {
				const memberHistory = this.getMemberHistory(memberName);
				if (memberHistory.length === 0) return null;
				return memberHistory[memberHistory.length - 1].new_iban;
			}
		};

		it('should track IBAN changes', () => {
			IBANHistoryTracker.addEntry(
				'MEM-001',
				'NL91ABNA0417164300',
				'NL44RABO0123456789',
				'Bank change requested by member'
			);

			const history = IBANHistoryTracker.getMemberHistory('MEM-001');
			expect(history).toHaveLength(1);
			expect(history[0].old_iban).toBe('NL91ABNA0417164300');
			expect(history[0].new_iban).toBe('NL44RABO0123456789');
		});

		it('should retrieve latest IBAN', () => {
			IBANHistoryTracker.addEntry('MEM-002', null, 'NL91ABNA0417164300', 'Initial IBAN');
			IBANHistoryTracker.addEntry('MEM-002', 'NL91ABNA0417164300', 'NL44RABO0123456789', 'Changed bank');

			expect(IBANHistoryTracker.getLatestIBAN('MEM-002')).toBe('NL44RABO0123456789');
		});

		it('should handle validation during IBAN change', () => {
			// Define validateIBAN within the test scope
			const validateIBAN = (iban) => {
				if (!iban) return { valid: false, error: 'IBAN is required' };
				const cleanIBAN = iban.replace(/\s/g, '').toUpperCase();
				if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]+$/.test(cleanIBAN)) {
					return { valid: false, error: 'Invalid IBAN format' };
				}
				return { valid: true, formatted: cleanIBAN.match(/.{1,4}/g).join(' ') };
			};

			const changeIBAN = (member, newIBAN, reason) => {
				// Validate new IBAN
				const validation = validateIBAN(newIBAN);
				if (!validation.valid) {
					return { success: false, error: validation.error };
				}

				// Check if IBAN actually changed
				if (member.iban === validation.formatted) {
					return { success: false, error: 'IBAN unchanged' };
				}

				// Record history
				const historyEntry = IBANHistoryTracker.addEntry(
					member.name,
					member.iban,
					validation.formatted,
					reason
				);

				// Update member
				member.iban = validation.formatted;

				return { success: true, history: historyEntry };
			};

			const member = { name: 'MEM-003', iban: 'NL91ABNA0417164300' };
			const result = changeIBAN(member, 'NL44RABO0123456789', 'Bank change');

			expect(result.success).toBe(true);
			expect(member.iban).toBe('NL44 RABO 0123 4567 89');
		});
	});

	describe('SEPA Mandate Lifecycle', () => {
		const SEPAMandateManager = {
			mandates: [],

			createMandate(memberName, iban, bic) {
				const mandate = {
					name: `SEPA-${Date.now()}`,
					member: memberName,
					mandate_id: this.generateMandateId(memberName),
					iban: iban,
					bic: bic,
					status: 'Active',
					signature_date: frappe.datetime.nowdate(),
					first_collection_date: null,
					last_collection_date: null,
					collection_count: 0
				};

				this.mandates.push(mandate);
				return mandate;
			},

			generateMandateId(memberName) {
				const date = new Date();
				const dateStr = date.toISOString().slice(0, 10).replace(/-/g, '');
				const random = Math.floor(Math.random() * 1000).toString().padStart(3, '0');
				return `M-${memberName}-${dateStr}-${random}`;
			},

			getActiveMandate(memberName) {
				return this.mandates.find(m => m.member === memberName && m.status === 'Active');
			},

			cancelMandate(mandateId, reason) {
				const mandate = this.mandates.find(m => m.mandate_id === mandateId);
				if (mandate) {
					mandate.status = 'Cancelled';
					mandate.cancellation_date = frappe.datetime.nowdate();
					mandate.cancellation_reason = reason;
					return true;
				}
				return false;
			},

			updateMandateForIBANChange(memberName, oldIBAN, newIBAN, newBIC) {
				// Cancel old mandate
				const oldMandate = this.mandates.find(
					m => m.member === memberName && m.iban === oldIBAN && m.status === 'Active'
				);

				if (oldMandate) {
					this.cancelMandate(oldMandate.mandate_id, 'IBAN changed');
				}

				// Create new mandate
				return this.createMandate(memberName, newIBAN, newBIC);
			}
		};

		it('should create SEPA mandate with unique ID', () => {
			const mandate = SEPAMandateManager.createMandate(
				'MEM-001',
				'NL91ABNA0417164300',
				'ABNANL2A'
			);

			expect(mandate.mandate_id).toMatch(/^M-MEM-001-\d{8}-\d{3}$/);
			expect(mandate.status).toBe('Active');
			expect(mandate.signature_date).toBe('2025-01-05');
		});

		it('should handle mandate cancellation', () => {
			const mandate = SEPAMandateManager.createMandate(
				'MEM-002',
				'NL91ABNA0417164300',
				'ABNANL2A'
			);

			const cancelled = SEPAMandateManager.cancelMandate(mandate.mandate_id, 'Member request');
			expect(cancelled).toBe(true);

			const updatedMandate = SEPAMandateManager.mandates.find(m => m.mandate_id === mandate.mandate_id);
			expect(updatedMandate.status).toBe('Cancelled');
			expect(updatedMandate.cancellation_reason).toBe('Member request');
		});

		it('should update mandate when IBAN changes', () => {
			// Create initial mandate
			const oldMandate = SEPAMandateManager.createMandate(
				'MEM-003',
				'NL91ABNA0417164300',
				'ABNANL2A'
			);

			// Change IBAN
			const newMandate = SEPAMandateManager.updateMandateForIBANChange(
				'MEM-003',
				'NL91ABNA0417164300',
				'NL44RABO0123456789',
				'RABONL2U'
			);

			// Verify old mandate cancelled
			const oldMandateStatus = SEPAMandateManager.mandates.find(
				m => m.mandate_id === oldMandate.mandate_id
			).status;
			expect(oldMandateStatus).toBe('Cancelled');

			// Verify new mandate created
			expect(newMandate.iban).toBe('NL44RABO0123456789');
			expect(newMandate.status).toBe('Active');
		});

		it('should track mandate usage', () => {
			const trackMandateUsage = (mandateId, amount) => {
				const mandate = SEPAMandateManager.mandates.find(m => m.mandate_id === mandateId);
				if (!mandate || mandate.status !== 'Active') {
					return { success: false, error: 'Invalid or inactive mandate' };
				}

				mandate.collection_count += 1;
				mandate.last_collection_date = frappe.datetime.nowdate();
				mandate.last_collection_amount = amount;

				if (!mandate.first_collection_date) {
					mandate.first_collection_date = frappe.datetime.nowdate();
				}

				return { success: true, collection_count: mandate.collection_count };
			};

			const mandate = SEPAMandateManager.createMandate('MEM-004', 'NL91ABNA0417164300', 'ABNANL2A');

			const result1 = trackMandateUsage(mandate.mandate_id, 50.00);
			expect(result1.success).toBe(true);
			expect(result1.collection_count).toBe(1);

			const result2 = trackMandateUsage(mandate.mandate_id, 50.00);
			expect(result2.collection_count).toBe(2);

			const updatedMandate = SEPAMandateManager.getActiveMandate('MEM-004');
			expect(updatedMandate.first_collection_date).toBe('2025-01-05');
			expect(updatedMandate.last_collection_amount).toBe(50.00);
		});
	});

	describe('Payment Method Transitions', () => {
		// Define SEPAMandateManager for this test suite
		const SEPAMandateManager = {
			mandates: [],

			createMandate(memberName, iban, bic) {
				const mandate = {
					name: `SEPA-${Date.now()}`,
					member: memberName,
					mandate_id: `M-${memberName}-${Date.now()}`,
					iban: iban,
					bic: bic,
					status: 'Active'
				};
				this.mandates.push(mandate);
				return mandate;
			},

			getActiveMandate(memberName) {
				return this.mandates.find(m => m.member === memberName && m.status === 'Active');
			}
		};

		it('should handle transition from bank transfer to direct debit', async () => {
			const transitionToDirectDebit = async (member) => {
				// Validate prerequisites
				if (!member.iban) {
					return { success: false, error: 'IBAN required for Direct Debit' };
				}

				// Check for active mandate
				const activeMandate = SEPAMandateManager.getActiveMandate(member.name);
				if (!activeMandate) {
					return { success: false, error: 'Active SEPA mandate required' };
				}

				// Update payment method
				const oldMethod = member.payment_method;
				member.payment_method = 'Direct Debit';

				// Log transition
				const transition = {
					member: member.name,
					from_method: oldMethod,
					to_method: 'Direct Debit',
					mandate_id: activeMandate.mandate_id,
					transition_date: frappe.datetime.now_datetime()
				};

				return { success: true, transition };
			};

			const member = {
				name: 'MEM-005',
				payment_method: 'Bank Transfer',
				iban: 'NL91ABNA0417164300'
			};

			// Create mandate first
			SEPAMandateManager.createMandate(member.name, member.iban, 'ABNANL2A');

			const result = await transitionToDirectDebit(member);
			expect(result.success).toBe(true);
			expect(result.transition.from_method).toBe('Bank Transfer');
			expect(result.transition.to_method).toBe('Direct Debit');
			expect(member.payment_method).toBe('Direct Debit');
		});

		it('should validate IBAN requirements for payment methods', () => {
			const validatePaymentMethodRequirements = (member, newMethod) => {
				const requirements = {
					'Direct Debit': ['iban', 'active_mandate'],
					'Bank Transfer': [],
					'Credit Card': ['card_token']
				};

				const required = requirements[newMethod] || [];
				const missing = [];

				if (required.includes('iban') && !member.iban) {
					missing.push('Valid IBAN');
				}

				if (required.includes('active_mandate')) {
					const mandate = SEPAMandateManager.getActiveMandate(member.name);
					if (!mandate) {
						missing.push('Active SEPA mandate');
					}
				}

				if (required.includes('card_token') && !member.card_token) {
					missing.push('Credit card information');
				}

				return {
					canSwitch: missing.length === 0,
					missingRequirements: missing
				};
			};

			const member = { name: 'MEM-006' };

			const result = validatePaymentMethodRequirements(member, 'Direct Debit');
			expect(result.canSwitch).toBe(false);
			expect(result.missingRequirements).toContain('Valid IBAN');
			expect(result.missingRequirements).toContain('Active SEPA mandate');
		});
	});
});
