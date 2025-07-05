// verenigingen/verenigingen/doctype/chapter/utils/ChapterValidation.js

import { ChapterConfig } from '../config/ChapterConfig.js';

export class ChapterValidation {
    /**
     * Validate board members data
     * @param {Array} boardMembers - Array of board member objects
     * @returns {Object} Validation result with isValid flag and errors array
     */
    static async validateBoardMembers(boardMembers) {
        const errors = [];
        const uniqueRoles = await this.getUniqueRoles();
        const activeUniqueRoles = new Map();

        if (!boardMembers || boardMembers.length === 0) {
            return { isValid: true, errors: [] };
        }

        // Check minimum board size
        const activeMembers = boardMembers.filter(m => m.is_active);
        if (activeMembers.length < ChapterConfig.board.minimumSize) {
            errors.push(__('Board must have at least {0} active members', [ChapterConfig.board.minimumSize]));
        }

        // Check maximum board size
        if (activeMembers.length > ChapterConfig.board.maximumSize) {
            errors.push(__('Board cannot exceed {0} active members', [ChapterConfig.board.maximumSize]));
        }

        // Check required roles
        const requiredRoles = ChapterConfig.board.requiredRoles;
        const assignedRoles = activeMembers.map(m => m.chapter_role);

        requiredRoles.forEach(role => {
            if (!assignedRoles.includes(role)) {
                errors.push(__('Required role "{0}" is not assigned to any active board member', [role]));
            }
        });

        // Validate each board member
        for (const member of boardMembers) {
            const memberErrors = this.validateBoardMember(member);
            if (memberErrors.length > 0) {
                errors.push(...memberErrors);
            }

            // Check unique role assignments
            if (member.is_active && member.chapter_role && uniqueRoles.includes(member.chapter_role)) {
                if (activeUniqueRoles.has(member.chapter_role)) {
                    errors.push(__('Unique role "{0}" is assigned to multiple active board members', [member.chapter_role]));
                }
                activeUniqueRoles.set(member.chapter_role, member.volunteer);
            }
        }

        return {
            isValid: errors.length === 0,
            errors: errors
        };
    }

    /**
     * Validate individual board member
     * @param {Object} member - Board member object
     * @returns {Array} Array of error messages
     */
    static validateBoardMember(member) {
        const errors = [];

        // Required fields
        if (!member.volunteer) {
            errors.push(__('Volunteer is required for board member'));
        }

        if (!member.chapter_role) {
            errors.push(__('Board role is required'));
        }

        if (!member.from_date) {
            errors.push(__('Start date is required for board member {0}', [member.volunteer_name || member.volunteer]));
        }

        // Date validation
        if (member.from_date && member.to_date) {
            const fromDate = frappe.datetime.str_to_obj(member.from_date);
            const toDate = frappe.datetime.str_to_obj(member.to_date);

            if (fromDate > toDate) {
                errors.push(__('Start date cannot be after end date for {0}', [member.volunteer_name || member.volunteer]));
            }
        }

        // Check if board member is active but has end date in the past
        if (member.is_active && member.to_date) {
            const toDate = frappe.datetime.str_to_obj(member.to_date);
            const today = frappe.datetime.str_to_obj(frappe.datetime.nowdate());

            if (toDate < today) {
                errors.push(__('Active board member {0} has end date in the past', [member.volunteer_name || member.volunteer]));
            }
        }

        // Check tenure
        if (member.from_date) {
            const tenure = this.calculateTenure(member.from_date, member.to_date);
            if (tenure > ChapterConfig.board.maxTenureYears * 365) {
                errors.push(__('Board member {0} tenure exceeds maximum of {1} years',
                    [member.volunteer_name || member.volunteer, ChapterConfig.board.maxTenureYears]));
            }
        }

        return errors;
    }

    /**
     * Validate postal code patterns
     * @param {String} postalCodes - Comma-separated postal code patterns
     * @returns {Object} Validation result with isValid flag and invalid patterns
     */
    static validatePostalCodes(postalCodes) {
        if (!postalCodes) {
            return { isValid: true, validPatterns: [], invalidPatterns: [] };
        }

        const patterns = postalCodes.split(',').map(p => p.trim());
        const validPatterns = [];
        const invalidPatterns = [];

        const maxPatterns = ChapterConfig.postalCodes.maxPatterns;
        if (patterns.length > maxPatterns) {
            return {
                isValid: false,
                validPatterns: [],
                invalidPatterns: patterns,
                error: __('Maximum {0} postal code patterns allowed', [maxPatterns])
            };
        }

        patterns.forEach(pattern => {
            if (this.isValidPostalCodePattern(pattern)) {
                validPatterns.push(pattern);
            } else {
                invalidPatterns.push(pattern);
            }
        });

        return {
            isValid: invalidPatterns.length === 0,
            validPatterns,
            invalidPatterns
        };
    }

