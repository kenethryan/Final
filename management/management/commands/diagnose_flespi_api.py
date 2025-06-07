from django.core.management.base import BaseCommand
from django.conf import settings
import requests
import json
import logging
from management.flespi import FlespiAPI

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Run diagnostics on the Flespi API connection and settings'

    def handle(self, *args, **options):
        self.stdout.write("Running Flespi API diagnostics...")
        
        # Check if token is configured
        token = settings.FLESPI_TOKEN
        if not token:
            self.stdout.write(self.style.ERROR("❌ No Flespi API token configured in settings.py"))
            return
            
        self.stdout.write(f"✓ API token found: {token[:4]}...{token[-4:]}")
        
        # Try the test_connection method
        self.stdout.write("\nTesting API connection...")
        result = FlespiAPI.test_connection(token)
        
        if result['success']:
            self.stdout.write(self.style.SUCCESS(f"✓ Connection successful: {result['message']}"))
        else:
            self.stdout.write(self.style.ERROR(f"❌ Connection failed: {result['message']}"))
            
        # Check MOCK_MODE
        self.stdout.write(f"\nMOCK_MODE is currently {'ENABLED' if FlespiAPI.MOCK_MODE else 'DISABLED'}")
        if FlespiAPI.MOCK_MODE:
            self.stdout.write(self.style.WARNING("⚠️ Mock mode is enabled - using simulated data instead of real API"))
            self.stdout.write("   To disable mock mode, edit management/flespi.py and set MOCK_MODE = False")
        
        # Try manual API tests
        self.stdout.write("\nRunning manual API tests:")
        
        # Initialize API client
        api = FlespiAPI(token)
        base_url = api.BASE_URL
        headers = api.headers
        
        # Test endpoints
        self.test_endpoint(f"{base_url}/devices/all", "GET", "List all devices")
        self.test_endpoint(f"{base_url}/devices/all/telemetry", "GET", "Get all devices telemetry")
        self.test_endpoint(f"{base_url}/devices", "POST", "Create device", 
                          json=[{"name": "Test Device", "device_type_id": 123, "configuration": {"ident": "123456789012345"}}])
        
        # Final recommendation
        self.stdout.write("\nDiagnostics complete.")
        if not FlespiAPI.MOCK_MODE:
            self.stdout.write(self.style.SUCCESS(
                "Using real API mode. If you're experiencing issues, consider temporarily enabling "
                "MOCK_MODE in management/flespi.py."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "MOCK_MODE is enabled. You are using simulated data instead of real GPS tracking."
            ))
            
    def test_endpoint(self, url, method, description, **kwargs):
        self.stdout.write(f"  Testing: {description} ({method} {url})...")
        
        try:
            # Get the token from settings
            token = settings.FLESPI_TOKEN
            
            # Set up proper headers with Flespi token
            headers = {
                'Authorization': f'FlespiToken {token}',
                'Content-Type': 'application/json'
            }
            
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(
                    url, 
                    headers=headers, 
                    json=kwargs.get('json', {}),
                    timeout=10
                )
            else:
                self.stdout.write(self.style.ERROR(f"    ❌ Unsupported method: {method}"))
                return
                
            self.stdout.write(f"    Status code: {response.status_code}")
            if response.status_code in (200, 201):
                self.stdout.write(self.style.SUCCESS(f"    ✓ Test passed"))
            else:
                self.stdout.write(self.style.ERROR(f"    ❌ Test failed"))
                self.stdout.write(f"    Response: {response.text[:200]}...")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    ❌ Connection error: {str(e)}")) 