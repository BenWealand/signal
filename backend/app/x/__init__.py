"""X/Twitter workflow package for Signal.

Implements the full topic → article → frontend link → share package loop.
Live X search, lookup, and post/reply are implemented in ``XClient``.
Trends are intentionally unused; discovery seeds recent search from desk topics.
"""

from app.x.client import XApiError, XApiNotConfigured, XClient, get_x_client, reset_x_client
from app.x.models import XCandidate, XPostResult, XSharePackage
from app.x.pipeline import run_x_pipeline, write_article_for_candidate

__all__ = [
    "XApiError",
    "XApiNotConfigured",
    "XCandidate",
    "XClient",
    "XPostResult",
    "XSharePackage",
    "get_x_client",
    "reset_x_client",
    "run_x_pipeline",
    "write_article_for_candidate",
]
