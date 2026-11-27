"""The QR code of "iPhone oder iPad verbinden" as SVG, as nexnotes, nextasks, nexlore and nexmail draw it: dark on
white with a quiet zone (readable on a dark page too), with a ``viewBox`` so that it scales (``omitsize``: with fixed
sizes segno writes none, and an image set to 200 px cuts the code off instead of scaling it).

The only part of the module that needs ``segno``; it is imported when a code is drawn."""

from __future__ import annotations

import io


def svg(link: str) -> str:
    import segno

    out = io.BytesIO()
    segno.make(link, error="m").save(
        out, kind="svg", scale=4, dark="#14141a", light="#ffffff", border=4, xmldecl=False, svgns=True, omitsize=True
    )
    return out.getvalue().decode("utf-8")
