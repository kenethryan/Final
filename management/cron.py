import logging
from django.core.management import call_command
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from management.models import DevicePosition

logger = logging.getLogger(__name__)

def update_positions():
    """Update positions for all units with devices every 5 minutes"""
    try:
        logger.info("Running scheduled position update")
        call_command('update_positions')
        logger.info("Position update completed")
    except Exception as e:
        logger.error(f"Error in scheduled position update: {str(e)}", exc_info=True)

def delete_old_positions():
    """Delete DevicePosition records older than 6 months"""
    cutoff_date = timezone.now() - timedelta(days=180)
    old_count = DevicePosition.objects.filter(timestamp__lt=cutoff_date).count()
    DevicePosition.objects.filter(timestamp__lt=cutoff_date).delete()
    logger.info(f"Deleted {old_count} DevicePosition records older than 6 months.")

# To use this with a scheduler like django-crontab, add to settings.py:
# CRONJOBS = [
#     ('*/5 * * * *', 'management.cron.update_positions', '>> /tmp/position_updates.log'),
#     ('0 3 * * *', 'management.cron.delete_old_positions', '>> /tmp/delete_old_positions.log'),
# ]
#
# And install django-crontab:
# pip install django-crontab
#
# Then run:
# python manage.py crontab add 