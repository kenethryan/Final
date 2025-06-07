from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Fix database schema issues by adding missing columns'

    def handle(self, *args, **options):
        # Create a cursor object
        cursor = connection.cursor()
        
        # Helper method to safely add columns
        def safe_add_column(table, column, definition):
            try:
                # Check if column exists
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = %s AND column_name = %s",
                    [table, column]
                )
                if cursor.fetchone()[0] > 0:
                    self.stdout.write(self.style.WARNING(f"Column {column} already exists in {table}"))
                    return
                
                # Add the column
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                self.stdout.write(self.style.SUCCESS(f"Successfully added column {column} to {table}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error adding column {column} to {table}: {e}"))
        
        # Add missing columns
        safe_add_column('management_unit', 'device_imei', 'VARCHAR(100) NULL')
        safe_add_column('management_unit', 'flespi_device_id', 'VARCHAR(100) NULL')
        
        # Create DevicePosition table if it doesn't exist
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = %s",
                ['management_deviceposition']
            )
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                CREATE TABLE management_deviceposition (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    latitude FLOAT NOT NULL,
                    longitude FLOAT NOT NULL,
                    speed FLOAT NOT NULL DEFAULT 0,
                    timestamp DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    unit_id BIGINT NOT NULL,
                    FOREIGN KEY (unit_id) REFERENCES management_unit(id)
                )
                """)
                cursor.execute("""
                CREATE INDEX management__unit_id_0aa5d8_idx 
                ON management_deviceposition (unit_id, timestamp DESC)
                """)
                self.stdout.write(self.style.SUCCESS("Successfully created DevicePosition table"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating DevicePosition table: {e}"))
            
        self.stdout.write(self.style.SUCCESS("Schema fix operation completed")) 