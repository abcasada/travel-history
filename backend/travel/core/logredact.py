"""Log formatters that redact secrets from every line (work-order item 7).

The code is written so that tokens never reach a log call; this is the second layer, for
lines the code doesn't control: the development server's request line (which includes the
query string), third-party messages, exception text. Applied to each formatted line, so it
also covers arguments and tracebacks.
"""

import logging
import re

from django.utils.log import ServerFormatter

_PATTERNS = (
    # Device tokens wherever they appear.
    (re.compile(r"trk_[A-Za-z0-9_-]{4,}"), "trk_[redacted]"),
    # Token-like query parameters.
    (
        re.compile(r"([?&](?:token|access_token|password)=)[^&\s\"']*", re.IGNORECASE),
        r"\1[redacted]",
    ),
    # Authorization header values (Basic carries the token base64-encoded).
    (
        re.compile(r"((?:authorization)['\"]?\s*[:=]\s*['\"]?)(basic|bearer)\s+[^\s'\",]+", re.I),
        r"\1\2 [redacted]",
    ),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class RedactingServerFormatter(ServerFormatter):
    """`runserver`'s request log, which prints the raw request line."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
