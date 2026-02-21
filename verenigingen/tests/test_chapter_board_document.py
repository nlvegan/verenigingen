# Copyright (c) 2025, Veganisme.org and Contributors
# See license.txt

"""
Tests for Chapter Board Document functionality
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestChapterBoardDocument(EnhancedTestCase):
    """Test Chapter Board Document creation and management"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create or get region
        if not frappe.db.exists("Region", "Noord-Holland"):
            frappe.get_doc({
                "doctype": "Region",
                "region_name": "Noord-Holland"
            }).insert(ignore_permissions=True)

        # Create a test chapter directly using frappe.get_doc
        self.chapter = frappe.get_doc({
            "doctype": "Chapter",
            "name": "Test Chapter Board Docs",
            "region": "Noord-Holland",
            "status": "Active",
            "introduction": "Test chapter for board documents"
        }).insert(ignore_permissions=True)

        frappe.db.commit()

    def tearDown(self):
        """Clean up test data"""
        # Delete the test chapter
        if frappe.db.exists("Chapter", "Test Chapter Board Docs"):
            frappe.delete_doc("Chapter", "Test Chapter Board Docs", force=True)

        frappe.db.commit()
        super().tearDown()

    def test_create_board_document(self):
        """Test creating a board document via Chapter"""
        # Get the chapter document
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Add a board document
        chapter_doc.append("board_documents", {
            "document_type": "Policy",
            "document_name": "2025-01 Board Policy Document",
            "document_file": "/files/test_policy.pdf",
            "description": "Test policy document"
        })

        chapter_doc.save()

        # Verify the document was added
        self.assertEqual(len(chapter_doc.board_documents), 1)

        # Verify field values
        board_doc = chapter_doc.board_documents[0]
        self.assertEqual(board_doc.document_type, "Policy")
        self.assertEqual(board_doc.document_name, "2025-01 Board Policy Document")
        self.assertEqual(board_doc.document_file, "/files/test_policy.pdf")
        self.assertEqual(board_doc.description, "Test policy document")

        # Verify auto-populated fields
        self.assertIsNotNone(board_doc.upload_date)
        self.assertIsNotNone(board_doc.uploaded_by)

    def test_multiple_document_types(self):
        """Test creating documents of different types"""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Add different document types
        document_types = [
            ("Policy", "2025-01 Privacy Policy"),
            ("Meeting Minutes", "2025-01 January Board Meeting"),
            ("Financial Report", "2025 Q1 Financial Report"),
            ("Other", "2025 Activity Calendar")
        ]

        for doc_type, doc_name in document_types:
            chapter_doc.append("board_documents", {
                "document_type": doc_type,
                "document_name": doc_name,
                "document_file": f"/files/{doc_name.replace(' ', '_').lower()}.pdf"
            })

        chapter_doc.save()

        # Verify all documents were added
        self.assertEqual(len(chapter_doc.board_documents), 4)

        # Verify each type is present
        doc_types_added = [doc.document_type for doc in chapter_doc.board_documents]
        self.assertIn("Policy", doc_types_added)
        self.assertIn("Meeting Minutes", doc_types_added)
        self.assertIn("Financial Report", doc_types_added)
        self.assertIn("Other", doc_types_added)

    def test_uploaded_by_auto_populated(self):
        """Test that uploaded_by field is automatically populated"""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Add a document without specifying uploaded_by
        chapter_doc.append("board_documents", {
            "document_type": "Policy",
            "document_name": "Test Auto Upload",
            "document_file": "/files/test.pdf"
        })

        chapter_doc.save()

        # Verify uploaded_by is populated with current user
        board_doc = chapter_doc.board_documents[0]
        self.assertEqual(board_doc.uploaded_by, frappe.session.user)

    def test_upload_date_auto_populated(self):
        """Test that upload_date is automatically set to today"""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Add a document without specifying upload_date
        chapter_doc.append("board_documents", {
            "document_type": "Meeting Minutes",
            "document_name": "Test Upload Date",
            "document_file": "/files/test_minutes.pdf"
        })

        chapter_doc.save()

        # Verify upload_date is today
        board_doc = chapter_doc.board_documents[0]
        self.assertEqual(str(board_doc.upload_date), str(today()))

    def test_document_sorting_by_name(self):
        """Test that documents can be sorted by name (for date-based naming)"""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Add documents with date-based names (in random order)
        documents = [
            "2025-03 March Minutes",
            "2025-01 January Minutes",
            "2025-02 February Minutes"
        ]

        for doc_name in documents:
            chapter_doc.append("board_documents", {
                "document_type": "Meeting Minutes",
                "document_name": doc_name,
                "document_file": f"/files/{doc_name.replace(' ', '_').lower()}.pdf"
            })

        chapter_doc.save()

        # Get documents and sort by name (descending)
        docs = sorted(
            [doc for doc in chapter_doc.board_documents if doc.document_type == "Meeting Minutes"],
            key=lambda x: x.document_name,
            reverse=True
        )

        # Verify sorting (newest first)
        self.assertEqual(docs[0].document_name, "2025-03 March Minutes")
        self.assertEqual(docs[1].document_name, "2025-02 February Minutes")
        self.assertEqual(docs[2].document_name, "2025-01 January Minutes")

    def test_required_fields_validation(self):
        """Test that required fields are validated"""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Try to add a document without required fields
        chapter_doc.append("board_documents", {
            "description": "Missing required fields"
        })

        # Should raise validation error
        with self.assertRaises(frappe.ValidationError):
            chapter_doc.save()

    def test_file_type_validation(self):
        """Test that only allowed file types can be uploaded"""
        from verenigingen.verenigingen.doctype.chapter_board_document.chapter_board_document import ALLOWED_EXTENSIONS

        # Verify our allowed extensions list includes common formats
        self.assertIn('.pdf', ALLOWED_EXTENSIONS)
        self.assertIn('.docx', ALLOWED_EXTENSIONS)
        self.assertIn('.md', ALLOWED_EXTENSIONS)
        self.assertIn('.epub', ALLOWED_EXTENSIONS)
        self.assertIn('.jpg', ALLOWED_EXTENSIONS)

        # Verify disallowed extensions are not in the list
        self.assertNotIn('.exe', ALLOWED_EXTENSIONS)
        self.assertNotIn('.bat', ALLOWED_EXTENSIONS)
        self.assertNotIn('.sh', ALLOWED_EXTENSIONS)

        # child-table-skip: validation testing only - no insert()
        # Test the validation logic directly
        test_doc = frappe.get_doc({
            "doctype": "Chapter Board Document",
            "document_type": "Policy",
            "document_name": "Test Document",
            "document_file": "/files/malicious.exe"
        })

        # Should raise validation error for .exe file
        with self.assertRaises(frappe.ValidationError) as context:
            test_doc.validate()
        self.assertIn("not allowed", str(context.exception))

    def test_path_traversal_prevention(self):
        """Test that path traversal attempts in document names are blocked"""

        # child-table-skip: validation testing only - no insert()
        # Test the validation logic directly
        test_doc = frappe.get_doc({
            "doctype": "Chapter Board Document",
            "document_type": "Policy",
            "document_name": "../../etc/passwd",
            "document_file": "/files/test.pdf"
        })

        # Should raise validation error for path traversal
        with self.assertRaises(frappe.ValidationError) as context:
            test_doc.validate()
        self.assertIn("path", str(context.exception).lower())

    def test_allowed_document_formats(self):
        """Test that common document formats are accepted"""
        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Test various allowed formats
        allowed_formats = [
            ("/files/document.pdf", "PDF"),
            ("/files/document.docx", "Word"),
            ("/files/document.xlsx", "Excel"),
            ("/files/document.txt", "Text"),
            ("/files/document.md", "Markdown"),
            ("/files/document.epub", "EPUB"),
            ("/files/image.jpg", "JPEG"),
            ("/files/image.png", "PNG")
        ]

        for file_path, format_name in allowed_formats:
            chapter_doc.board_documents = []  # Clear previous
            chapter_doc.append("board_documents", {
                "document_type": "Policy",
                "document_name": f"Test {format_name}",
                "document_file": file_path
            })
            # Should not raise error
            chapter_doc.save()
            self.assertEqual(len(chapter_doc.board_documents), 1)

    def test_document_retrieval_by_type(self):
        """Test retrieving documents organized by type and year"""
        from verenigingen.templates.pages.chapter_dashboard import get_chapter_board_documents

        chapter_doc = frappe.get_doc("Chapter", self.chapter.name)

        # Add various documents with years
        test_docs = [
            ("Policy", "Privacy Policy 2025"),
            ("Policy", "Code of Conduct 2024"),
            ("Meeting Minutes", "January 2025 Meeting"),
            ("Financial Report", "Q1 2025 Report")
        ]

        for doc_type, doc_name in test_docs:
            chapter_doc.append("board_documents", {
                "document_type": doc_type,
                "document_name": doc_name,
                "document_file": f"/files/{doc_name.replace(' ', '_').lower()}.pdf"
            })

        chapter_doc.save()

        # Retrieve documents organized by type and year
        result = get_chapter_board_documents(self.chapter.name)

        # Verify structure
        self.assertIn("by_type_and_year", result)
        self.assertIn("total_count", result)

        # Verify total count
        self.assertEqual(result["total_count"], 4)

        # Verify organization by type and year
        self.assertIn("2025", result["by_type_and_year"]["Policy"])
        self.assertIn("2024", result["by_type_and_year"]["Policy"])
        self.assertIn("2025", result["by_type_and_year"]["Meeting Minutes"])
        self.assertIn("2025", result["by_type_and_year"]["Financial Report"])

        # Verify document counts in years
        self.assertEqual(len(result["by_type_and_year"]["Policy"]["2025"]), 1)
        self.assertEqual(len(result["by_type_and_year"]["Policy"]["2024"]), 1)
        self.assertEqual(len(result["by_type_and_year"]["Meeting Minutes"]["2025"]), 1)
        self.assertEqual(len(result["by_type_and_year"]["Financial Report"]["2025"]), 1)


def run_tests():
    """Helper function to run tests from command line"""
    frappe.flags.in_test = True

    import unittest

    suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterBoardDocument)
    unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == "__main__":
    run_tests()
