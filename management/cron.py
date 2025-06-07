import logging
from django.core.management import call_command
from django.conf import settings

logger = logging.getLogger(__name__)

def update_positions():
    """Update positions for all units with devices every 5 minutes"""
    try:
        logger.info("Running scheduled position update")
        call_command('update_positions')
        logger.info("Position update completed")
    except Exception as e:
        logger.error(f"Error in scheduled position update: {str(e)}", exc_info=True)

# To use this with a scheduler like django-crontab, add to settings.py:
# CRONJOBS = [
#     ('*/5 * * * *', 'management.cron.update_positions', '>> /tmp/position_updates.log')
# ]
#
# And install django-crontab:
# pip install django-crontab
#
# Then run:
# python manage.py crontab add 