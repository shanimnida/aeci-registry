"""Template access to the reader's chosen name order.

`{% person_name person %}` writes a name the way this user reads lists --
surname first by default, spoken order if they have switched (see
people/naming.py). It takes the request from the template context rather
than making every view pass an `order` down, which is the difference
between one line per template and a parameter threaded through six view
functions.

Use it for a name in a COLUMN. A name inside a sentence stays
`{{ person.full_name }}`, because a sentence reads in the spoken order.
"""

from django import template

from people.naming import display_name, name_order, short_display_name

register = template.Library()


@register.simple_tag(takes_context=True)
def person_name(context, person):
    return display_name(person, name_order(context.get("request")))


@register.simple_tag(takes_context=True)
def person_short_name(context, person):
    """First and last only, plus a nickname -- the roster form."""
    return short_display_name(person, name_order(context.get("request")))
