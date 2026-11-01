"""Collaborators: the brand's name in emails, styled as its logo."""

from django.template.loader import render_to_string

from core.templatetags.extra_tags import wordmark

UPRIGHT = '<span style="font-style:normal;">✍️</span>'


def test_wordmark_letters_bold_italic_emojis_upright():
    """The letters are bold italic on one row; the emojis are never italic."""
    html = wordmark("CO✍️✍️ABORATORS")

    assert html == (
        '<span style="font-weight:800;font-style:italic;color:#4747A3;'
        f'white-space:nowrap;">CO{UPRIGHT}{UPRIGHT}ABORATORS</span>'
    )


def test_wordmark_escapes_the_name():
    """The configured name is text, never markup."""
    assert "&lt;b&gt;" in wordmark("<b>✍️")


def _context(**extra):
    return {
        "title": "Hello",
        "message": "A message",
        "link": "https://example.com",
        "link_label": "",
        "button_label": "Open",
        **extra,
    }


def test_email_tagline_opens_with_the_logo():
    """
    The tagline opens with the brand's name in its logo's style, and the
    emails no longer end with "Brought to you by".
    """
    html = render_to_string(
        "mail/html/template.html", _context(brandname="CO✍️✍️ABORATORS")
    )
    text = render_to_string(
        "mail/text/template.txt", _context(brandname="CO✍️✍️ABORATORS")
    )

    styled = wordmark("CO✍️✍️ABORATORS")
    assert html.count(styled) == 2  # atop the email and in the tagline
    assert f"{styled}, where teams organize and share knowledge together." in html
    assert (
        "CO✍️✍️ABORATORS, where teams organize and share knowledge together."
        in " ".join(text.split())
    )
    assert "Brought to you by" not in html
    assert "Brought to you by" not in text
    assert "font-weight:800" not in text


def test_email_tagline_without_a_brand_name():
    """With no brand name configured, the tagline still names the platform."""
    html = render_to_string("mail/html/template.html", _context(brandname=None))

    assert (
        f"{wordmark('CO✍️✍️ABORATORS')}, where teams organize and "
        "share knowledge together." in html
    )
