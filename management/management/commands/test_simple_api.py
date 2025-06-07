from django.core.management.base import BaseCommand
from django.conf import settings
import requests
import json

class Command(BaseCommand):
    help = 'Simple direct test of Flespi API'

    def handle(self, *args, **options):
        self.stdout.write("== Simple Flespi API Test ==")
        
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
        
        # Test endpoints
        base_url = "https://flespi.io/gw"
        
        # 1. Test listing devices
        devices_url = f"{base_url}/devices/all"
        self.stdout.write(f"1. Testing GET {devices_url}")
        
        try:
            resp = requests.get(devices_url, headers=headers)
            self.stdout.write(f"Status: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                devices = data.get('result', [])
                self.stdout.write(f"Found {len(devices)} devices")
                
                if devices:
                    device = devices[0]
                    device_id = device.get('id')
                    self.stdout.write(f"First device ID: {device_id}")
                    self.stdout.write(f"Device info: {json.dumps(device, indent=2)}")
                    
                    # 2. Test getting a specific device
                    device_url = f"{base_url}/devices/{device_id}"
                    self.stdout.write(f"\n2. Testing GET {device_url}")
                    
                    try:
                        device_resp = requests.get(device_url, headers=headers)
                        self.stdout.write(f"Status: {device_resp.status_code}")
                        
                        if device_resp.status_code == 200:
                            device_data = device_resp.json().get('result', [{}])[0]
                            self.stdout.write(f"Device fields: {', '.join(device_data.keys())}")
                            
                            # Check for last_message
                            if 'last_message' in device_data:
                                last_message = device_data.get('last_message', {})
                                self.stdout.write(f"Last message fields: {', '.join(last_message.keys())}")
                                
                                # Check for position
                                if 'position' in last_message:
                                    position = last_message.get('position', {})
                                    self.stdout.write(f"Position: {position}")
                            else:
                                self.stdout.write("No last_message field found")
                        else:
                            self.stdout.write(f"Response: {device_resp.text}")
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Error: {str(e)}"))
            else:
                self.stdout.write(f"Response: {resp.text}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {str(e)}"))
            
        # Test creating a device
        self.stdout.write("\n3. Testing device creation")
        create_url = f"{base_url}/devices"
        
        payload = [{
            "name": "Test Device",
            "device_type_id": 871,
            "configuration": {
                "ident": "123456789012346"  # Use a new IMEI
            }
        }]
        
        try:
            resp = requests.post(create_url, headers=headers, json=payload)
            self.stdout.write(f"Status: {resp.status_code}")
            self.stdout.write(f"Response: {resp.text}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {str(e)}"))
            
        self.stdout.write("\nTest completed") 