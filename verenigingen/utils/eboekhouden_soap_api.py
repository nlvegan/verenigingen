"""
E-Boekhouden SOAP API Client

⚠️ DEPRECATED - DO NOT USE FOR NEW DEVELOPMENT ⚠️
=====================================
This SOAP API integration is DEPRECATED and should NOT be used for any new development.
The SOAP API has significant limitations:
- Limited to only 500 most recent transactions
- Slower performance compared to REST API
- More complex XML handling
- Legacy authentication method

✅ USE THE REST API INSTEAD ✅
The REST API (eboekhouden_api.py) provides:
- Access to complete transaction history (no 500 limit)
- Better performance and reliability
- Modern JSON-based interface
- Full feature parity with SOAP

This file is maintained only for backward compatibility.
All new features should use the REST API implementation.
=====================================

Provides access to the complete mutation data including descriptions and transaction types
"""

import xml.etree.ElementTree as ET

import frappe
import requests


class EBoekhoudenSOAPAPI:
    def __init__(self, settings=None):
        if not settings:
            settings = frappe.get_single("E-Boekhouden Settings")

        self.soap_url = "https://soap.e-boekhouden.nl/soap.asmx"

        # Get credentials from settings or use defaults for backward compatibility
        if hasattr(settings, "soap_username") and settings.soap_username:
            self.username = settings.soap_username
            self.security_code_1 = (
                settings.get_password("soap_security_code1")
                if hasattr(settings, "soap_security_code1")
                else ""
            )
            self.security_code_2 = (
                settings.get_password("soap_security_code2")
                if hasattr(settings, "soap_security_code2")
                else ""
            )
        else:
            # Fallback to hardcoded values for existing installations
            self.username = "NVV_penningmeester"
            self.security_code_1 = "7e3169c820d849518853df7e30c4ba3f"
            self.security_code_2 = "BB51E315-A9B2-4D37-8E8E-96EF2E2554A7"

        self.session_id = None

    def open_session(self):
        """Open a SOAP session"""
        # Add Source parameter as indicated in WSDL
        source = getattr(self, "source", "ERPNext")

        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <OpenSession xmlns="http://www.e-boekhouden.nl/soap">
      <Username>{self.username}</Username>
      <SecurityCode1>{self.security_code_1}</SecurityCode1>
      <SecurityCode2>{self.security_code_2}</SecurityCode2>
      <Source>{source}</Source>
    </OpenSession>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.e-boekhouden.nl/soap/OpenSession"',
        }

        try:
            response = requests.post(self.soap_url, data=envelope, headers=headers, timeout=30)
            if response.status_code == 200:
                # Parse the full response to check for errors
                root = ET.fromstring(response.text)

                # Look for SessionID
                session_id = None
                error_msg = None

                for elem in root.iter():
                    if "SessionID" in elem.tag and elem.text and elem.text.strip():
                        session_id = elem.text.strip()
                    elif "ErrorMsg" in elem.tag and elem.text:
                        error_msg = elem.text.strip()

                if session_id:
                    self.session_id = session_id
                    return {"success": True, "session_id": self.session_id}
                else:
                    # Return detailed error info
                    return {
                        "success": False,
                        "error": f"No SessionID in response. Error: {error_msg}",
                        "response_text": response.text[:1000],
                    }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "response_text": response.text[:1000],
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_mutations(self, date_from=None, date_to=None, mutation_nr_from=None, mutation_nr_to=None):
        """Get mutations with full details including descriptions"""
        if not self.session_id:
            session_result = self.open_session()
            if not session_result["success"]:
                return session_result

        # Build filter
        filter_xml = ""
        if mutation_nr_from and mutation_nr_to:
            filter_xml = """
        <MutatieNrVan>{mutation_nr_from}</MutatieNrVan>
        <MutatieNrTot>{mutation_nr_to}</MutatieNrTot>"""
        if date_from and date_to:
            filter_xml += """
        <DatumVan>{date_from}</DatumVan>
        <DatumTm>{date_to}</DatumTm>"""

        envelope = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetMutaties xmlns="http://www.e-boekhouden.nl/soap">
      <SecurityCode2>{self.security_code_2}</SecurityCode2>
      <SessionID>{self.session_id}</SessionID>
      <cFilter>{filter_xml}
      </cFilter>
    </GetMutaties>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.e-boekhouden.nl/soap/GetMutaties"',
        }

        try:
            response = requests.post(self.soap_url, data=envelope, headers=headers, timeout=60)
            if response.status_code == 200:
                return self._parse_mutations_response(response.text)
            else:
                return {"success": False, "error": "Failed to get mutations: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_mutations_response(self, xml_text):
        """Parse mutations from SOAP response"""
        try:
            root = ET.fromstring(xml_text)
            mutations = []

            # Find all cMutatieList elements but only at the correct level
            # First find GetMutatiesResult, then Mutaties, then process cMutatieList
            mutations_parent = None

            # Navigate to the correct parent element
            for elem in root.iter():
                if "GetMutatiesResult" in elem.tag:
                    for child in elem:
                        if "Mutaties" in child.tag:
                            mutations_parent = child
                            break
                    break

            if not mutations_parent:
                return {"success": True, "mutations": [], "count": 0}

            # Process only direct children that are cMutatieList elements
            for mutatie_elem in mutations_parent:
                if "cMutatieList" in mutatie_elem.tag:
                    mut_data = {}
                    mutation_lines = []

                    # Get all child elements
                    for field in mutatie_elem:
                        field_name = field.tag.split("}")[-1] if "}" in field.tag else field.tag

                        if field_name == "MutatieRegels":
                            # Parse mutation lines - only direct children
                            for regel in field:
                                if "cMutatieListRegel" in regel.tag:
                                    regel_data = {}
                                    for regel_field in regel:
                                        regel_field_name = (
                                            regel_field.tag.split("}")[-1]
                                            if "}" in regel_field.tag
                                            else regel_field.tag
                                        )
                                        if regel_field.text:
                                            regel_data[regel_field_name] = regel_field.text
                                    if regel_data:
                                        mutation_lines.append(regel_data)
                        elif field.text:
                            mut_data[field_name] = field.text

                    if mut_data:
                        mut_data["MutatieRegels"] = mutation_lines
                        mutations.append(mut_data)

            return {"success": True, "mutations": mutations, "count": len(mutations)}

        except Exception as e:
            frappe.log_error(f"Error parsing mutations: {str(e)}", "E-Boekhouden SOAP")
            return {"success": False, "error": str(e)}

    def get_grootboekrekeningen(self):
        """Get chart of accounts (Grootboekrekeningen)"""
        if not self.session_id:
            session_result = self.open_session()
            if not session_result["success"]:
                return session_result

        envelope = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetGrootboekrekeningen xmlns="http://www.e-boekhouden.nl/soap">
      <SecurityCode2>{self.security_code_2}</SecurityCode2>
      <SessionID>{self.session_id}</SessionID>
      <cFilter>
        <ID>0</ID>
        <Code></Code>
        <Categorie></Categorie>
      </cFilter>
    </GetGrootboekrekeningen>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.e-boekhouden.nl/soap/GetGrootboekrekeningen"',
        }

        try:
            response = requests.post(self.soap_url, data=envelope, headers=headers, timeout=30)
            if response.status_code == 200:
                return self._parse_grootboekrekeningen_response(response.text)
            else:
                return {"success": False, "error": "Failed: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_grootboekrekeningen_response(self, xml_text):
        """Parse chart of accounts from response"""
        try:
            root = ET.fromstring(xml_text)
            accounts = []

            for account_elem in root.iter():
                if "cGrootboekrekening" in account_elem.tag:
                    acc_data = {}
                    for field in account_elem:
                        field_name = field.tag.split("}")[-1] if "}" in field.tag else field.tag
                        if field.text:
                            acc_data[field_name] = field.text
                    if acc_data:
                        accounts.append(acc_data)

            return {"success": True, "accounts": accounts, "count": len(accounts)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_relaties(self):
        """Get relations (customers and suppliers)"""
        if not self.session_id:
            session_result = self.open_session()
            if not session_result["success"]:
                return session_result

        envelope = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetRelaties xmlns="http://www.e-boekhouden.nl/soap">
      <SecurityCode2>{self.security_code_2}</SecurityCode2>
      <SessionID>{self.session_id}</SessionID>
      <cFilter>
        <Code></Code>
        <ID>0</ID>
      </cFilter>
    </GetRelaties>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.e-boekhouden.nl/soap/GetRelaties"',
        }

        try:
            response = requests.post(self.soap_url, data=envelope, headers=headers, timeout=30)
            if response.status_code == 200:
                return self._parse_relaties_response(response.text)
            else:
                return {"success": False, "error": "Failed: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _parse_relaties_response(self, xml_text):
        """Parse relations from response"""
        try:
            root = ET.fromstring(xml_text)
            relations = []

            for relation_elem in root.iter():
                if "cRelatie" in relation_elem.tag:
                    rel_data = {}
                    for field in relation_elem:
                        field_name = field.tag.split("}")[-1] if "}" in field.tag else field.tag
                        if field.text:
                            rel_data[field_name] = field.text
                    if rel_data:
                        relations.append(rel_data)

            return {"success": True, "relations": relations, "count": len(relations)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_highest_mutation_number(self):
        """Get the highest mutation number to understand the full range"""
        if not self.session_id:
            session_result = self.open_session()
            if not session_result["success"]:
                return session_result

        # Try to get the last mutation by using a very high number range
        # Start with a reasonable high number and work backwards
        envelope = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetMutaties xmlns="http://www.e-boekhouden.nl/soap">
      <SecurityCode2>{self.security_code_2}</SecurityCode2>
      <SessionID>{self.session_id}</SessionID>
      <cFilter>
        <MutatieNrVan>999999</MutatieNrVan>
        <MutatieNrTot>9999999</MutatieNrTot>
      </cFilter>
    </GetMutaties>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.e-boekhouden.nl/soap/GetMutaties"',
        }

        try:
            response = requests.post(self.soap_url, data=envelope, headers=headers, timeout=60)
            if response.status_code == 200:
                # Even if no mutations in this range, try a lower range
                # Get mutations from the last year to find the highest number
                date_to = frappe.utils.today()
                date_from = frappe.utils.add_years(date_to, -1)

                result = self.get_mutations(date_from=date_from, date_to=date_to)
                if result["success"] and result["mutations"]:
                    # Find the highest mutation number
                    highest = 0
                    for mut in result["mutations"]:
                        mut_nr = mut.get("MutatieNr")
                        if mut_nr:
                            try:
                                nr = int(mut_nr)
                                if nr > highest:
                                    highest = nr
                            except Exception:
                                pass

                    # Now get a few more recent ones to ensure we have the latest
                    if highest > 0:
                        recent_result = self.get_mutations(
                            mutation_nr_from=highest + 1, mutation_nr_to=highest + 10000
                        )
                        if recent_result["success"] and recent_result["mutations"]:
                            for mut in recent_result["mutations"]:
                                mut_nr = mut.get("MutatieNr")
                                if mut_nr:
                                    try:
                                        nr = int(mut_nr)
                                        if nr > highest:
                                            highest = nr
                                    except Exception:
                                        pass

                    return {"success": True, "highest_mutation_number": highest}
                else:
                    return {"success": False, "error": "No mutations found to determine highest number"}
            else:
                return {"success": False, "error": "Failed to get mutations: {response.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_soap_api():
    """Test the SOAP API client"""
    api = EBoekhoudenSOAPAPI()

    # Test getting mutations
    result = api.get_mutations(date_from="2025-06-01", date_to="2025-06-30")

    if result["success"]:
        return {
            "success": True,
            "mutation_count": result["count"],
            "sample_mutation": result["mutations"][0] if result["mutations"] else None,
            "transaction_types": list(set(m.get("Soort", "Unknown") for m in result["mutations"])),
        }
    else:
        return result


@frappe.whitelist()
def test_connection():
    """Test SOAP API connection"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenSOAPAPI(settings)

        # Try to open session
        result = api.open_session()

        if result["success"]:
            return {
                "success": True,
                "message": "Successfully connected to E-Boekhouden SOAP API",
                "session_id": result["session_id"],
            }
        else:
            return {"success": False, "error": result.get("error", "Failed to connect"), "details": result}

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def debug_soap_relations():
    """Debug SOAP relations response to understand data structure"""
    try:
        settings = frappe.get_single("E-Boekhouden Settings")
        api = EBoekhoudenSOAPAPI(settings)

        # Open session
        session_result = api.open_session()
        if not session_result["success"]:
            return {"success": False, "error": "Session failed: {session_result}"}

        # Get raw relations
        envelope = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetRelaties xmlns="http://www.e-boekhouden.nl/soap">
      <SecurityCode2>{api.security_code_2}</SecurityCode2>
      <SessionID>{api.session_id}</SessionID>
      <cFilter>
        <Code></Code>
        <ID>0</ID>
      </cFilter>
    </GetRelaties>
  </soap:Body>
</soap:Envelope>"""

        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"http://www.e-boekhouden.nl/soap/GetRelaties"',
        }

        response = requests.post(api.soap_url, data=envelope, headers=headers, timeout=30)

        if response.status_code == 200:
            # Return raw response for analysis
            result = {
                "success": True,
                "raw_response": response.text[:2000],  # First 2000 chars
                "response_length": len(response.text),
                "session_id": api.session_id,
            }

            # Try to parse and see what we get
            try:
                root = ET.fromstring(response.text)
                relation_elements = []

                for elem in root.iter():
                    if "cRelatie" in elem.tag or "Relatie" in elem.tag:
                        relation_data = {}
                        for child in elem:
                            field_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                            if child.text:
                                relation_data[field_name] = child.text
                        if relation_data:
                            relation_elements.append(relation_data)

                result["parsed_relations"] = relation_elements[:5]  # First 5
                result["total_parsed"] = len(relation_elements)

            except Exception as parse_e:
                result["parse_error"] = str(parse_e)

            return result
        else:
            return {
                "success": False,
                "error": "HTTP {response.status_code}",
                "response_text": response.text[:1000],
            }

    except Exception as e:
        return {"success": False, "error": str(e)}
