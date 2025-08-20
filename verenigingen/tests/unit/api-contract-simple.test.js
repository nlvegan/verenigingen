/**
 * @fileoverview Simple API Contract Testing Examples
 * 
 * Demonstrates basic API contract validation without mock server complexity.
 * Tests parameter validation and schema matching for JavaScript-to-Python calls.
 * 
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { 
    SimpleAPIContractTester, 
    createSimpleAPIContractMatcher 
} = require('../setup/api-contract-simple');

require('../setup/frappe-mocks').setupTestMocks();

// Add custom Jest matcher
expect.extend(createSimpleAPIContractMatcher());

describe('Simple API Contract Testing', () => {
    let tester;
    
    beforeAll(() => {
        tester = new SimpleAPIContractTester();
    });

    describe('Parameter Validation', () => {
        it('should validate correct member API call', () => {
            const validArgs = {
                member: 'ASSOC-MEMBER-2025-001'
            };
            
            expect(validArgs).toMatchAPIContract(
                'verenigingen.verenigingen.doctype.member.member.process_payment'
            );
        });
        
        it('should reject invalid member format', () => {
            const invalidArgs = {
                member: 'invalid-format'
            };
            
            expect(() => {
                expect(invalidArgs).toMatchAPIContract(
                    'verenigingen.verenigingen.doctype.member.member.process_payment'
                );
            }).toThrow();
        });
        
        it('should reject missing required parameters', () => {
            const incompleteArgs = {
                // missing 'member' parameter
            };
            
            expect(() => {
                expect(incompleteArgs).toMatchAPIContract(
                    'verenigingen.verenigingen.doctype.member.member.process_payment'
                );
            }).toThrow();
        });
    });

    describe('IBAN Validation Contract', () => {
        it('should validate Dutch IBAN format correctly', () => {
            const validIbanCall = {
                iban: 'NL91ABNA0417164300'
            };
            
            expect(validIbanCall).toMatchAPIContract(
                'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
            );
        });
        
        it('should reject invalid IBAN format', () => {
            const invalidIbanCall = {
                iban: 'INVALID-IBAN-123'
            };
            
            expect(() => {
                expect(invalidIbanCall).toMatchAPIContract(
                    'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
                );
            }).toThrow();
        });
    });

    describe('Chapter Assignment Contract', () => {
        it('should validate chapter assignment with required fields', () => {
            const validAssignment = {
                member: 'ASSOC-MEMBER-2025-001',
                chapter: 'CH-Amsterdam',
                note: 'Member requested transfer'
            };
            
            expect(validAssignment).toMatchAPIContract(
                'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup'
            );
        });
        
        it('should allow optional note field to be omitted', () => {
            const minimalAssignment = {
                member: 'ASSOC-MEMBER-2025-001',
                chapter: 'CH-Amsterdam'
                // note is optional
            };
            
            expect(minimalAssignment).toMatchAPIContract(
                'verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup'
            );
        });
    });

    describe('Donation API Contract', () => {
        it('should validate donation with all required fields', () => {
            const validDonation = {
                donor_name: 'John Doe',
                email: 'john.doe@example.org',
                amount: 50.00,
                donation_type: 'one-time',
                anbi_consent: true
            };
            
            expect(validDonation).toMatchAPIContract(
                'verenigingen.templates.pages.donate.submit_donation'
            );
        });
        
        it('should reject invalid email format', () => {
            const invalidEmailDonation = {
                donor_name: 'Invalid Email',
                email: 'not-an-email',
                amount: 25.00
            };
            
            expect(() => {
                expect(invalidEmailDonation).toMatchAPIContract(
                    'verenigingen.templates.pages.donate.submit_donation'
                );
            }).toThrow();
        });
        
        it('should reject negative donation amounts', () => {
            const negativeDonation = {
                donor_name: 'Negative Amount',
                email: 'test@example.org',
                amount: -5.00
            };
            
            expect(() => {
                expect(negativeDonation).toMatchAPIContract(
                    'verenigingen.templates.pages.donate.submit_donation'
                );
            }).toThrow();
        });
    });

    describe('Test Data Generation', () => {
        it('should generate valid test data for member APIs', () => {
            const testData = tester.generateValidTestData(
                'verenigingen.verenigingen.doctype.member.member.process_payment'
            );
            
            expect(testData).toHaveProperty('member');
            expect(testData.member).toMatch(/^[A-Z]+-[A-Z]+-[0-9]+-[0-9]+$/);
        });
        
        it('should generate valid IBAN test data', () => {
            const testData = tester.generateValidTestData(
                'verenigingen.verenigingen.doctype.member.member.derive_bic_from_iban'
            );
            
            expect(testData).toHaveProperty('iban');
            expect(testData.iban).toMatch(/^[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{10}$/);
        });
        
        it('should generate valid donation test data', () => {
            const testData = tester.generateValidTestData(
                'verenigingen.templates.pages.donate.submit_donation'
            );
            
            expect(testData).toHaveProperty('donor_name');
            expect(testData).toHaveProperty('email');
            expect(testData).toHaveProperty('amount');
            expect(testData.email).toContain('@');
            expect(testData.amount).toBeGreaterThan(0);
        });
    });

    describe('Available Methods Validation', () => {
        it('should list all available API methods', () => {
            const methods = tester.getAvailableMethods();
            
            expect(methods).toContain('verenigingen.verenigingen.doctype.member.member.process_payment');
            expect(methods).toContain('verenigingen.verenigingen.doctype.chapter.chapter.assign_member_to_chapter_with_cleanup');
            expect(methods).toContain('verenigingen.templates.pages.donate.submit_donation');
            expect(methods.length).toBeGreaterThan(3);
        });
        
        it('should provide schema details for specific methods', () => {
            const schema = tester.getMethodSchema(
                'verenigingen.verenigingen.doctype.member.member.process_payment'
            );
            
            expect(schema).toHaveProperty('args');
            expect(schema).toHaveProperty('response');
            expect(schema.args.required).toContain('member');
        });
    });

    describe('Direct Validation Testing', () => {
        it('should validate API calls directly', () => {
            const result = tester.validateFrappeCall({
                method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
                args: { member: 'ASSOC-MEMBER-2025-001' }
            });
            
            expect(result.valid).toBe(true);
            expect(result.errors).toHaveLength(0);
        });
        
        it('should detect parameter name mismatches', () => {
            const result = tester.validateFrappeCall({
                method: 'verenigingen.verenigingen.doctype.member.member.process_payment',
                args: { member_id: 'ASSOC-MEMBER-2025-001' } // Wrong parameter name
            });
            
            expect(result.valid).toBe(false);
            expect(result.errors.length).toBeGreaterThan(0);
        });
        
        it('should detect data type mismatches', () => {
            const result = tester.validateFrappeCall({
                method: 'verenigingen.templates.pages.donate.submit_donation',
                args: { 
                    donor_name: 'Test',
                    email: 'test@example.org',
                    amount: '25.00' // Should be number, not string
                }
            });
            
            expect(result.valid).toBe(false);
            expect(result.errors.some(err => err.message.includes('number'))).toBe(true);
        });
    });
});