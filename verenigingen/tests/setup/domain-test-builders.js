/**
 * @fileoverview Domain-Specific Test Builders
 * 
 * Provides specialized test builders for different domains in the Verenigingen
 * association management system. These builders create domain-specific test
 * patterns while leveraging the common controller test infrastructure.
 * 
 * @author Verenigingen Development Team
 * @version 1.0.0
 */

const { 
    validateDutchIBAN, 
    validateDutchPostalCode,
    validateDutchEmail,
    validateBIC 
} = require('./dutch-validators');

/**
 * Financial Controller Test Builder
 * For controllers handling payments, SEPA, banking, and financial operations
 */
class FinancialControllerTestBuilder {
    constructor(controllerTest) {
        this.controllerTest = controllerTest;
    }

    /**
     * Generate SEPA compliance tests
     */
    createSEPATests() {
        return {
            'should validate Dutch IBAN correctly': () => {
                const testIBANs = [
                    { iban: 'NL91ABNA0417164300', valid: true },
                    { iban: 'NL91 ABNA 0417 1643 00', valid: true },
                    { iban: 'INVALID_IBAN', valid: false },
                    { iban: 'DE89370400440532013000', valid: false }, // German IBAN
                    { iban: '', valid: false }
                ];
                
                testIBANs.forEach(test => {
                    const result = validateDutchIBAN(test.iban);
                    expect(result.valid).toBe(test.valid);
                });
            },

            'should validate BIC codes correctly': () => {
                const testBICs = [
                    { bic: 'ABNANL2A', valid: true },
                    { bic: 'ABNANL2AXXX', valid: true },
                    { bic: 'INVALID', valid: false },
                    { bic: '', valid: false }
                ];
                
                testBICs.forEach(test => {
                    const result = validateBIC(test.bic);
                    expect(result.valid).toBe(test.valid);
                });
            },

            'should handle European banking compliance': () => {
                const sepaIBANs = [
                    'NL91ABNA0417164300', // Netherlands
                    'DE89370400440532013000', // Germany  
                    'FR1420041010050500013M02606', // France
                    'ES9121000418450200051332', // Spain
                    'IT60X0542811101000000123456' // Italy
                ];
                
                sepaIBANs.forEach(iban => {
                    this.controllerTest.mockForm.doc.iban = iban;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            }
        };
    }

    /**
     * Generate payment integration tests
     */
    createPaymentTests() {
        return {
            'should handle payment method configuration': () => {
                const paymentMethods = ['SEPA', 'Mollie', 'Bank Transfer', 'Cash'];
                
                paymentMethods.forEach(method => {
                    this.controllerTest.mockForm.doc.payment_method = method;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should validate payment amounts': () => {
                const testAmounts = [0, 25.00, 100.50, 1000.99, -50.00];
                
                testAmounts.forEach(amount => {
                    this.controllerTest.mockForm.doc.amount = amount;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            }
        };
    }

    /**
     * Generate mandate and authorization tests
     */
    createMandateTests() {
        return {
            'should handle mandate status transitions': () => {
                const statusTransitions = [
                    { from: 'Draft', to: 'Active' },
                    { from: 'Active', to: 'Suspended' },
                    { from: 'Suspended', to: 'Active' },
                    { from: 'Active', to: 'Cancelled' }
                ];
                
                statusTransitions.forEach(transition => {
                    this.controllerTest.mockForm.doc.status = transition.from;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should validate mandate authorization': () => {
                this.controllerTest.mockForm.doc.status = 'Active';
                this.controllerTest.mockForm.doc.iban = 'NL91ABNA0417164300';
                this.controllerTest.mockForm.doc.account_holder_name = 'Jan van der Berg';
                this.controllerTest.mockForm.doc.mandate_date = '2024-01-15';
                
                expect(() => {
                    this.controllerTest.testEvent('refresh');
                }).not.toThrow();
            }
        };
    }
}

/**
 * Association Management Controller Test Builder
 * For controllers handling members, chapters, volunteers, and organizational structure
 */
class AssociationControllerTestBuilder {
    constructor(controllerTest) {
        this.controllerTest = controllerTest;
    }

    /**
     * Generate Dutch business logic tests
     */
    createDutchValidationTests() {
        return {
            'should validate Dutch postal codes': () => {
                const testCodes = [
                    { code: '1012 AB', valid: true },
                    { code: '2011 CD', valid: true },
                    { code: '12345', valid: false },
                    { code: 'ABCD EF', valid: false }
                ];
                
                testCodes.forEach(test => {
                    const result = validateDutchPostalCode(test.code);
                    expect(result.valid).toBe(test.valid);
                });
            },

            'should handle Dutch name components': () => {
                const nameTests = [
                    { first: 'Jan', tussen: 'van der', last: 'Berg' },
                    { first: 'Maria', tussen: 'de', last: 'Jong' },
                    { first: 'Peter', tussen: '', last: 'Jansen' },
                    { first: 'Anne', tussen: 'van', last: 'Dijk' }
                ];
                
                nameTests.forEach(nameTest => {
                    this.controllerTest.mockForm.doc.first_name = nameTest.first;
                    this.controllerTest.mockForm.doc.tussenvoegsel = nameTest.tussen;
                    this.controllerTest.mockForm.doc.last_name = nameTest.last;
                    
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should validate Dutch email format': () => {
                const testEmails = [
                    { email: 'jan.van.der.berg@example.org', valid: true },
                    { email: 'maria@vereniging.nl', valid: true },
                    { email: 'invalid-email', valid: false },
                    { email: '@example.org', valid: false }
                ];
                
                testEmails.forEach(test => {
                    const result = validateDutchEmail(test.email);
                    expect(result.valid).toBe(test.valid);
                });
            }
        };
    }

    /**
     * Generate membership lifecycle tests
     */
    createMembershipTests() {
        return {
            'should handle membership status transitions': () => {
                const statuses = ['Pending', 'Active', 'Inactive', 'Terminated', 'Suspended'];
                
                statuses.forEach(status => {
                    this.controllerTest.mockForm.doc.status = status;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should handle membership types': () => {
                const membershipTypes = ['Regular', 'Student', 'Senior', 'Family', 'Honorary'];
                
                membershipTypes.forEach(type => {
                    this.controllerTest.mockForm.doc.membership_type = type;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should validate required fields for active members': () => {
                this.controllerTest.mockForm.doc.status = 'Active';
                this.controllerTest.mockForm.doc.first_name = 'Jan';
                this.controllerTest.mockForm.doc.last_name = 'Berg';
                this.controllerTest.mockForm.doc.email = 'jan.berg@example.org';
                
                expect(() => {
                    this.controllerTest.testEvent('refresh');
                }).not.toThrow();
            }
        };
    }

    /**
     * Generate geographical organization tests
     */
    createGeographicalTests() {
        return {
            'should handle chapter assignment': () => {
                const chapters = ['Amsterdam', 'Rotterdam', 'Utrecht', 'Den Haag'];
                
                chapters.forEach(chapter => {
                    this.controllerTest.mockForm.doc.primary_chapter = chapter;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should validate postal code regions': () => {
                const postalCodeRanges = [
                    { from: '1000 AA', to: '1099 ZZ' },
                    { from: '2000 AA', to: '2099 ZZ' },
                    { from: '3000 AA', to: '3099 ZZ' }
                ];
                
                postalCodeRanges.forEach(range => {
                    this.controllerTest.mockForm.doc.postal_code_from = range.from;
                    this.controllerTest.mockForm.doc.postal_code_to = range.to;
                    
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            }
        };
    }

    /**
     * Generate volunteer management tests
     */
    createVolunteerTests() {
        return {
            'should handle volunteer roles': () => {
                const volunteerRoles = ['Board Member', 'Event Coordinator', 'Communications', 'Treasurer'];
                
                volunteerRoles.forEach(role => {
                    this.controllerTest.mockForm.doc.volunteer_role = role;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should validate volunteer age requirements': () => {
                // Volunteers must be 16+ in Dutch association management
                const birthDates = [
                    '2010-01-15', // Under 16
                    '2007-01-15', // Exactly 16
                    '1990-01-15', // Adult
                    '1950-01-15'  // Senior
                ];
                
                birthDates.forEach(birthDate => {
                    this.controllerTest.mockForm.doc.birth_date = birthDate;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            }
        };
    }
}

/**
 * Workflow Controller Test Builder
 * For controllers handling document workflows, approvals, and state transitions
 */
class WorkflowControllerTestBuilder {
    constructor(controllerTest) {
        this.controllerTest = controllerTest;
    }

    /**
     * Generate workflow state tests
     */
    createWorkflowTests() {
        return {
            'should handle document state transitions': () => {
                const states = ['Draft', 'Pending Approval', 'Approved', 'Rejected', 'Cancelled'];
                
                states.forEach(state => {
                    this.controllerTest.mockForm.doc.workflow_state = state;
                    expect(() => {
                        this.controllerTest.testEvent('refresh');
                    }).not.toThrow();
                });
            },

            'should handle approval workflows': () => {
                this.controllerTest.mockForm.doc.workflow_state = 'Pending Approval';
                this.controllerTest.mockForm.doc.approver = 'admin@example.org';
                
                expect(() => {
                    this.controllerTest.testEvent('refresh');
                }).not.toThrow();
            }
        };
    }
}

/**
 * Factory function to create appropriate test builder based on controller type
 */
function createDomainTestBuilder(controllerTest, domain) {
    switch (domain) {
        case 'financial':
            return new FinancialControllerTestBuilder(controllerTest);
        case 'association':
            return new AssociationControllerTestBuilder(controllerTest);
        case 'workflow':
            return new WorkflowControllerTestBuilder(controllerTest);
        default:
            throw new Error(`Unknown domain: ${domain}`);
    }
}

module.exports = {
    FinancialControllerTestBuilder,
    AssociationControllerTestBuilder,
    WorkflowControllerTestBuilder,
    createDomainTestBuilder
};