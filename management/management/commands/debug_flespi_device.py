from django.core.management.base import BaseCommand
from django.conf import settings
import requests
import json
import time

class Command(BaseCommand):
    help = 'Direct debugging of Flespi API device operations'

    def add_arguments(self, parser):
        parser.add_argument('--imei', type=str, help='Test IMEI to use')

    def handle(self, *args, **options):
        self.stdout.write("==== Flespi API Direct Debug Tool ====")
        
        # Use the token from settings
        token = settings.FLESPI_TOKEN
        if not token:
            self.stdout.write(self.style.ERROR("No Flespi API token configured"))
            return
            
        self.stdout.write(f"Using token: {token[:4]}...{token[-4:]}")
        
        # Set up the headers
        headers = {
            "Authorization": f"FlespiToken {token}",
            "Content-Type": "application/json"
        }
        
        # Try all the base URL patterns
        base_urls = [
            "https://flespi.io/gw",
            "https://flespi.io",
            "https://flespi.io/api",
            "https://api.flespi.io"
        ]
        
        # Test device endpoints
        for base_url in base_urls:
            self.stdout.write(f"\nTrying base URL: {base_url}")
            
            # Test getting devices
            devices_url = f"{base_url}/devices/all"
            self.stdout.write(f"- Testing GET {devices_url}")
            try:
                resp = requests.get(devices_url, headers=headers, timeout=10)
                self.stdout.write(f"  Status: {resp.status_code}")
                
                if resp.status_code == 200:
                    data = resp.json()
                    self.stdout.write(self.style.SUCCESS(f"  SUCCESS! Found devices endpoint"))
                    self.stdout.write(f"  Found {len(data.get('result', []))} devices")
                    
                    # If successful, try to create a device
                    imei = options.get('imei', f"999{int(time.time())%10000}")
                    self.create_test_device(base_url, imei, headers)
                    
                    # Try to get device telemetry
                    self.test_device_telemetry(base_url, headers)
                    
                    # We found a working endpoint, so exit early
                    break
                else:
                    self.stdout.write(f"  Response: {resp.text[:200]}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error: {str(e)}"))
                
        # Final recommendations
        self.stdout.write("\nRecommendations:")
        self.stdout.write("1. Check that your Flespi token is valid and has the correct permissions")
        self.stdout.write("2. Verify network connectivity to the Flespi API server")
        self.stdout.write("3. Review Flespi documentation for current API endpoints")
        
    def create_test_device(self, base_url, imei, headers):
        """Try to create a test device"""
        self.stdout.write(f"\nTesting device creation with IMEI: {imei}")
        
        # Try different create device endpoints
        endpoints = [
            f"{base_url}/devices",
            f"{base_url}/devices/create"
        ]
        
        for url in endpoints:
            self.stdout.write(f"- Testing POST {url}")
            
            payload = [{
                "name": f"Test Device {imei}",
                "device_type_id": 871,  # Default GPS tracker device type
                "configuration": {
                    "ident": imei
                }
            }]
            
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=10)
                self.stdout.write(f"  Status: {resp.status_code}")
                
                if resp.status_code in (200, 201):
                    self.stdout.write(self.style.SUCCESS(f"  SUCCESS! Device creation endpoint works"))
                    result = resp.json().get('result', [])
                    if result:
                        device_id = result[0].get('id')
                        self.stdout.write(f"  Created device ID: {device_id}")
                    else:
                        self.stdout.write(f"  No result in response: {resp.text[:200]}")
                    
                    # Found working endpoint, so exit early
                    return True
                else:
                    self.stdout.write(f"  Response: {resp.text[:200]}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error: {str(e)}"))
                
        return False
        
    def test_device_telemetry(self, base_url, headers):
        """Test device telemetry endpoints"""
        self.stdout.write("\nTesting device telemetry endpoints")
        
        # First get all devices to find one to test with
        try:
            devices_url = f"{base_url}/devices/all"
            resp = requests.get(devices_url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                devices = resp.json().get('result', [])
                if not devices:
                    self.stdout.write("No devices found to test telemetry")
                    return
                    
                # Get the first device ID
                device_id = devices[0].get('id')
                self.stdout.write(f"Testing telemetry for device ID: {device_id}")
                
                # Try direct device retrieval first to see if it has last_message field
                device_url = f"{base_url}/devices/{device_id}"
                self.stdout.write(f"- Testing GET {device_url}")
                try:
                    device_resp = requests.get(device_url, headers=headers, timeout=10)
                    self.stdout.write(f"  Status: {device_resp.status_code}")
                    
                    if device_resp.status_code == 200:
                        self.stdout.write(self.style.SUCCESS(f"  SUCCESS! Device info endpoint works"))
                        device_data = device_resp.json().get('result', [{}])[0]
                        
                        # Check if the device has a last_message field
                        if 'last_message' in device_data:
                            self.stdout.write(self.style.SUCCESS(f"  SUCCESS! Device has last_message field with telemetry"))
                            last_message = device_data.get('last_message', {})
                            
                            # Check for position data
                            if 'position' in last_message:
                                self.stdout.write(self.style.SUCCESS(f"  SUCCESS! Device has position data"))
                                position = last_message.get('position', {})
                                self.stdout.write(f"  Position: {position}")
                            else:
                                self.stdout.write(f"  No position data in last_message: {last_message}")
                        else:
                            self.stdout.write(f"  No last_message field in device data: {list(device_data.keys())}")
                    else:
                        self.stdout.write(f"  Response: {device_resp.text[:200]}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  Error: {str(e)}"))
                
                # Try different telemetry endpoints
                endpoints = [
                    f"{base_url}/devices/{device_id}/telemetry",
                    f"{base_url}/devices/all/telemetry",
                    f"{base_url}/telemetry/devices/{device_id}",
                    f"{base_url}/telemetry/devices/all"
                ]
                
                for url in endpoints:
                    self.stdout.write(f"- Testing GET {url}")
                    
                    try:
                        telemetry_resp = requests.get(url, headers=headers, timeout=10)
                        self.stdout.write(f"  Status: {telemetry_resp.status_code}")
                        
                        if telemetry_resp.status_code == 200:
                            self.stdout.write(self.style.SUCCESS(f"  SUCCESS! Telemetry endpoint works"))
                            result = telemetry_resp.json().get('result', {})
                            if result:
                                self.stdout.write(f"  Found telemetry data")
                                # Display a few telemetry fields as examples
                                if isinstance(result, dict):
                                    keys = list(result.keys())[:5]
                                    self.stdout.write(f"  Sample fields: {', '.join(keys)}")
                            else:
                                self.stdout.write(f"  No telemetry data in response")
                        else:
                            self.stdout.write(f"  Response: {telemetry_resp.text[:200]}")
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"  Error: {str(e)}"))
            else:
                self.stdout.write(f"Could not get devices to test telemetry: {resp.status_code}")
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error testing telemetry: {str(e)}")) 