"""Neutralise line breaks in values that end up in log messages.

A value a client controls (a chore's text, an upgrade tag) that contains a
newline could otherwise start a forged log line. Escaping CR and LF keeps the
value readable while guaranteeing one record stays one line.
"""


def log_safe(value: object) -> str:
    """``str(value)`` with carriage returns and line feeds escaped."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")
