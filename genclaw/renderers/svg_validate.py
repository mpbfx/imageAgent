"""Lightweight static validation for free-form SVG source (ADR 0005).

This is the first step of code-as-brush: the LLM writes raw ``<svg>`` source and
we render it. SVG is markup (no JS execution at render time), so a static
allow-list check covers the main risk surface without a full execution sandbox.

SECURITY DEBT (ADR 0005, deliberately deferred): this is NOT a hardened sandbox.
It is a best-effort static filter for a LOCAL, single-machine reproduction whose
input comes from a trusted LLM provider, not anonymous public traffic. It blocks
the obvious vectors (scripts, external references, foreignObject, event
handlers) but is not a security boundary. Do NOT expose this to untrusted input
or deploy publicly before the execution-sandbox ADR is implemented.
"""

from __future__ import annotations

import re

# Tags that may appear in a generated SVG. Anything else is rejected.
_ALLOWED_TAGS = {
    "svg", "g", "defs", "title", "desc", "style",
    "rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
    "text", "tspan", "textpath",
    "lineargradient", "radialgradient", "stop", "pattern", "clippath", "mask",
    "filter", "fegaussianblur", "feoffset", "feblend", "femerge", "femergenode",
    "fecolormatrix", "fecomposite", "feflood", "use", "symbol", "marker",
    # More pure-rendering SVG filter primitives (no script, safe to allow).
    "fedropshadow", "femorphology", "fespecularlighting", "fediffuselighting",
    "fepointlight", "fedistantlight", "fespotlight", "feturbulence",
    "fedisplacementmap", "fetile", "feimage", "fecomponenttransfer",
    "fefunca", "fefuncr", "fefuncg", "fefuncb", "feconvolvematrix",
    "lineargradient", "radialgradient", "switch", "metadata", "title", "desc",
    "tspan", "textpath", "lineargradient",
}

# Substrings that are forbidden anywhere (case-insensitive). These cover script
# execution, external/network references, and embedded foreign content.
_FORBIDDEN_PATTERNS = [
    r"<script",            # inline script
    r"<foreignobject",     # arbitrary embedded HTML
    r"<iframe",
    r"<image[\s>]",        # external raster refs (xlink:href to network/file)
    r"javascript:",        # javascript: URLs
    r"\bon\w+\s*=",        # event handlers: onload=, onclick=, ...
    r"<!entity",           # XML entity definitions (XXE / billion laughs)
    r"<!doctype",          # DOCTYPE (entity vector)
    r"data:text/html",     # html data URIs
]

# href/url() values are restricted: only same-document refs ("#id") are allowed.
_HREF_RE = re.compile(r'(?:xlink:href|href)\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE)
_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.IGNORECASE)
_TAG_RE = re.compile(r"<\s*([a-zA-Z][\w:-]*)")


class SVGValidationError(ValueError):
    """Raised when free-form SVG source fails static validation."""


def validate_svg(source: str) -> str:
    """Validate free-form SVG ``source``; return it unchanged if it passes.

    Raises :class:`SVGValidationError` on the first problem found. This is a
    static filter, not a sandbox (see module docstring / ADR 0005).
    """
    if not source or not source.strip():
        raise SVGValidationError("empty SVG source")

    low = source.lower()

    if "<svg" not in low:
        raise SVGValidationError("source does not contain an <svg> root element")

    for pat in _FORBIDDEN_PATTERNS:
        if re.search(pat, low):
            raise SVGValidationError(f"forbidden content matched pattern: {pat!r}")

    # Tag allow-list.
    for match in _TAG_RE.finditer(low):
        tag = match.group(1).split(":")[-1]  # strip namespace prefix
        if tag not in _ALLOWED_TAGS:
            raise SVGValidationError(f"disallowed tag: <{tag}>")

    # References must stay in-document (no http(s)/file/data network fetches).
    for ref in _HREF_RE.findall(source) + _URL_RE.findall(source):
        r = ref.strip()
        if r and not r.startswith("#"):
            raise SVGValidationError(
                f"external reference not allowed: {ref!r} (only in-document '#id' refs)"
            )

    return source
