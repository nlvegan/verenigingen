"""Read the per-key cooldowns the two v15 patches hard-code (#2012).

The values are read from the patch SOURCE by an AST walk, so a test can pin "registry == the
migrate patch, except the #1999 keys" without a second hand-typed table that could drift.
"""

import ast
from pathlib import Path

PATCH_DIR = Path(__file__).resolve().parents[2] / "patches" / "v15_0"
MIGRATE_PATCH = PATCH_DIR / "migrate_email_settings_to_configuration.py"
TEAM_PATCH = PATCH_DIR / "add_team_chapter_notification_types.py"

# Ruled on #1999 (maintainer): these keep their registry value although the team patch disagrees.
RULED_ON_1999 = {"payment_reminder_friendly", "payment_reminder_urgent"}


def patch_cooldowns(path):
    """{notification_key: cooldown_minutes} for every dict literal in ``path`` that has both."""
    found = {}
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if not isinstance(node, ast.Dict):
            continue
        entry = {
            k.value: v.value
            for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
        }
        if "notification_key" in entry and "cooldown_minutes" in entry:
            found[entry["notification_key"]] = entry["cooldown_minutes"]
    return found


def ruled_v15_cooldowns(registry_keys):
    """{key: value the ruling gives it}: migrate patch wins over team patch, #1999 keys excluded,
    keys the registry does not know excluded."""
    team = patch_cooldowns(TEAM_PATCH)
    ruled = {**team, **patch_cooldowns(MIGRATE_PATCH)}
    return {k: v for k, v in ruled.items() if k in registry_keys and k not in RULED_ON_1999}