    /**
     * Check if a postal code pattern is valid
     * @param {String} pattern - Postal code pattern
     * @returns {Boolean} Whether pattern is valid
     */
    static isValidPostalCodePattern(pattern) {
        if (!pattern) return false;

        // Check for range pattern (e.g. 1000-1099)
        if (pattern.includes('-')) {
            const parts = pattern.split('-');
            if (parts.length !== 2) return false;

            const [start, end] = parts;
            if (!this.isValidPostalCode(start) || !this.isValidPostalCode(end)) {
                return false;
            }

            // Check if range is valid (start <= end)
            if (start.match(/^\d+$/) && end.match(/^\d+$/)) {
                return parseInt(start) <= parseInt(end);
            }

            return true;
        }

        // Check for wildcard pattern (e.g. 10*)
        if (pattern.includes('*')) {
            const base = pattern.replace('*', '');
            // Base should be numeric or alphanumeric depending on country
            return base.match(/^[a-zA-Z0-9]+$/);
        }

        // Simple postal code
        return this.isValidPostalCode(pattern);
    }

    /**
     * Check if a postal code is valid
     * @param {String} postalCode - Postal code
     * @returns {Boolean} Whether postal code is valid
     */
    static isValidPostalCode(postalCode) {
        if (!postalCode) return false;

        const country = ChapterConfig.postalCodes.defaultCountry;
        const pattern = ChapterConfig.postalCodes.validationRules[country];

        if (pattern) {
            return pattern.test(postalCode);
        }

        // Default validation - alphanumeric
        return /^[a-zA-Z0-9]+$/.test(postalCode);
    }

    /**
     * Validate chapter basic information
     * @param {Object} chapter - Chapter document
     * @returns {Object} Validation result
     */
    static validateChapterInfo(chapter) {
        const errors = [];

        // Required fields
        if (!chapter.name) {
            errors.push(__('Chapter name is required'));
        } else if (!ChapterConfig.validation.namePattern.test(chapter.name)) {
            errors.push(__('Chapter name contains invalid characters'));
        }

        if (!chapter.region) {
            errors.push(__('Region is required'));
        }

        if (!chapter.introduction) {
            errors.push(__('Introduction is required'));
        }

        // Field length validation
        const maxLengths = ChapterConfig.validation.maxFieldLengths;

        if (chapter.introduction && chapter.introduction.length > maxLengths.description) {
            errors.push(__('Introduction exceeds maximum length of {0} characters', [maxLengths.description]));
        }

        if (chapter.address && chapter.address.length > maxLengths.address) {
            errors.push(__('Address exceeds maximum length of {0} characters', [maxLengths.address]));
        }

        return {
            isValid: errors.length === 0,
            errors
        };
    }

    /**
     * Validate email addresses
     * @param {String|Array} emails - Email address(es) to validate
     * @returns {Object} Validation result
     */
    static validateEmails(emails) {
        const emailArray = Array.isArray(emails) ? emails : emails.split(',').map(e => e.trim());
        const validEmails = [];
        const invalidEmails = [];

        emailArray.forEach(email => {
            if (ChapterConfig.validation.emailPattern.test(email)) {
                validEmails.push(email);
            } else {
                invalidEmails.push(email);
            }
        });

        return {
            isValid: invalidEmails.length === 0,
            validEmails,
            invalidEmails
        };
    }

    /**
     * Validate phone number
     * @param {String} phone - Phone number
     * @returns {Boolean} Whether phone number is valid
     */
    static validatePhone(phone) {
        if (!phone) return true; // Phone is optional
        return ChapterConfig.validation.phonePattern.test(phone);
    }

    /**
     * Validate URL
     * @param {String} url - URL to validate
     * @returns {Boolean} Whether URL is valid
     */
    static validateURL(url) {
        if (!url) return true; // URL is optional
        return ChapterConfig.validation.urlPattern.test(url);
    }

