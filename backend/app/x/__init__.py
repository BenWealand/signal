"""X/Twitter workflow package for Signal.

Implements the full trend → article → frontend link → share package loop.
X API calls live behind ``XClient`` stubs for you to fill in.
"""

from app.x.client import XApiNotConfigured, XClient, get_x_client
from app.x.models import XCandidate, XPostResult, XSharePackage
from app.x.pipeline import run_x_pipeline, write_article_for_candidate

__all__ = [
    "XApiNotConfigured",
    "XCandidate",
    "XClient",
    "XPostResult",
    "XSharePackage",
    "get_x_client",
    "run_x_pipeline",
    "write_article_for_candidate",
]
