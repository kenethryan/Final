import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from management.models import Unit

class Command(BaseCommand):
    help = 'Map Sinotrack device IMEI (unit_PO) to Flespi device ID and update units'

    def handle(self, *args, **options):
        # Fetch all devices from Flespi
        url = 'https://flespi.io/gw/devices/all'
        headers = {
            'Authorization': f'FlespiToken {settings.FLESPI_TOKEN}',
            'Content-Type': 'application/json'
        }
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        devices = resp.json().get('result', [])

        # Build a mapping: IMEI (ident) -> flespi device id
        imei_to_flespi = {}
        for dev in devices:
            imei = str(dev.get('ident'))
            flespi_id = str(dev['id'])
            if imei:
                imei_to_flespi[imei] = flespi_id

        updated = 0
        for unit in Unit.objects.all():
            imei = str(unit.unit_PO)
            flespi_id = imei_to_flespi.get(imei)
            if flespi_id and unit.flespi_device_id != flespi_id:
                unit.flespi_device_id = flespi_id
                unit.save()
                updated += 1
                self.stdout.write(self.style.SUCCESS(f'Updated unit {unit.unit_PO}: flespi_device_id={flespi_id}'))
        self.stdout.write(self.style.SUCCESS(f'Updated {updated} units.')) 