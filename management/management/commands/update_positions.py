from django.core.management.base import BaseCommand
from django.conf import settings
from management.flespi import FlespiAPI
from management.models import Unit, DevicePosition
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Update positions for all units with devices'

    def handle(self, *args, **options):
        self.stdout.write('Starting position update...')
        
        # Initialize Flespi API
        flespi = FlespiAPI(settings.FLESPI_TOKEN)
        
        # Get all units with device IDs
        units = Unit.objects.exclude(flespi_device_id__isnull=True).exclude(flespi_device_id='')
        
        success_count = 0
        fail_count = 0
        
        # Update positions for each unit
        for unit in units:
            try:
                if flespi.update_unit_positions(unit):
                    success_count += 1
                    self.stdout.write(f"Updated position for unit {unit.unit_PO}")
                else:
                    fail_count += 1
                    self.stdout.write(self.style.WARNING(f"Failed to update position for unit {unit.unit_PO}"))
            except Exception as e:
                fail_count += 1
                self.stdout.write(self.style.ERROR(f"Error updating position for unit {unit.unit_PO}: {str(e)}"))
        
        self.stdout.write(self.style.SUCCESS(
            f'Position update complete. Success: {success_count}, Failed: {fail_count}'
        )) 