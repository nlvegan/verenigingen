# verenigingen/hooks/apps_screen.py
"""The app's tile on the desk's Apps screen (Desktop Settings = Apps).

That screen is built only from this hook; an app without it has no tile.
"""

add_to_apps_screen = [
    {
        "name": "verenigingen",
        "logo": "/assets/verenigingen/icons/desktop_icons/solid/verenigingen.svg",
        "title": "Verenigingen",
        "route": "/desk/verenigingen",
        "has_permission": "verenigingen.permissions.check_app_permission",
    }
]
