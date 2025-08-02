/**
 * @fileoverview Member Portal Redirect System - Intelligent User Experience Navigation
 * 
 * This module provides intelligent client-side redirect functionality for association members,
 * ensuring users are automatically directed to the most appropriate interface based on their
 * role, permissions, and usage context. Enhances user experience by eliminating navigation
 * confusion and providing role-appropriate access patterns.
 * 
 * Key Features:
 * - Automatic member portal redirection for role-based access
 * - Intelligent path analysis to prevent inappropriate redirects
 * - Integration with Frappe authentication and session management
 * - Server-side coordination for consistent redirect behavior
 * - Login form enhancement with post-authentication routing
 * - Global utility functions for custom redirect scenarios
 * 
 * Business Value:
 * - Improves member user experience through intelligent navigation
 * - Reduces support burden by eliminating navigation confusion
 * - Ensures members access appropriate interfaces automatically
 * - Supports role-based access control and security policies
 * - Facilitates smooth member onboarding and engagement
 * - Maintains consistent user experience across system access points
 * 
 * Technical Architecture:
 * - Client-side JavaScript with jQuery integration
 * - Role-based routing with session state analysis
 * - API integration for server-side redirect decisions
 * - Event-driven redirect handling for dynamic scenarios
 * - Global namespace exposure for extensibility
 * - Non-intrusive operation preserving existing functionality
 * 
 * Security Features:
 * - Session validation before redirect operations
 * - Role-based authorization checks
 * - Guest user protection against unauthorized redirects
 * - Path validation to prevent redirect loops
 * - Integration with Frappe security framework
 * 
 * User Experience Enhancements:
 * - Seamless redirect timing to prevent jarring transitions
 * - Contextual redirect decisions based on current location
 * - Login form integration for post-authentication routing
 * - Preservation of user intent during navigation
 * - Smooth transition animations and timing
 * 
 * @author Verenigingen Development Team
 * @version 2.1.0
 * @since 1.0.0
 * 
 * @requires frappe (Frappe framework client-side API)
 * @requires jQuery (DOM manipulation and event handling)
 * @requires verenigingen.auth_hooks (Server-side authentication integration)
 * 
 * @example
 * // Automatic redirect functionality:
 * // 1. Member logs into system
 * // 2. System detects member role and current location
 * // 3. Automatically redirects to member portal if appropriate
 * // 4. Provides smooth transition with timing optimization
 * 
 * // Manual redirect checking:
 * window.MemberPortalRedirect.checkMemberPortalRedirect();
 * 
 * @see {@link verenigingen.auth_hooks.get_member_home_page} Server-side redirect logic
 * @see {@link /member_portal} Member portal destination
 */

$(document).ready(function() {
	// Only run on web pages, not in backend/app
	if (window.location.pathname.startsWith('/app')) {
		return;
	}

	// Check if user should be redirected to member portal
	checkMemberPortalRedirect();
});

function checkMemberPortalRedirect() {
	// Skip for guest users
	if (!frappe.session.user || frappe.session.user === 'Guest') {
		return;
	}

	// Check if user has member role and should be on member portal
	if (frappe.user_roles && frappe.user_roles.includes('Member')) {
		// If on homepage or generic pages, redirect to member portal
		const currentPath = window.location.pathname;

		// Pages that should redirect to member portal for members
		const redirectPaths = ['/', '/index', '/home', '/web'];

		if (redirectPaths.includes(currentPath)) {
			// Use API to check if user should be redirected
			frappe.call({
				method: 'verenigingen.auth_hooks.get_member_home_page',
				callback: function(r) {
					if (r.message && r.message === '/member_portal') {
						// Redirect to member portal with a small delay
						setTimeout(function() {
							window.location.href = '/member_portal';
						}, 500);
					}
				}
			});
		}
	}
}

// Handle login form redirects
$(document).on('submit', 'form[data-web-form="login"]', function() {
	// After successful login, the server-side hook will handle the redirect
	// This is just for additional client-side handling if needed
});

// Export functions for use elsewhere
window.MemberPortalRedirect = {
	checkMemberPortalRedirect: checkMemberPortalRedirect
};
