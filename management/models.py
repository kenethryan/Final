from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.files.storage import FileSystemStorage

User = get_user_model()

class Driver(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('on_leave', 'On Leave'),
        ('fired', 'Fired'),
    ]

    driver_PD = models.CharField(max_length=100, unique=True)
    contact_number = models.CharField(max_length=15)
    savings = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    debt = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    driver_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    profile_picture = models.ImageField(
        upload_to='driver_profiles/',
        null=True,
        blank=True,
        storage=FileSystemStorage(location='media/'),
        default='profile1.png'
    )

    class Meta:
        ordering = ['driver_name']

    def __str__(self):
        return f"{self.driver_name} ({self.driver_PD})"




class DamagePart(models.Model):
    part_name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['part_name']

    def __str__(self):
        return self.part_name


class Unit(models.Model):
    STATUS_CHOICES = [
        ('stand_by', 'Stand By'),
        ('in_use', 'In Use'),
        ('under_maintenance', 'Under Maintenance'),
        ('out_of_service', 'Out of Service'),
    ]

    unit_PO = models.CharField(max_length=100, unique=True)
    unit_made = models.DateField()
    unit_model = models.CharField(max_length=100, blank=True, null=True)
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_units'
    )
    device_imei = models.CharField(max_length=100, null=True, blank=True, help_text="Device IMEI number")
    flespi_device_id = models.CharField(max_length=100, null=True, blank=True)
    previous_status = models.CharField(max_length=20, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='stand_by')
    damage_parts = models.ManyToManyField(DamagePart, blank=True, related_name='units_with_damage')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['unit_PO']

    def __str__(self):
        return f"{self.unit_PO} ({self.get_status_display()})"


class Remittance(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='unit_remittances')
    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='driver_remittances'
    )
    remit_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    savings_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, null=True, blank=True)
    date = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False)
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.driver and self.unit.driver:
            # Capture driver info before clearing
            self.driver = self.unit.driver
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Remittance #{self.id} - {self.unit.unit_PO} ({self.date})"

    def save(self, *args, **kwargs):
        if not self.driver and self.unit:
            if self.unit.driver and self.unit.driver == self:
                self.driver = self.unit.driver

        super().save(*args, **kwargs)


class DamageReport(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='damage_reports')
    description = models.TextField()
    reported_date = models.DateTimeField(auto_now_add=True)
    is_fixed = models.BooleanField(default=False)
    previous_status = models.CharField(max_length=20, choices=Unit.STATUS_CHOICES)
    fixed_date = models.DateTimeField(null=True, blank=True)


class RemittanceAmount(models.Model):
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=200.00)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        verbose_name = "Remittance Amount"
        verbose_name_plural = "Remittance Amount"

    def __str__(self):
        return f"₱{self.amount}"

class DevicePosition(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='positions')
    latitude = models.FloatField()
    longitude = models.FloatField()
    speed = models.FloatField(default=0)
    timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['unit', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.unit.unit_PO} at {self.timestamp}"

class Location(models.Model):
    latitude = models.FloatField()
    longitude = models.FloatField()
    speed = models.FloatField(null=True, blank=True)
    timestamp = models.DateTimeField()