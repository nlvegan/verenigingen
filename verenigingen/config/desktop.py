from frappe import _


def get_data():
    return [
        {
            "module_name": "Verenigingen",
            "color": "grey",
            "icon": "octicon octicon-file-directory",
            "type": "module",
            "label": _("Verenigingen"),
            "links": [
                {
                    "label": _("E-Boekhouden"),
                    "items": [
                        {
                            "type": "doctype",
                            "name": "E-Boekhouden Dashboard",
                            "label": _("Migration Dashboard"),
                            "description": _("Monitor migration status and system health"),
                        },
                        {
                            "type": "doctype",
                            "name": "E-Boekhouden Migration",
                            "label": _("Migrations"),
                            "description": _("Create and manage data migrations"),
                        },
                        {
                            "type": "doctype",
                            "name": "E-Boekhouden Settings",
                            "label": _("Settings"),
                            "description": _("Configure API connection and defaults"),
                        },
                        {
                            "type": "page",
                            "name": "e-boekhouden-dashboard",
                            "label": _("Live Dashboard"),
                            "description": _("Real-time migration dashboard"),
                        },
                    ],
                }
            ],
        }
    ]
