"""
Protocol helpers for the CSC/ECE 573 P2P-CI project.

This module knows how to construct and parse P2P-CI/1.0 request/response
messages.  All helpers operate on CRLF-terminated strings and return bytes
ready to be sent over a TCP socket.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

PROTOCOL_VERSION = "P2P-CI/1.0"
CRLF = "\r\n"


class ProtocolError(RuntimeError):
    """Raised when an incoming message cannot be parsed."""


def _normalise_headers(headers: Iterable[Tuple[str, str]] | Dict[str, str] | None) -> List[Tuple[str, str]]:
    if headers is None:
        return []
    if isinstance(headers, dict):
        return list(headers.items())
    return list(headers)


def _serialise(start_line: str, headers: Iterable[Tuple[str, str]], body: str = "") -> bytes:
    header_lines = [f"{key}: {value}" for key, value in headers]
    parts = [start_line, *header_lines, "", body]
    return (CRLF.join(parts)).encode("utf-8")


def build_request(
    method: str,
    resource: str,
    headers: Iterable[Tuple[str, str]] | Dict[str, str] | None = None,
    body: str = "",
) -> bytes:
    start_line = f"{method} {resource} {PROTOCOL_VERSION}"
    return _serialise(start_line, _normalise_headers(headers), body)


def build_status(
    version: str,
    status_code: int,
    reason: str,
    headers: Iterable[Tuple[str, str]] | Dict[str, str] | None = None,
    body: str = "",
) -> bytes:
    start_line = f"{version} {status_code} {reason}"
    return _serialise(start_line, _normalise_headers(headers), body)


def parse_message(raw: str) -> Tuple[str, Dict[str, str], str]:
    if CRLF not in raw:
        raise ProtocolError("Message missing CRLF terminator")
    head, _, body = raw.partition(CRLF + CRLF)
    lines = head.split(CRLF)
    if not lines:
        raise ProtocolError("Empty message")
    start_line = lines[0]
    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise ProtocolError(f"Malformed header line: {line!r}")
        key, value = line.split(":", 1)
        headers[key.strip()] = value.strip()
    return start_line, headers, body


def parse_status_line(line: str) -> Tuple[str, int, str]:
    tokens = line.split()
    if len(tokens) < 3:
        raise ProtocolError(f"Malformed status line: {line!r}")
    version = tokens[0]
    status = tokens[1]
    reason = " ".join(tokens[2:])
    if not status.isdigit():
        raise ProtocolError(f"Non-numeric status code: {status}")
    return version, int(status), reason


def parse_request_line(line: str) -> Tuple[str, str, str]:
    tokens = line.split()
    if len(tokens) < 3:
        raise ProtocolError(f"Malformed request line: {line!r}")
    method = tokens[0]
    version = tokens[-1]
    resource = " ".join(tokens[1:-1])
    if not resource:
        raise ProtocolError(f"Missing resource in request line: {line!r}")
    return method, resource, version
