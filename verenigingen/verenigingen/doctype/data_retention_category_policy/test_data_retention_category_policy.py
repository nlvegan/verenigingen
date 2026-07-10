import json
import os
import unittest

from verenigingen.verenigingen_payments.core.compliance.data_retention_policy import (
    DataCategory,
    RetentionAction,
)


class TestCategoryPolicyEnumSync(unittest.TestCase):
    def _load_json(self):
        here = os.path.dirname(__file__)
        with open(os.path.join(here, "data_retention_category_policy.json")) as f:
            return json.load(f)

    def _options(self, doc, fieldname):
        field = next(f for f in doc["fields"] if f["fieldname"] == fieldname)
        return set(o for o in field["options"].split("\n") if o)

    def test_category_options_match_enum(self):
        doc = self._load_json()
        self.assertEqual(self._options(doc, "category"), {c.value for c in DataCategory})

    def test_action_options_match_enum(self):
        doc = self._load_json()
        self.assertEqual(self._options(doc, "action"), {a.value for a in RetentionAction})
