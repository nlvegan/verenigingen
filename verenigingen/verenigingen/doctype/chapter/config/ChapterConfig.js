/**
 * @fileoverview Chapter Configuration System - Central configuration management for Chapter DocType
 *
 * This module provides comprehensive configuration management for the Chapter DocType,
 * encompassing board management, member operations, communications, statistics, validation,
 * API settings, and feature flags. It serves as the single source of truth for all
 * chapter-related configuration parameters.
 *
 * Key Features:
 * - Board management rules and role definitions
 * - Member status and operation limits
 * - Communication templates and batch processing
 * - Statistical dashboard and chart configurations
 * - Form validation patterns and rules
 * - API endpoints and rate limiting
 * - Feature toggles and workflow settings
 * - Helper methods for configuration access
 *
 * Usage:
 * ```javascript
 * import { ChapterConfig } from './ChapterConfig.js';
 *
 * // Get board minimum size
 * const minSize = ChapterConfig.get('board.minimumSize', 3);
 *
 * // Check if feature is enabled
 * if (ChapterConfig.isFeatureEnabled('enableBoardManagement')) {
 *     // Board management logic
 * }
 *
 * // Get role permissions
 * const permissions = ChapterConfig.getRolePermissions('Chair');
 * ```
 *
 * Configuration Categories:
 * - board: Board composition, roles, permissions, and tenure rules
 * - members: Member status, pagination, export/import limits
 * - communication: Email batching, templates, attachment rules
 * - statistics: Chart colors, metrics, refresh intervals
 * - postalCodes: Validation patterns by country
 * - ui: Animation durations, modal sizes, pagination
 * - validation: Field patterns, length limits, required permissions
 * - api: Timeouts, retry logic, rate limits, endpoints
 * - features: Feature flags for various functionalities
 * - messages: Error, confirmation, and success message templates
 * - dateTime: Date/time formatting and working day definitions
 * - security: Session, password, and audit configurations
 * - integrations: Volunteer, SEPA, and event integration settings
 * - workflows: Approval processes and notification templates
 *
 * Business Rules:
 * - Boards must have minimum 3 members, maximum 15
 * - Critical roles (Chair, President, Treasurer) have enhanced permissions
 * - Member exports limited to 500 records per batch
 * - Email communications respect unsubscribe requirements
 * - Statistical data refreshes every 5 minutes
 * - API requests timeout after 30 seconds with 3 retry attempts
 * - Strong password requirements and session management
 *
 * @module ChapterConfig
 * @version 2.1.0
 * @since 1.0.0
 * @requires frappe
 * @see {@link https://frappeframework.com/docs/user/en/api/frappe-client|Frappe Client API}
 * @see {@link ../chapter.js|Chapter Controller}
 * @see {@link ../modules/ChapterController.js|Chapter Controller Module}
 *
 * @author Verenigingen System
 * @copyright 2024 Verenigingen
 */