    /**
     * Validate member data
     * @param {Object} member - Member object
     * @returns {Object} Validation result
     */
    static validateMember(member) {
        const errors = [];

        if (!member.member) {
            errors.push(__('Member ID is required'));
        }

        if (!member.member_name) {
            errors.push(__('Member name is required'));
        }

        if (member.introduction && member.introduction.length > ChapterConfig.members.maxIntroductionLength) {
            errors.push(__('Introduction exceeds maximum length of {0} characters',
                [ChapterConfig.members.maxIntroductionLength]));
        }

        if (member.website_url && !this.validateURL(member.website_url)) {
            errors.push(__('Invalid website URL for member {0}', [member.member_name]));
        }

        return {
            isValid: errors.length === 0,
            errors
        };
    }

    /**
     * Validate communication data
     * @param {Object} data - Communication data
     * @returns {Object} Validation result
     */
    static validateCommunication(data) {
        const errors = [];

        if (!data.subject) {
            errors.push(__('Subject is required'));
        }

        if (!data.message) {
            errors.push(__('Message is required'));
        }

        if (data.recipients) {
            const emailValidation = this.validateEmails(data.recipients);
            if (!emailValidation.isValid) {
                errors.push(__('Invalid email addresses: {0}', [emailValidation.invalidEmails.join(', ')]));
            }
        } else {
            errors.push(__('At least one recipient is required'));
        }

        // Check attachment size
        if (data.attachments) {
            const maxSize = ChapterConfig.communication.maxAttachmentSize;
            // This would need actual file size checking
            // For now, just placeholder
        }

        return {
            isValid: errors.length === 0,
            errors
        };
    }

    /**
     * Calculate tenure in days
     * @param {String} fromDate - Start date
     * @param {String} toDate - End date (optional)
     * @returns {Number} Tenure in days
     */
    static calculateTenure(fromDate, toDate) {
        const start = frappe.datetime.str_to_obj(fromDate);
        const end = toDate ? frappe.datetime.str_to_obj(toDate) : new Date();

        return Math.floor((end - start) / (1000 * 60 * 60 * 24));
    }

    /**
     * Get list of unique roles from database
     * @returns {Array} Array of unique role names
     */
    static async getUniqueRoles() {
        try {
            const roles = await frappe.db.get_list('Chapter Role', {
                filters: { is_unique: 1, is_active: 1 },
                fields: ['name']
            });

            return roles.map(r => r.name);
        } catch (error) {
            console.error('Error fetching unique roles:', error);
            return [];
        }
    }

    /**
     * Check if user has permission for an action
     * @param {String} action - Action name
     * @param {Array} userRoles - User's roles
     * @returns {Boolean} Whether user has permission
     */
    static hasPermission(action, userRoles = null) {
        const roles = userRoles || frappe.user_roles;
        const requiredRoles = ChapterConfig.validation.requiredPermissions[action] || [];

        return requiredRoles.some(role => roles.includes(role));
    }

    /**
     * Validate bulk operation data
     * @param {Array} items - Items for bulk operation
     * @param {String} operation - Operation type
     * @returns {Object} Validation result
     */
    static validateBulkOperation(items, operation) {
        const errors = [];

        if (!items || items.length === 0) {
            errors.push(__('No items selected for bulk operation'));
        }

        if (items.length > ChapterConfig.board.bulkOperationLimit) {
            errors.push(__('Bulk operation limited to {0} items at a time',
                [ChapterConfig.board.bulkOperationLimit]));
        }

        // Validate each item based on operation
        items.forEach((item, index) => {
            if (!item.volunteer) {
                errors.push(__('Item {0} is missing volunteer information', [index + 1]));
            }

            if (operation === 'remove' || operation === 'deactivate') {
                if (!item.end_date) {
                    errors.push(__('End date is required for item {0}', [index + 1]));
                }
            }
        });

        return {
            isValid: errors.length === 0,
            errors
        };
    }

    /**
     * Validate date range
     * @param {String} startDate - Start date
     * @param {String} endDate - End date
     * @param {Object} options - Validation options
     * @returns {Object} Validation result
     */
    static validateDateRange(startDate, endDate, options = {}) {
        const errors = [];

        if (!startDate) {
            errors.push(__('Start date is required'));
        }

        if (!endDate && options.requireEndDate) {
            errors.push(__('End date is required'));
        }

        if (startDate && endDate) {
            const start = frappe.datetime.str_to_obj(startDate);
            const end = frappe.datetime.str_to_obj(endDate);

            if (start > end) {
                errors.push(__('Start date cannot be after end date'));
            }

            if (options.maxDays) {
                const days = Math.floor((end - start) / (1000 * 60 * 60 * 24));
                if (days > options.maxDays) {
                    errors.push(__('Date range cannot exceed {0} days', [options.maxDays]));
                }
            }
        }

        return {
            isValid: errors.length === 0,
            errors
        };
    }
}
