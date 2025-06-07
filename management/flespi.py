import requests
import logging
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from time import time as now_unix
import random
import math

logger = logging.getLogger(__name__)

class FlespiAPI:
    # Base URL for Flespi API endpoints
    BASE_URL = "https://flespi.io/gw"
    
    def __init__(self, token):
        self.token = token
        self.headers = {
            "Authorization": f"FlespiToken {token}",
            "Content-Type": "application/json"
        }
        
    def _verify_connection(self):
        """Verify API connectivity and token validity"""
        logger.info(f"_verify_connection: Testing connection to Flespi API at {self.BASE_URL}")
            
        try:
            # Try to access a simple endpoint to verify connectivity
            test_url = f"{self.BASE_URL}/devices/all"
            logger.info(f"Testing Flespi API connection: {test_url}")
            resp = requests.get(test_url, headers=self.headers, timeout=10)
            logger.info(f"API response status: {resp.status_code}")
            
            if resp.status_code in (200, 201):
                logger.info("_verify_connection: API connection successful")
                return True
            else:
                # Log detailed error information
                if resp.status_code == 401:
                    error_msg = "Authentication failed. Check your API token."
                elif resp.status_code == 404:
                    error_msg = "API endpoint not found. Check if the API URL is correct or if the API has changed."
                elif resp.status_code == 403:
                    error_msg = "Access forbidden. Check your API token permissions."
                else:
                    error_msg = f"Unknown error"
                    
                logger.error(f"_verify_connection: Failed with status {resp.status_code} - {error_msg}. Response: {resp.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("_verify_connection: Connection timeout - API server is not responding")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("_verify_connection: Connection error - check network connectivity and API URL")
            return False
        except Exception as e:
            logger.error(f"_verify_connection: Unexpected error: {str(e)}")
            return False
            
    def get_device_by_imei(self, imei):
        """Find a device with the specified IMEI
        
        Args:
            imei (str): IMEI to search for
            
        Returns:
            dict: Device info or None if not found
        """
        url = f"{self.BASE_URL}/devices/all"  # Use devices/all endpoint
        
        logger.info(f"Searching for device with IMEI {imei} at URL: {url}")
        
        try:
            resp = requests.get(url, headers=self.headers)
            logger.info(f"Flespi device search response status: {resp.status_code}")
            
            if resp.status_code != 200:
                logger.error(f"Flespi device search error: {resp.text}")
                return None
                
            result = resp.json().get('result', [])
            if not result:
                logger.warning(f"No devices found in Flespi")
                return None

            # We need to manually filter for devices with this IMEI
            # Log some debug info to help diagnose
            logger.info(f"Filtering {len(result)} devices by IMEI {imei}")
            
            for device in result:
                # The IMEI is stored in the configuration.ident field
                device_imei = device.get('configuration', {}).get('ident')
                device_id = device.get('id')
                device_name = device.get('name', 'Unknown')
                
                logger.debug(f"Checking device {device_id} ({device_name}) with IMEI: {device_imei}")
                
                if device_imei == imei:
                    logger.info(f"Found device with IMEI {imei}: {device_id} ({device_name})")
                    return device
                    
            logger.warning(f"No device found with IMEI {imei}")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for device with IMEI {imei}: {str(e)}")
            return None
    
    def create_device(self, name, imei, device_type=871):
        """Create a new device in Flespi using IMEI"""
        # First check if a device with this IMEI already exists
        existing_device = self.get_device_by_imei(imei)
        if existing_device:
            device_id = existing_device.get('id')
            logger.info(f"Device with IMEI {imei} already exists with ID {device_id}")
            return device_id
            
        # Create a new device
        url = f"{self.BASE_URL}/devices"
        
        # Using the correct payload format from our tests
        payload = [{
            "name": name,
            "device_type_id": device_type,
            "configuration": {"ident": imei}
        }]
        
        logger.info(f"Creating Flespi device with name '{name}' and IMEI '{imei}' at URL: {url}")
        logger.info(f"API Request payload: {payload}")
        
        try:
            resp = requests.post(url, headers=self.headers, json=payload)
            logger.info(f"Flespi create device response status: {resp.status_code}")
            
            # Handle various response codes
            if resp.status_code == 200:
                # Success
                result = resp.json().get('result', [])
                if not result:
                    logger.error(f"No result in create device response: {resp.text}")
                    return None
                    
                logger.info(f"Device created successfully with result: {result}")
                device_id = result[0].get('id')
                logger.info(f"Created device with ID: {device_id}")
                return device_id
                
            elif resp.status_code == 400:
                # Check if the error is because the device already exists
                error_msg = resp.text
                logger.warning(f"400 Bad Request: {error_msg}")
                
                if "already exists" in error_msg:
                    # Try again to find the device
                    logger.info(f"Device with IMEI {imei} might already exist - searching again")
                    existing_device = self.get_device_by_imei(imei)
                    if existing_device:
                        device_id = existing_device.get('id')
                        logger.info(f"Found existing device with IMEI {imei}: {device_id}")
                        return device_id
                        
            elif resp.status_code == 401:
                logger.error("Authentication failed. Check your API token.")
            elif resp.status_code == 404:
                logger.error("API endpoint not found. Check the BASE_URL value.")
            else:
                logger.error(f"Unexpected status code: {resp.status_code}")
                
            logger.error(f"Flespi create device error: {resp.text}")
            return None
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error when creating device: {e}")
            return None
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout error when creating device: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating device: {str(e)}")
            return None
    
    def ensure_device_exists(self, unit):
        """Ensure a device exists in Flespi for the given unit"""
        logger.info(f"ensure_device_exists: Working with real API for unit {unit.id} with IMEI {unit.device_imei}")
        
        # Debug information about API configuration
        logger.info(f"Base URL: {self.BASE_URL}, Token: {self.token[:4]}...{self.token[-4:] if len(self.token) > 8 else '****'}")
        
        # Check connection before proceeding
        if not self._verify_connection():
            logger.error(f"Cannot ensure device exists: API connection failed. Check your API token and network connectivity.")
            return None
        
        if not unit.device_imei:
            logger.error(f"Cannot ensure device exists: Unit has no device IMEI")
            return None
            
        # First check if we already have a Flespi device ID
        if unit.flespi_device_id:
            # Verify the device still exists in Flespi
            try:
                logger.info(f"Checking if device {unit.flespi_device_id} still exists in Flespi")
                url = f"{self.BASE_URL}/devices/{unit.flespi_device_id}"
                resp = requests.get(url, headers=self.headers)
                if resp.status_code == 200:
                    logger.info(f"Device {unit.flespi_device_id} exists in Flespi")
                    return unit.flespi_device_id
                else:
                    logger.warning(f"Device {unit.flespi_device_id} not found in Flespi (status code: {resp.status_code})")
            except Exception as e:
                logger.warning(f"Exception when checking existing device: {str(e)}")
                # If there's an error, we'll try to find or create the device
        
        # Try to find the device by IMEI
        logger.info(f"Searching for device with IMEI {unit.device_imei}")
        device = self.get_device_by_imei(unit.device_imei)
        if device:
            device_id = device.get('id')
            logger.info(f"Found existing device with IMEI {unit.device_imei}: ID = {device_id}")
            unit.flespi_device_id = device_id
            unit.save()
            return device_id
        
        # Device not found, create it
        logger.info(f"No device found with IMEI {unit.device_imei}, creating a new one")
        device_name = f"Unit {unit.unit_PO or ''} (ID: {unit.id})"
        
        # Get device type for GPS trackers
        device_type_id = 871  # Default GPS tracker type ID
        
        # Try to create the device
        device_id = self.create_device(device_name, unit.device_imei, device_type_id)
        
        if device_id:
            logger.info(f"Successfully created device with ID {device_id}")
            unit.flespi_device_id = device_id
            unit.save()
            return device_id
        else:
            logger.error(f"Failed to create device for IMEI {unit.device_imei}")
        
        logger.error("No device ID could be found or created")
        return None
    
    def get_device_position(self, device_id):
        """Get the latest position for a specific device ID from Flespi"""
        if not self._verify_connection():
            logger.error(f"Cannot get device position: API connection failed")
            return None
            
        url = f"{self.BASE_URL}/devices/{device_id}/messages"
        params = {"limit": 1, "sort": "timestamp,desc"}
        
        try:
            resp = requests.get(url, params=params, headers=self.headers)
            resp.raise_for_status()
            result = resp.json().get('result', [])
            
            if not result:
                return None
                
            # Get the latest message
            msg = result[0]
            
            # Extract relevant position data
            timestamp = msg.get('timestamp')
            
            # Extract all available position data
            position = {
                'latitude': msg.get('position.latitude'),
                'longitude': msg.get('position.longitude'),
                'speed': msg.get('position.speed'),
                'timestamp': timestamp,
                'direction': msg.get('position.direction'),
                'altitude': msg.get('position.altitude'),
                'hdop': msg.get('position.hdop'),
                'satellites': msg.get('position.satellites'),
                'valid': msg.get('position.valid', True),
            }
            
            return position
            
        except Exception as e:
            logger.warning(f"Flespi API error getting device position: {e}")
            
            return None
        
    def get_device_telemetry(self, device_id):
        """Get telemetry for a specific device"""
        logger.info(f"get_device_telemetry: Getting telemetry for device {device_id}")
        
        try:
            # Try the individual device endpoint
            url = f"{self.BASE_URL}/devices/{device_id}"
            logger.debug(f"Fetching device data from {url}")
            
            resp = requests.get(url, headers=self.headers)
            
            if resp.status_code != 200:
                logger.warning(f"Error fetching device data: {resp.status_code}")
                return None
                
            device_data = resp.json().get('result', [{}])[0]
            
            # Check if the device has a last_message field
            if 'last_message' in device_data:
                # Extract the 'last_message' field which contains the most recent telemetry
                last_message = device_data.get('last_message', {})
                
                # Process position data into a simpler format
                result = {}
                
                # Look for position data in the last_message
                if 'position' in last_message:
                    position = last_message.get('position', {})
                    result['latitude'] = position.get('latitude')
                    result['longitude'] = position.get('longitude')
                    result['speed'] = position.get('speed')
                    result['direction'] = position.get('direction')
                    result['timestamp'] = last_message.get('timestamp')
                    
                    # Check for battery information
                    if 'battery' in last_message:
                        result['battery'] = last_message.get('battery', {}).get('level')
                        
                    return result
                else:
                    logger.warning(f"No position data found in last_message for device {device_id}")
            else:
                # If no last_message field, no telemetry data available
                logger.warning(f"No last_message field found for device {device_id} - no telemetry data available")
                
            # Since we couldn't get valid telemetry from the API, fallback to mock data
            return None
                
        except Exception as e:
            logger.error(f"Error getting telemetry for device {device_id}: {str(e)}")
            # Fallback to mock data on error
            return None
            
    def get_all_devices_telemetry(self, device_ids=None):
        """Get telemetry data for all or specified devices
        
        Args:
            device_ids (list): List of device IDs to get telemetry for, or None for all
            
        Returns:
            dict: Device ID -> telemetry data mapping
        """
        logger.info(f"get_all_devices_telemetry: Getting telemetry for {len(device_ids) if device_ids else 'all'} devices")
            
        # Based on diagnostics, we found that we need to get telemetry for each device individually
        result = {}
        
        try:
            # Fetch all devices if no specific IDs provided
            if not device_ids:
                try:
                    devices_url = f"{self.BASE_URL}/devices/all"
                    devices_resp = requests.get(devices_url, headers=self.headers)
                    
                    if devices_resp.status_code != 200:
                        logger.error(f"Error fetching devices: {devices_resp.status_code}")
                        return {}
                        
                    devices = devices_resp.json().get('result', [])
                    device_ids = [device.get('id') for device in devices]
                except Exception as e:
                    logger.error(f"Error fetching device list: {str(e)}")
                    return {}
                    
            # Fetch telemetry for each device using the device info endpoint
            for device_id in device_ids:
                try:
                    telemetry = self.get_device_telemetry(device_id)
                    if telemetry:
                        result[device_id] = telemetry
                    
                except Exception as e:
                    logger.error(f"Error processing telemetry for device {device_id}: {str(e)}")
                    continue
            
            return result
            
        except Exception as e:
            logger.error(f"Error in get_all_devices_telemetry: {str(e)}")
            return {}
        
    @classmethod
    def test_connection(cls, token):
        """Test the connection to the Flespi API using the provided token"""
        logger.info(f"Testing Flespi API connection with token: {token[:4]}...{token[-4:] if len(token) > 8 else '****'}")
        
        if not token:
            return {
                'success': False,
                'message': 'No token provided'
            }
            
        # Make a test request
        try:
            logger.info(f"Trying to connect to: {cls.BASE_URL}/devices/all")
            
            headers = {
                'Authorization': f'FlespiToken {token}',
                'Content-Type': 'application/json'
            }
            
            resp = requests.get(f"{cls.BASE_URL}/devices/all", headers=headers, timeout=10)
            logger.info(f"API response status: {resp.status_code}")
            
            if resp.status_code in (200, 201):
                return {
                    'success': True,
                    'message': 'Connected successfully'
                }
            elif resp.status_code == 401:
                logger.error(f"Authentication failed with token: {token[:4]}...")
                return {
                    'success': False,
                    'message': 'Authentication failed - invalid or expired token'
                }
            elif resp.status_code == 404:
                logger.error(f"API endpoint not found: {cls.BASE_URL}/devices/all")
                return {
                    'success': False,
                    'message': 'API endpoint not found - the API URL may have changed'
                }
            else:
                logger.error(f"API returned status code {resp.status_code}")
                return {
                    'success': False,
                    'message': f"API returned status code {resp.status_code}"
                }
                
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {e}")
            return {
                'success': False,
                'message': f"Connection error: {str(e)}"
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"Connection timeout: {e}")
            return {
                'success': False,
                'message': f"Connection timeout: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error connecting to Flespi API: {e}")
            return {
                'success': False,
                'message': f"Error: {str(e)}"
            }

    def diagnose_device_issues(self, imei=None):
        """Diagnose issues with device assignment and creation"""
        results = {
            'api_status': 'unknown',
            'token_valid': False,
            'can_list_devices': False,
            'can_create_devices': False,
            'imei_exists': False,
            'errors': [],
            'suggestions': []
        }
        
        # Step 1: Check token and basic connection
        if not self._verify_connection():
            results['api_status'] = 'connection_failed'
            results['errors'].append('Could not connect to Flespi API. Check network and credentials.')
            results['suggestions'].append('Verify that your Flespi token is correct and not expired.')
            results['suggestions'].append('Check network connectivity to the Flespi API server.')
            return results
            
        results['token_valid'] = True
        
        # Step 2: Check ability to list devices
        try:
            url = f"{self.BASE_URL}/devices/all"
            resp = requests.get(url, headers=self.headers)
            
            if resp.status_code in (200, 201):
                results['can_list_devices'] = True
                results['api_status'] = 'healthy'
                devices = resp.json().get('result', [])
                results['devices_count'] = len(devices)
            else:
                results['errors'].append(f"Could not list devices: Status code {resp.status_code}")
                if resp.status_code == 403:
                    results['suggestions'].append('Your API token does not have permission to list devices.')
        except Exception as e:
            results['errors'].append(f"Error listing devices: {str(e)}")
            
        # Step 3: Check if the IMEI exists already (if provided)
        if imei:
            device = self.get_device_by_imei(imei)
            if device:
                results['imei_exists'] = True
                results['existing_device_id'] = device.get('id')
                results['suggestions'].append(f"IMEI {imei} already exists as device ID {device.get('id')}.")
                
        # Step 4: Test device creation
        if not results['imei_exists'] and imei:
            # Generate a test IMEI that won't conflict with existing ones
            test_imei = f"999{int(now_unix())%10000}"
            try:
                url = f"{self.BASE_URL}/devices"
                payload = [{
                    "name": "Test Device (Diagnostic)",
                    "device_type_id": 871,  # Standard GPS device type
                    "configuration": {"ident": test_imei}
                }]
                
                resp = requests.post(url, headers=self.headers, json=payload)
                
                if resp.status_code in (200, 201):
                    results['can_create_devices'] = True
                    # Try to clean up by deleting the test device
                    try:
                        device_id = resp.json().get('result', [])[0].get('id')
                        requests.delete(f"{self.BASE_URL}/devices/{device_id}", headers=self.headers)
                    except:
                        pass  # Ignore cleanup errors
                else:
                    results['errors'].append(f"Cannot create devices: Status code {resp.status_code}")
                    results['api_status'] = 'limited_permissions'
                    if resp.status_code == 403:
                        results['suggestions'].append('Your API token does not have permission to create devices.')
                    elif resp.status_code == 400:
                        results['suggestions'].append('Bad request when creating device - the API rejected the payload.')
            except Exception as e:
                results['errors'].append(f"Error creating test device: {str(e)}")
                
        # Final status and suggestions
        if not results['errors']:
            if results['can_list_devices'] and results['can_create_devices']:
                results['api_status'] = 'healthy'
                if not results['imei_exists'] and imei:
                    results['suggestions'].append(f"IMEI {imei} doesn't exist yet but can be created.")
            elif results['can_list_devices']:
                results['api_status'] = 'limited_functionality'
                results['suggestions'].append('Your token can only read devices but not create them. You need create permissions for device assignment.')
        else:
            if not results['api_status'] or results['api_status'] == 'unknown':
                results['api_status'] = 'error'
                
        return results

    def get_device_history(self, device_id, hours=24):
        """
        Fetch position history for a device from Flespi messages API.
        Returns a list of messages (dicts) for the last `hours` hours.
        """
        if not self._verify_connection():
            logger.error(f"Cannot get device history: API connection failed")
            return []

        url = f"{self.BASE_URL}/devices/{device_id}/messages"
        from time import time
        min_timestamp = int(time()) - hours * 3600
        params = {
            "timestamp:gte": min_timestamp,
            "sort": "timestamp,asc"
        }
        try:
            resp = requests.get(url, params=params, headers=self.headers)
            resp.raise_for_status()
            return resp.json().get('result', [])
        except Exception as e:
            logger.warning(f"Flespi API error getting device history: {e}")
            return [] 