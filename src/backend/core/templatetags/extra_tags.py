"""Custom template tags for the core application of Docs."""

import base64
import re

from django import template
from django.contrib.staticfiles import finders
from django.utils.html import format_html, format_html_join

from PIL import ImageFile as PillowImageFile

register = template.Library()

# An emoji, with its optional variation selector (e.g. "✍️" is U+270D U+FE0F)
EMOJI = re.compile(
    "([\u2300-\u23ff\u2600-\u27bf\u2b00-\u2bff\U0001f000-\U0001faff]\ufe0f?)"
)


def image_to_base64(file_or_path, close=False):
    """
    Return the src string of the base64 encoding of an image represented by its path
    or file opened or not.

    Inspired by Django's "get_image_dimensions"
    """
    pil_parser = PillowImageFile.Parser()
    if hasattr(file_or_path, "read"):
        file = file_or_path
        if file.closed and hasattr(file, "open"):
            file_or_path.open()
        file_pos = file.tell()
        file.seek(0)
    else:
        try:
            # pylint: disable=consider-using-with
            file = open(file_or_path, "rb")
        except OSError:
            return ""
        close = True

    try:
        image_data = file.read()
        if not image_data:
            return ""
        pil_parser.feed(image_data)
        if pil_parser.image:
            mime_type = pil_parser.image.get_format_mimetype()
            encoded_string = base64.b64encode(image_data)
            return f"data:{mime_type:s};base64, {encoded_string.decode('utf-8'):s}"
        return ""
    finally:
        if close:
            file.close()
        else:
            file.seek(file_pos)


@register.simple_tag
def base64_static(path):
    """Return a static file into a base64."""
    full_path = finders.find(path)
    if full_path:
        return image_to_base64(full_path, True)
    return ""


@register.filter
def wordmark(name):
    """
    Collaborators: the brand's name in the style of its logo (bold italic
    capitals in indigo), as at the top of HTML emails. Its emojis are never
    italic: they stay upright, as on the platform.
    """
    pieces = (
        (format_html('<span style="font-style:normal;">{}</span>', part),)
        if EMOJI.fullmatch(part)
        else (part,)
        for part in EMOJI.split(str(name))
        if part
    )
    return format_html(
        '<span style="font-weight:800;font-style:italic;color:#4747A3;'
        'white-space:nowrap;">{}</span>',
        format_html_join("", "{}", pieces),
    )
