from django.core.management.base import BaseCommand
from django.db.models import Q
from management.models import Unit
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Clears mock device IDs from all units to prepare for real Flespi API integration'

    def handle(self, *args, **options):
        # Find all units with mock device IDs
        mock_units = Unit.objects.filter(
            Q(flespi_device_id__startswith='mock-') | 
            Q(flespi_device_id__startswith='10000')
        )
        
        count = mock_units.count()
        self.stdout.write(f"Found {count} units with mock device IDs")
        
        if count > 0:
            # Ask for confirmation
            confirm = input(f"Are you sure you want to clear {count} mock device IDs? [y/N]: ")
            
            if confirm.lower() == 'y':
                # Clear the mock IDs
                for unit in mock_units:
                    old_id = unit.flespi_device_id
                    unit.flespi_device_id = None
                    unit.save(update_fields=['flespi_device_id'])
                    logger.info(f"Cleared mock device ID {old_id} from unit {unit.unit_PO}")
                    self.stdout.write(f"Cleared mock ID {old_id} from unit {unit.unit_PO}")
                
                self.stdout.write(self.style.SUCCESS(f"Successfully cleared {count} mock device IDs"))
                self.stdout.write(self.style.SUCCESS("You can now assign real IMEIs to your units"))
            else:
                self.stdout.write("Operation cancelled")
        else:
            self.stdout.write("No mock device IDs found") 