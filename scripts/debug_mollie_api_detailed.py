#!/usr/bin/env python3
"""
Detailed debug script for Mollie API vs our client implementation
"""

import sys
import os
import json
import requests
from datetime import datetime

# Add the frappe-bench path to import frappe
sys.path.insert(0, '/home/frappe/frappe-bench/apps/frappe')
sys.path.insert(0, '/home/frappe/frappe-bench/apps/erpnext')
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

# Change to bench directory
os.chdir('/home/frappe/frappe-bench')

import frappe

def debug_mollie_implementation():
    """Compare raw Mollie API with our client implementation"""
    
    # Initialize frappe
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    
    try:
        print("="*60)
        print("MOLLIE API DEBUG - DETAILED COMPARISON")
        print("="*60)
        print(f"Timestamp: {datetime.now()}")
        print()
        
        # Step 1: Get credentials
        print("1. GETTING CREDENTIALS")
        print("-" * 30)
        
        settings = frappe.get_single('Mollie Settings')
        oat = settings.get_password('organization_access_token', raise_exception=False)
        
        if not oat:
            print("❌ ERROR: No Organization Access Token found")
            return
        
        print(f"✅ Organization Access Token found: {oat[:20]}...")
        print(f"✅ Backend API enabled: {settings.enable_backend_api}")
        print()
        
        # Step 2: Raw API call
        print("2. RAW MOLLIE API CALL")
        print("-" * 30)
        
        url = "https://api.mollie.com/v2/balances"
        headers = {
            "Authorization": f"Bearer {oat}",
            "Content-Type": "application/json"
        }
        
        print(f"🔗 URL: {url}")
        print(f"🔑 Authorization: Bearer {oat[:20]}...")
        
        response = requests.get(url, headers=headers)
        
        print(f"📊 Response Status: {response.status_code}")
        print(f"📝 Response Headers: {dict(response.headers)}")
        print()
        
        if response.status_code != 200:
            print(f"❌ API Error: {response.text}")
            return
            
        # Parse raw response
        raw_data = response.json()
        print(f"✅ Raw JSON Response:")
        print(json.dumps(raw_data, indent=2))
        print()
        
        # Extract balances from raw response
        raw_balances = []
        if '_embedded' in raw_data and 'balances' in raw_data['_embedded']:
            raw_balances = raw_data['_embedded']['balances']
            
        print(f"📈 Raw API returned {len(raw_balances)} balances")
        for i, balance in enumerate(raw_balances):
            print(f"  Balance {i+1}:")
            print(f"    ID: {balance.get('id')}")
            print(f"    Currency: {balance.get('currency')}")
            print(f"    Status: {balance.get('status')}")
            
            available = balance.get('availableAmount', {})
            print(f"    Available Amount (raw): {available}")
            
            pending = balance.get('pendingAmount', {})
            print(f"    Pending Amount (raw): {pending}")
            print()
        
        # Step 3: Our client implementation
        print("3. OUR CLIENT IMPLEMENTATION")
        print("-" * 30)
        
        from verenigingen.verenigingen_payments.clients.balances_client import BalancesClient
        
        client = BalancesClient()
        print(f"✅ Client initialized: {type(client)}")
        
        # Test our client
        client_balances = client.list_balances()
        print(f"📊 Our client returned {len(client_balances)} balances")
        
        for i, balance in enumerate(client_balances):
            print(f"  Balance {i+1} (Our Client):")
            print(f"    ID: {balance.id}")
            print(f"    Currency: {balance.currency}")
            print(f"    Status: {balance.status}")
            print(f"    Type: {type(balance)}")
            
            # Check available amount
            print(f"    Available amount object: {balance.available_amount}")
            print(f"    Available amount type: {type(balance.available_amount)}")
            
            if hasattr(balance, 'available_amount') and balance.available_amount:
                if hasattr(balance.available_amount, 'decimal_value'):
                    print(f"    Available decimal_value: {balance.available_amount.decimal_value}")
                if hasattr(balance.available_amount, 'value'):
                    print(f"    Available value: {balance.available_amount.value}")
                if hasattr(balance.available_amount, 'currency'):
                    print(f"    Available currency: {balance.available_amount.currency}")
            else:
                print(f"    ❌ No available_amount or it's None")
                
            # Check pending amount
            print(f"    Pending amount object: {balance.pending_amount}")
            print(f"    Pending amount type: {type(balance.pending_amount)}")
            
            if hasattr(balance, 'pending_amount') and balance.pending_amount:
                if hasattr(balance.pending_amount, 'decimal_value'):
                    print(f"    Pending decimal_value: {balance.pending_amount.decimal_value}")
                if hasattr(balance.pending_amount, 'value'):
                    print(f"    Pending value: {balance.pending_amount.value}")
            else:
                print(f"    ❌ No pending_amount or it's None")
            print()
        
        # Step 4: Compare results
        print("4. COMPARISON ANALYSIS")
        print("-" * 30)
        
        if len(raw_balances) != len(client_balances):
            print(f"⚠️  Balance count mismatch: Raw={len(raw_balances)}, Client={len(client_balances)}")
        else:
            print(f"✅ Balance count matches: {len(raw_balances)}")
            
        # Compare each balance
        for i in range(min(len(raw_balances), len(client_balances))):
            raw_bal = raw_balances[i]
            client_bal = client_balances[i]
            
            print(f"\n  Comparing Balance {i+1}:")
            print(f"    ID match: {raw_bal.get('id') == client_bal.id}")
            print(f"    Currency match: {raw_bal.get('currency') == client_bal.currency}")
            
            # Compare available amounts
            raw_available = raw_bal.get('availableAmount', {})
            if raw_available and client_bal.available_amount:
                raw_value = raw_available.get('value', '0')
                if hasattr(client_bal.available_amount, 'value'):
                    client_value = client_bal.available_amount.value
                    print(f"    Available amount: Raw={raw_value}, Client={client_value}, Match={raw_value == client_value}")
                else:
                    print(f"    ❌ Client available_amount has no 'value' attribute")
            else:
                print(f"    Available amount: Raw has data={bool(raw_available)}, Client has data={bool(client_bal.available_amount)}")
                
        # Step 5: Test dashboard calculation
        print("\n5. DASHBOARD CALCULATION TEST")
        print("-" * 30)
        
        from verenigingen.verenigingen_payments.dashboards.financial_dashboard import FinancialDashboard
        
        dashboard = FinancialDashboard()
        balance_overview = dashboard._get_balance_overview()
        
        print(f"Dashboard balance overview:")
        print(json.dumps(balance_overview, indent=2, default=str))
        
        print("\n" + "="*60)
        print("DEBUG COMPLETE")
        print("="*60)
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        frappe.destroy()

if __name__ == '__main__':
    debug_mollie_implementation()