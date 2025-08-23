__version__ = "0.9.0"

# Session authentication fix applied via CSRF secret key in site config
# The "User None is disabled" error was caused by missing csrf_secret_key
# which made Frappe fall back to session-based CSRF tokens that could corrupt
# session data during tab switching and browser reopening.

# Session corruption workaround will be applied during app initialization
# This is a known Frappe issue without a definitive upstream fix
