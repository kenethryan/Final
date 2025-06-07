from django import template
from django.db.models import Model

register = template.Library()

@register.filter
def get_field_choices(instance, field_name):
    if isinstance(instance, Model):
        field = instance._meta.get_field(field_name)
        return field.choices
    return []

@register.filter
def sum_remit_amount(queryset):
    return sum(unit.remit_amount for unit in queryset if hasattr(unit, 'remit_amount') and unit.remit_amount is not None)

register = template.Library()

@register.filter(name='floatformat')
def floatformat(value, decimals=2):
    """
    Formats a number as a float with the specified number of decimal places.
    """
    return f"{value:.{decimals}}"