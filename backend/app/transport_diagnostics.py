"""Bounded network diagnostics; never serialize exception messages or URLs."""

import socket
import ssl
from typing import Any
from urllib.error import URLError


def transport_failure(
    error: BaseException, phase: str, elapsed: float
) -> dict[str, Any]:
    reason = error.reason if isinstance(error, URLError) else error
    category = "network_error"
    safe_to_retry = False
    outcome_unknown = True
    if isinstance(reason, socket.gaierror):
        category, phase, outcome_unknown = "dns_error", "dns", False
        safe_to_retry = reason.errno == socket.EAI_AGAIN
    elif isinstance(reason, ssl.SSLCertVerificationError):
        category, phase, outcome_unknown = "certificate_verification", "tls", False
    elif isinstance(reason, ssl.SSLError):
        category, phase, outcome_unknown = "tls_error", "tls", False
    elif isinstance(reason, ConnectionRefusedError):
        category, phase, safe_to_retry, outcome_unknown = (
            "connection_refused",
            "connect",
            True,
            False,
        )
    elif isinstance(reason, TimeoutError):
        category = "timeout"
    elif isinstance(reason, ConnectionResetError):
        category = "connection_reset"
    return {
        "phase": phase,
        "reason": category,
        "exception_type": type(reason).__name__
        if isinstance(reason, BaseException)
        else "URLError",
        "errno": reason.errno if isinstance(reason, OSError) else None,
        "elapsed_seconds": round(max(0, elapsed), 3),
        "safe_to_retry": safe_to_retry,
        "outcome_unknown": outcome_unknown,
    }
