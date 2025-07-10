/**
 * Member Portal Redirect JavaScript
 * Handles client-side redirects for members accessing the system
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
