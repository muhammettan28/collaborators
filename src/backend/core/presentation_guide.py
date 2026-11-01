"""
Collaborators: how to make presentations for Collaborators, for AI
assistants (the MCP server's presentation_guide tool, and its tools'
descriptions) and for people (copied from the block, to give to the AI they
make files with); and checks(), what a file misses of it, told back to the
AI that sent it so it can fix it.
"""

import json
import re

from django.utils.translation import gettext as _

CARD_ID = "collaborators-presentation"

GUIDE = """\
# Making presentations for Collaborators

Collaborators shows a presentation in a page from one standalone HTML file
(styles, scripts and pictures inside it, or loaded over https from public
sites such as Google Fonts or cdnjs). Readers click through it there, and
download its PDF. Follow these rules so that both work at their best.

## 1. Send its PDF with it

Make a PDF of the same presentation at the same time, and send both
together (publish_presentation, create_presentation_page or
replace_presentation: `pdf_base64` or `pdf_link`, or `-F pdf=@deck.pdf` with
the upload address). Replace both
together too. "Export to PDF" then gives your PDF, and the block shows it
page by page in its "Slides" tab. Without one, the slides are
photographed instead: the text becomes pictures. An animation's PDF holds
a few of its key moments, one per page.

## 2. One slide per printed page

Give the HTML print rules, so that printing it (and so its PDF) gives
exactly one slide per page, the slide's shape, nothing cut:

```css
@page { size: 1280px 720px; margin: 0; }
@media print {
  .slide { display: flex !important; break-after: page; height: 720px; }
  .controls { display: none; }
}
```

## 3. A presentation card

Say what it is, in a card the block reads (one of the two):

```html
<script type="application/json" id="collaborators-presentation">
{"kind": "slides", "slides": 12}
</script>

<script type="application/json" id="collaborators-presentation">
{"kind": "animation", "seconds": 45}
</script>
```

"slides" is clicked through (arrow keys, clicks): `slides` is how many,
and its PDF must have as many pages. "animation" plays on its own:
`seconds` is how long it lasts.

## 4. Slides move with the arrow keys and clicks

ArrowRight / ArrowLeft (and a click) go to the next / previous slide,
from the first slide shown when the file opens.

## 5. Animations readers can move through

Readers may turn on a time bar under an animation, to pause it and move
forward or back. It works by itself with CSS animations and transitions
and with the Web Animations API (element.animate()), when they play once,
not forever. An animation driven by a script (requestAnimationFrame,
timers, GSAP) must give the time bar a handle:

```js
window.collaboratorsTimeline = {
  duration: 45,                  // seconds
  seek(seconds) { /* show the moment at that second, paused */ },
  play() { /* play on from there */ },
  pause() { /* stop where it is */ },
  get time() { return t; },      // optional: the second it shows now
  get playing() { return on; },  // optional: whether it plays
};
```

Give `time` and `playing` when its clock doesn't start as the file opens
(it waits for its fonts, say), so the time bar shows exactly where it is.
With a handle, let it stop at its end rather than loop: the time bar plays
it once, and its play button starts it again from the beginning.

## 6. What it can't do

It is shown in a sealed frame: no access to the page around it, cookies,
storage or the network but for files from public https addresses. Don't
rely on them, nor on forms or pop-ups.
"""


def card_of(text):
    """The presentation card of an HTML file, None if none, or "invalid"."""
    found = re.search(
        r"<script[^>]*id=[\"']" + CARD_ID + r"[\"'][^>]*>(.*?)</script\s*>",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    if not found:
        return None
    try:
        card = json.loads(found.group(1))
    except ValueError:
        return "invalid"
    return card if isinstance(card, dict) else "invalid"


def checks(text, pdf_pages_count=None, has_pdf=False):
    """
    What an HTML file (and its PDF) misses of GUIDE, for the AI that made
    it to fix, or the person to know; [] when nothing.
    """
    found = []
    card = card_of(text)
    if card is None:
        found.append(
            _(
                'It has no presentation card: add <script type="application/json" '
                'id="{id}">{{"kind": "slides", "slides": 12}}</script> '
                "(see the guide)."
            ).format(id=CARD_ID)
        )
    elif card == "invalid":
        found.append(_("Its presentation card isn't valid JSON."))
    else:
        kind = card.get("kind")
        if kind == "slides" and not isinstance(card.get("slides"), int):
            found.append(_('Its card should say how many slides it has ("slides").'))
        elif kind == "animation" and not isinstance(card.get("seconds"), (int, float)):
            found.append(_('Its card should say how long it lasts ("seconds").'))
        elif kind not in ("slides", "animation"):
            found.append(_('Its card\'s kind must be "slides" or "animation".'))
        if (
            kind == "slides"
            and isinstance(card.get("slides"), int)
            and pdf_pages_count
            and card["slides"] != pdf_pages_count
        ):
            found.append(
                _(
                    "Its card says {slides} slides but its PDF has {pages} pages."
                ).format(slides=card["slides"], pages=pdf_pages_count)
            )
    if "@page" not in text and "@media print" not in text:
        found.append(
            _(
                "It has no print rules (@page, @media print): printed, it may not "
                "give one slide per page, so its PDF may not match its slides."
            )
        )
    if "requestAnimationFrame" in text and "collaboratorsTimeline" not in text:
        found.append(
            _(
                "It animates with a script but gives no handle to the time bar "
                "(window.collaboratorsTimeline): readers can't move through it."
            )
        )
    if not has_pdf:
        found.append(
            _(
                'No PDF came with it: "Export to PDF" will photograph its slides '
                "instead of giving your PDF."
            )
        )
    return found