export const ChapterConfig = {
	// Board Management Configuration
	board: {
		minimumSize: 3,
		maximumSize: 15,
		defaultRoles: ['Chair', 'Secretary', 'Treasurer'],
		requiredRoles: ['Chair', 'Secretary', 'Treasurer'],
		criticalRoles: ['Chair', 'President', 'Treasurer'],
		rolePermissions: {
			Chair: ['manage_all', 'view_financials', 'send_communications'],
			President: ['manage_all', 'view_financials', 'send_communications'],
			Secretary: ['manage_members', 'send_communications', 'view_reports'],
			Treasurer: ['view_financials', 'manage_payments', 'view_reports'],
			'Board Member': ['view_reports', 'vote']
		},
		tenureWarningDays: 365, // Warn if board member tenure exceeds this
		maxTenureYears: 10,
		inactivityWarningDays: 90, // Warn if no board activity for this many days
		transitionNoticeDays: 30, // Notice period for role transitions
		bulkOperationLimit: 10 // Maximum members for bulk operations
	},

	// Member Management Configuration
	members: {
		defaultMemberStatus: 'Active',
		allowedStatuses: ['Active', 'Inactive', 'Suspended', 'Expired'],
		exportBatchSize: 500,
		importBatchSize: 100,
		searchResultLimit: 50,
		directoryPageSize: 24,
		memberCardFields: ['full_name', 'email', 'mobile_no', 'member_since', 'status'],
		requiredFields: ['full_name', 'email'],
		maxIntroductionLength: 500,
		defaultMemberPermissions: ['view_directory', 'update_profile']
	},

	// Communication Configuration
	communication: {
		emailBatchSize: 50,
		maxRecipientsPerEmail: 500,
		defaultEmailDelay: 100, // milliseconds between emails
		unsubscribeTokenExpiry: 30, // days
		emailTemplates: {
			welcome: 'Welcome to {chapter_name}',
			board_appointment: 'Board Appointment Notification',
			meeting_reminder: 'Chapter Meeting Reminder',
			newsletter: 'Chapter Newsletter'
		},
		allowedAttachmentTypes: ['.pdf', '.doc', '.docx', '.jpg', '.png', '.xlsx'],
		maxAttachmentSize: 10 * 1024 * 1024, // 10MB
		newsletterSections: {
			maxSections: 10,
			maxSectionLength: 5000
		},
		communicationRetentionDays: 365,
		trackEmailOpens: true,
		requireUnsubscribeLink: true
	},

	// Statistics Configuration
	statistics: {
		refreshInterval: 300000, // 5 minutes in milliseconds
		cacheDuration: 3600, // 1 hour in seconds
		chartColors: {
			primary: '#007bff',
			success: '#28a745',
			danger: '#dc3545',
			warning: '#ffc107',
			info: '#17a2b8',
			secondary: '#6c757d'
		},
		chartColorPalette: [
			'#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8',
			'#6610f2', '#e83e8c', '#fd7e14', '#20c997', '#6c757d'
		],
		defaultChartHeight: 300,
		exportFormats: ['csv', 'xlsx', 'pdf'],
		dateRanges: {
			last_30_days: { label: __('Last 30 Days'), days: 30 },
			last_90_days: { label: __('Last 90 Days'), days: 90 },
			last_year: { label: __('Last Year'), days: 365 },
			all_time: { label: __('All Time'), days: null }
		},
		engagementScoreWeights: {
			eventAttendance: 10,
			volunteerHours: 5,
			communications: 2,
			donations: 8
		},
		dashboardMetrics: [
			'total_members',
			'active_members',
			'board_members',
			'retention_rate',
			'engagement_score',
			'recent_activities'
		]
	},

	// Postal Code Configuration
	postalCodes: {
		maxPatterns: 50,
		patternTypes: ['exact', 'range', 'wildcard'],
		validationRules: {
			NL: /^[1-9][0-9]{3}$/, // Netherlands
			BE: /^[1-9][0-9]{3}$/, // Belgium
			DE: /^[0-9]{5}$/, // Germany
			US: /^[0-9]{5}$/, // USA
			UK: /^[A-Z]{1,2}[0-9][0-9A-Z]?$/ // UK
		},
		defaultCountry: 'NL'
	},

	// UI Configuration
	ui: {
		animationDuration: 300,
		toastDuration: 5000,
		loadingDelay: 500,
		debounceDelay: 300,
		modalSizes: {
			small: '400px',
			medium: '600px',
			large: '800px',
			'extra-large': '1200px'
		},
		gridRowHeight: 35,
		avatarSizes: {
			small: 30,
			medium: 50,
			large: 80
		},
		pagination: {
			itemsPerPage: 20,
			maxPageButtons: 5
		}
	},

	// Validation Configuration
	validation: {
		namePattern: /^[a-zA-Z0-9\s\-_]+$/,
		emailPattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
		phonePattern: /^[\d\s\-\+\(\)]+$/,
		urlPattern: /^https?:\/\/.+$/,
		maxFieldLengths: {
			name: 100,
			description: 1000,
			address: 500,
			notes: 2000
		},
		requiredPermissions: {
			board_management: ['Verenigingen Administrator', 'System Manager'],
			member_management: ['Verenigingen Administrator', 'System Manager', 'Verenigingen Chapter Board Member'],
			communication: ['Verenigingen Administrator', 'System Manager', 'Verenigingen Chapter Board Member'],
			statistics: ['Verenigingen Administrator', 'System Manager', 'Verenigingen Chapter Board Member'],
			export_data: ['Verenigingen Administrator', 'System Manager']
		}
	},

	// API Configuration
	api: {
		timeout: 30000, // 30 seconds
		retryAttempts: 3,
		retryDelay: 1000,
		batchSize: 100,
		rateLimits: {
			emailsPerHour: 1000,
			apiCallsPerMinute: 60
		},
		endpoints: {
			boardHistory: 'verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_board_history',
			chapterStats: 'verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_stats',
			volunteerSync: 'verenigingen.verenigingen.doctype.volunteer.volunteer.sync_chapter_board_members',
			bulkRemove: 'verenigingen.verenigingen.doctype.chapter.chapter.bulk_remove_board_members',
			bulkDeactivate: 'verenigingen.verenigingen.doctype.chapter.chapter.bulk_deactivate_board_members'
		}
	},

	// Feature Flags
	features: {
		enableBoardManagement: true,
		enableMemberDirectory: true,
		enableCommunications: true,
		enableStatistics: true,
		enablePostalCodes: true,
		enableBulkOperations: true,
		enableNewsletters: true,
		enableVolunteerIntegration: true,
		enableSEPAMandates: true,
		enableEventIntegration: false,
		enableDonationTracking: false
	},

	// Default Messages
	messages: {
		errors: {
			generic: __('An error occurred. Please try again.'),
			permission: __('You do not have permission to perform this action.'),
			validation: __('Please correct the errors before proceeding.'),
			network: __('Network error. Please check your connection.'),
			timeout: __('Request timed out. Please try again.')
		},
		confirmations: {
			delete: __('Are you sure you want to delete this item?'),
			save: __('Do you want to save your changes?'),
			cancel: __('Are you sure you want to cancel? Unsaved changes will be lost.'),
			bulkAction: __('This action will affect {0} items. Continue?')
		},
		success: {
			saved: __('Changes saved successfully'),
			deleted: __('Item deleted successfully'),
			sent: __('Email sent successfully'),
			exported: __('Data exported successfully')
		}
	},

	// Date and Time Configuration
	dateTime: {
		defaultDateFormat: 'YYYY-MM-DD',
		defaultTimeFormat: 'HH:mm',
		defaultDateTimeFormat: 'YYYY-MM-DD HH:mm',
		firstDayOfWeek: 1, // Monday
		workingDays: [1, 2, 3, 4, 5], // Monday to Friday
		timezone: 'system' // Use system timezone
	},

	// Security Configuration
	security: {
		sessionTimeout: 3600, // 1 hour in seconds
		maxLoginAttempts: 5,
		passwordMinLength: 8,
		requireStrongPassword: true,
		twoFactorAuth: false,
		auditLogRetention: 90 // days
	},

	// Integration Configuration
	integrations: {
		volunteer: {
			enabled: true,
			syncInterval: 86400, // 24 hours in seconds
			fieldMapping: {
				volunteer_name: 'full_name',
				email: 'email',
				phone: 'mobile_no'
			}
		},
		sepa: {
			enabled: true,
			mandatePrefix: 'M',
			defaultMandateType: 'RCUR',
			expiryWarningDays: 30
		},
		events: {
			enabled: false,
			defaultRSVPDeadline: 7, // days before event
			reminderDays: [7, 3, 1]
		}
	},

	// Workflow Configuration
	workflows: {
		boardAppointment: {
			requireApproval: true,
			approvers: ['Verenigingen Administrator'],
			notificationTemplate: 'board_appointment_approval'
		},
		memberTermination: {
			requireApproval: true,
			approvers: ['Verenigingen Administrator', 'System Manager'],
			gracePeriodDays: 30
		}
	},

	// Helper Methods

	/**
     * Get configuration value by path
     * @param {String} path - Dot-separated path (e.g., 'board.minimumSize')
     * @param {*} defaultValue - Default value if path not found
     * @returns {*} Configuration value
     */
	get(path, defaultValue = null) {
		const keys = path.split('.');
		let value = this;

		for (const key of keys) {
			if (value && typeof value === 'object' && key in value) {
				value = value[key];
			} else {
				return defaultValue;
			}
		}

		return value;
	},

	/**
     * Check if a feature is enabled
     * @param {String} feature - Feature name
     * @returns {Boolean} Whether feature is enabled
     */
	isFeatureEnabled(feature) {
		return this.features[feature] === true;
	},

	/**
     * Get role permissions
     * @param {String} role - Role name
     * @returns {Array} Array of permissions
     */
	getRolePermissions(role) {
		return this.board.rolePermissions[role] || [];
	},

	/**
     * Get validation pattern
     * @param {String} type - Pattern type (name, email, phone, url)
     * @returns {RegExp} Regular expression pattern
     */
	getValidationPattern(type) {
		return this.validation[`${type}Pattern`] || null;
	},

	/**
     * Get API endpoint
     * @param {String} endpoint - Endpoint name
     * @returns {String} Full endpoint path
     */
	getEndpoint(endpoint) {
		return this.api.endpoints[endpoint] || null;
	},

	/**
     * Get date range configuration
     * @param {String} range - Range name
     * @returns {Object} Date range configuration
     */
	getDateRange(range) {
		return this.statistics.dateRanges[range] || null;
	},

	/**
     * Get chart color by index
     * @param {Number} index - Color index
     * @returns {String} Hex color code
     */
	getChartColor(index) {
		const colors = this.statistics.chartColorPalette;
		return colors[index % colors.length];
	},

	/**
     * Get maximum field length
     * @param {String} field - Field name
     * @returns {Number} Maximum length
     */
	getMaxFieldLength(field) {
		return this.validation.maxFieldLengths[field] || 255;
	},

	/**
     * Get message template
     * @param {String} category - Message category (errors, confirmations, success)
     * @param {String} key - Message key
     * @returns {String} Message template
     */
	getMessage(category, key) {
		return this.messages[category]?.[key] || this.messages.errors.generic;
	}
};
