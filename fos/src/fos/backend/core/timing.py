"""
Timing instrumentation for performance diagnosis.

Provides context managers and helpers for measuring critical-path durations.
Outputs consistent log prefixes for easy grepping in Docker logs.

Contains:
    - log_time: Context manager for timing code blocks
    - log_event: One-shot event logger with category prefix
"""

import logging
import time
from contextlib import contextmanager
from typing import Any


logger = logging.getLogger("fos.timing")


@contextmanager
def log_time(category: str, **kwargs: Any):
    """
    Time a code block and log the duration.

    Args:
        category: Log prefix category (LLM, SIM, WS, DB)
        **kwargs: Additional key=value pairs to include in log line

    Usage:
        with log_time("LLM", provider="openai", model="gpt-4"):
            result = call_llm()
        # Logs: [LLM] provider=openai model=gpt-4 duration_ms=2340
    """
    start = time.monotonic()
    error = None
    try:
        yield
    except Exception as e:
        error = str(e)
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        parts = [f"{k}={v}" for k, v in kwargs.items()]
        parts.append(f"duration_ms={duration_ms}")
        if error:
            parts.append("status=error")
            parts.append(f"error={error[:80]}")
        else:
            parts.append("status=ok")
        logger.info("[%s] %s", category, " ".join(parts))


def log_event(category: str, **kwargs: Any) -> None:
    """
    Log a one-shot event with category prefix.

    Args:
        category: Log prefix category (LLM, SIM, WS, DB)
        **kwargs: key=value pairs to include in log line

    Usage:
        log_event("WS", sim_id="abc", event="connected", clients=5)
        # Logs: [WS] sim_id=abc event=connected clients=5
    """
    parts = [f"{k}={v}" for k, v in kwargs.items()]
    logger.info("[%s] %s", category, " ".join(parts))
