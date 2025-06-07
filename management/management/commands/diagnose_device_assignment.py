from django.core.management.base import BaseCommand
from django.conf import settings
import requests
import json
import logging
from management.flespi import FlespiAPI
from management.models import Unit

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Diagnose issues with device assignment and Flespi API integration'

    def add_arguments(self, parser):
        parser.add_argument('--unit_id', type=int, help='Specify a unit ID to diagnose')
        parser.add_argument('--imei', type=str, help='Specify an IMEI to check')

    def handle(self, *args, **options):
        self.stdout.write("Running device assignment diagnostics...")
        
        # Check if token is configured
        token = settings.FLESPI_TOKEN
        if not token:
            self.stdout.write(self.style.ERROR("❌ No Flespi API token configured in settings.py"))
            return
            
        self.stdout.write(f"✓ API token found: {token[:4]}...{token[-4:]}")
        self.stdout.write(f"✓ MOCK_MODE is {'ENABLED' if FlespiAPI.MOCK_MODE else 'DISABLED'}")
        
        # Initialize API client
        flespi = FlespiAPI(token)
        
        # Check specific unit if requested
        unit_id = options.get('unit_id')
        imei = options.get('imei')
        
        if unit_id:
            try:
                unit = Unit.objects.get(id=unit_id)
                self.stdout.write(f"\nDiagnosing unit: {unit.unit_PO} (ID: {unit.id})")
                self.stdout.write(f"  IMEI: {unit.device_imei or 'Not set'}")
                self.stdout.write(f"  Flespi Device ID: {unit.flespi_device_id or 'Not set'}")
                
                # If IMEI is set but no device ID, may indicate assignment failure
                if unit.device_imei and not unit.flespi_device_id:
                    self.stdout.write(self.style.WARNING(f"⚠️ Unit has IMEI but no device ID - likely assignment failure"))
                
                # Run diagnostics on the IMEI
                if unit.device_imei:
                    self.diagnose_imei(flespi, unit.device_imei)
                else:
                    self.stdout.write(self.style.WARNING("⚠️ No IMEI to diagnose for this unit"))
            except Unit.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"❌ Unit with ID {unit_id} not found"))
        elif imei:
            self.diagnose_imei(flespi, imei)
        else:
            # Run general diagnostics
            self.general_diagnostics(flespi)
    
    def diagnose_imei(self, flespi, imei):
        """Run diagnostics for a specific IMEI"""
        self.stdout.write(f"\nDiagnosing IMEI: {imei}")
        
        if FlespiAPI.MOCK_MODE:
            self.stdout.write(self.style.WARNING("⚠️ Running in MOCK_MODE - no real API calls will be made"))
            self.stdout.write("   To disable mock mode, edit management/flespi.py and set MOCK_MODE = False")
            return
            
        # Run the diagnostics
        results = flespi.diagnose_device_issues(imei)
        
        # Display results
        self.stdout.write(f"\nAPI Status: {results['api_status']}")
        
        if results['token_valid']:
            self.stdout.write(self.style.SUCCESS("✓ API token is valid"))
        else:
            self.stdout.write(self.style.ERROR("❌ API token is invalid or not accepted"))
            
        if results['can_list_devices']:
            self.stdout.write(self.style.SUCCESS(f"✓ API token can list devices ({results.get('devices_count', 'unknown')} devices found)"))
        else:
            self.stdout.write(self.style.ERROR("❌ API token cannot list devices"))
            
        if results['can_create_devices']:
            self.stdout.write(self.style.SUCCESS("✓ API token can create devices"))
        else:
            self.stdout.write(self.style.ERROR("❌ API token cannot create devices"))
            
        if results['imei_exists']:
            self.stdout.write(self.style.SUCCESS(f"✓ IMEI {imei} exists as device ID {results.get('existing_device_id')}"))
        else:
            self.stdout.write(self.style.WARNING(f"⚠️ IMEI {imei} doesn't exist as a Flespi device"))
            
        # Display errors
        if results['errors']:
            self.stdout.write("\nErrors:")
            for error in results['errors']:
                self.stdout.write(self.style.ERROR(f"  ❌ {error}"))
                
        # Display suggestions
        if results['suggestions']:
            self.stdout.write("\nSuggestions:")
            for suggestion in results['suggestions']:
                self.stdout.write(f"  • {suggestion}")
                
    def general_diagnostics(self, flespi):
        """Run general system diagnostics"""
        self.stdout.write("\nRunning general device assignments diagnostics...")
        
        # Count units with various statuses
        total_units = Unit.objects.count()
        units_with_imei = Unit.objects.exclude(device_imei__isnull=True).exclude(device_imei='').count()
        units_with_device_id = Unit.objects.exclude(flespi_device_id__isnull=True).exclude(flespi_device_id='').count()
        units_with_imei_no_device = Unit.objects.exclude(device_imei__isnull=True).exclude(device_imei='').filter(
            flespi_device_id__isnull=True
        ).count()
        
        self.stdout.write(f"Total units in system: {total_units}")
        self.stdout.write(f"Units with IMEI: {units_with_imei}")
        self.stdout.write(f"Units with Flespi device ID: {units_with_device_id}")
        
        if units_with_imei_no_device > 0:
            self.stdout.write(self.style.WARNING(
                f"⚠️ {units_with_imei_no_device} units have IMEI but no device ID - "
                "these units likely failed during device assignment"
            ))
            
            # List a few examples
            problem_units = Unit.objects.exclude(device_imei__isnull=True).exclude(device_imei='').filter(
                flespi_device_id__isnull=True
            ).order_by('id')[:5]
            
            self.stdout.write("\nExample problem units:")
            for unit in problem_units:
                self.stdout.write(f"  • Unit {unit.unit_PO} (ID: {unit.id}), IMEI: {unit.device_imei}")
                
            # Provide resolution steps
            self.stdout.write("\nTo fix these units, you can:")
            self.stdout.write("  1. Check device assignment logs for errors")
            self.stdout.write("  2. Verify Flespi token has device creation permissions")
            self.stdout.write("  3. Run this command with --unit_id=<id> to diagnose specific units")
            self.stdout.write("  4. Try re-assigning the devices through the admin interface")
        
        # Check mock devices
        mock_units = Unit.objects.filter(flespi_device_id__startswith='mock-').count()
        if mock_units > 0:
            self.stdout.write(self.style.WARNING(
                f"⚠️ {mock_units} units have mock device IDs - these are simulated GPS trackers"
            ))
            
            if not FlespiAPI.MOCK_MODE:
                self.stdout.write(self.style.WARNING(
                    "   You have mock devices but MOCK_MODE is currently disabled. "
                    "These devices won't update until you either:\n"
                    "   1. Re-enable MOCK_MODE to use all simulated data, or\n"
                    "   2. Clear mock devices and assign real GPS tracker IMEIs"
                ))
                
        # Run API diagnostics
        if not FlespiAPI.MOCK_MODE:
            results = flespi.diagnose_device_issues()
            
            if results['api_status'] != 'healthy':
                self.stdout.write(self.style.ERROR(
                    f"❌ API health check shows issues: {results['api_status']}"
                ))
                
                # Display errors and suggestions
                if results['errors']:
                    self.stdout.write("\nErrors:")
                    for error in results['errors']:
                        self.stdout.write(self.style.ERROR(f"  ❌ {error}"))
                        
                if results['suggestions']:
                    self.stdout.write("\nSuggestions:")
                    for suggestion in results['suggestions']:
                        self.stdout.write(f"  • {suggestion}")
            else:
                self.stdout.write(self.style.SUCCESS("✓ Flespi API is healthy and properly configured")) 