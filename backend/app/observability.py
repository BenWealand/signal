from __future__ import annotations

import logging
from typing import Any


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    clean_fields = {key: value for key, value in fields.items() if value not in (None, "")}
    logger.log(level, event, extra={"event": event, **clean_fields})
