from django import template
from users.services import can

register = template.Library()

@register.filter(name='has_capability')
def has_capability(user, capability_name):
    return can(user, capability_name)
