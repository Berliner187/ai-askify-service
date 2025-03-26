from django import template
import json

register = template.Library()


@register.filter
def get_attribute(obj, attr):
    return getattr(obj, attr, None)


@register.filter
def is_dict(value):
    return isinstance(value, dict)


@register.filter
def pretty_json(value):
    try:
        return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
    except:
        return value
