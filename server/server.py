#!/usr/bin/env python3
"""
Centralized P2P-CI Server

This process listens on TCP port 7734 and services ADD, LOOKUP, and LIST
requests from peers participating in the P2P file-sharing system.
"""

from __future__ import annotations
import logging
import socket
import sys
import threading
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from shared import protocol

HOST = ""
PORT = 7734

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("p2p-ci-server")


@dataclass
class RFCRecord:
    number: int
    title: str
    host: str
    port: int


class RFCIndex:
    """Thread-safe in-memory index of peers and advertised RFCs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[int, Dict[Tuple[str, int], RFCRecord]] = {}
        self._peer_rfcs: Dict[Tuple[str, int], set[int]] = {}

    def register_peer(self, host: str, port: int) -> None:
        with self._lock:
            self._peer_rfcs.setdefault((host, port), set())

    def unregister_peer(self, host: str, port: int) -> None:
        key = (host, port)
        with self._lock:
            numbers = self._peer_rfcs.pop(key, set())
            for number in numbers:
                entries = self._records.get(number)
                if entries and key in entries:
                    del entries[key]
                    if not entries:
                        del self._records[number]

    def add(self, number: int, title: str, host: str, port: int) -> List[RFCRecord]:
        key = (host, port)
        with self._lock:
            entries = self._records.setdefault(number, {})
            entries[key] = RFCRecord(number, title, host, port)
            self._peer_rfcs.setdefault(key, set()).add(number)
            return list(entries.values())

    def lookup(self, number: int) -> List[RFCRecord]:
        with self._lock:
            entries = self._records.get(number, {})
            return list(entries.values())

    def list_all(self) -> List[RFCRecord]:
        with self._lock:
            all_entries: List[RFCRecord] = []
            for rfc_number in sorted(self._records):
                all_entries.extend(sorted(self._records[rfc_number].values(), key=lambda rec: (rec.host, rec.port)))
            return all_entries


INDEX = RFCIndex()


def recv_request(conn: socket.socket) -> Optional[str]:
    """Receive a complete request terminated by CRLF CRLF."""
    data = b""
    while True:
        if b"\r\n\r\n" in data:
            break
        try:
            chunk = conn.recv(4096)
        except TimeoutError:
            continue
        if not chunk:
            return None
        data += chunk
    return data.decode("utf-8", errors="ignore")


def format_entries(entries: Iterable[RFCRecord]) -> str:
    lines = [
        f"RFC {entry.number} {entry.title} {entry.host} {entry.port}"
        for entry in entries
    ]
    return protocol.CRLF.join(lines)


def send_response(
    conn: socket.socket,
    status: int,
    phrase: str,
    body: str = "",
    *,
    log_target: str,
) -> None:
    parts = [f"{protocol.PROTOCOL_VERSION} {status} {phrase}"]
    if body:
        parts.append("")
        parts.append(body)
    message = protocol.CRLF.join(parts) + protocol.CRLF + protocol.CRLF
    LOGGER.debug("Response to %s\n%s", log_target, message.replace(protocol.CRLF, "\n"))
    conn.sendall(message.encode("utf-8"))


def parse_rfc_resource(resource: str) -> Optional[int]:
    parts = resource.split()
    if len(parts) != 2 or parts[0] != "RFC":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def handle_client(conn: socket.socket, addr: Tuple[str, int]) -> None:
    LOGGER.info("Accepted connection from %s:%s", addr[0], addr[1])
    peer_host: Optional[str] = None
    peer_port: Optional[int] = None
    try:
        while True:
            raw = recv_request(conn)
            if raw is None:
                break
            LOGGER.info(
                "Request from %s:%s\n%s",
                addr[0],
                addr[1],
                raw.replace(protocol.CRLF, "\n"),
            )
            try:
                request_line, headers, _ = protocol.parse_message(raw)
                method, resource, version = protocol.parse_request_line(request_line)
            except protocol.ProtocolError as exc:
                LOGGER.warning("Protocol error from %s:%s -> %s", addr[0], addr[1], exc)
                send_response(conn, 400, "Bad Request", "", log_target=f"{addr[0]}:{addr[1]}")
                continue

            if version != protocol.PROTOCOL_VERSION:
                send_response(conn, 505, "P2P-CI Version Not Supported", "", log_target=f"{addr[0]}:{addr[1]}")
                continue

            host = headers.get("Host")
            port_header = headers.get("Port")
            title = headers.get("Title")
            if host is None or port_header is None:
                send_response(conn, 400, "Bad Request", "", log_target=f"{addr[0]}:{addr[1]}")
                continue
            try:
                port_value = int(port_header)
            except ValueError:
                send_response(conn, 400, "Bad Request", "", log_target=f"{addr[0]}:{addr[1]}")
                continue

            peer_host, peer_port = host, port_value
            INDEX.register_peer(host, port_value)
            log_target = f"{host}:{port_value}"

            if method == "ADD":
                number = parse_rfc_resource(resource)
                if number is None or not title:
                    send_response(conn, 400, "Bad Request", "", log_target=log_target)
                    continue

                INDEX.add(number, title, host, port_value)
                LOGGER.info("Registered RFC %s for %s:%s", number, host, port_value)
                
                body = f"RFC {number} {title} {host} {port_value}"
                send_response(conn, 200, "OK", body, log_target=log_target)
            elif method == "LOOKUP":
                number = parse_rfc_resource(resource)
                if number is None:
                    send_response(conn, 400, "Bad Request", "", log_target=log_target)
                    continue
                records = INDEX.lookup(number)
                if not records:
                    send_response(conn, 404, "Not Found", "", log_target=log_target)
                    LOGGER.info("LOOKUP RFC %s -> 404", number)
                else:
                    send_response(conn, 200, "OK", format_entries(records), log_target=log_target)
                    LOGGER.info("LOOKUP RFC %s -> %s record(s)", number, len(records))
            elif method == "LIST":
                if resource != "ALL":
                    send_response(conn, 400, "Bad Request", "", log_target=log_target)
                    continue
                entries = INDEX.list_all()
                if not entries:
                    send_response(conn, 404, "Not Found", "", log_target=log_target)
                    LOGGER.info("LIST ALL -> 404 (empty index)")
                else:
                    send_response(conn, 200, "OK", format_entries(entries), log_target=log_target)
                    LOGGER.info("LIST ALL -> %s record(s)", len(entries))
            else:
                LOGGER.warning("Unsupported method %s from %s:%s", method, addr[0], addr[1])
                send_response(conn, 400, "Bad Request", "", log_target=log_target)
    finally:
        if peer_host and peer_port is not None:
            INDEX.unregister_peer(peer_host, peer_port)
            LOGGER.info("Peer %s:%s disconnected; records purged", peer_host, peer_port)
        try:
            conn.close()
        except OSError:
            pass
        LOGGER.info("Closed connection from %s:%s", addr[0], addr[1])


def serve_forever(host: str = HOST, port: int = PORT) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind((host, port))
        except OSError as exc:
            LOGGER.error("Failed to bind to %s:%s -> %s", host or "0.0.0.0", port, exc)
            sys.exit(1)

        server_socket.listen()
        LOGGER.info("P2P-CI server listening on %s:%s", host or "0.0.0.0", port)

        try:
            while True:
                conn, addr = server_socket.accept()
                thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
                thread.start()
        except KeyboardInterrupt:
            LOGGER.info("Received Ctrl+C; shutting down.")
        except Exception as exc:
            LOGGER.exception("Server error: %s", exc)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Centralized P2P-CI index server.")
    parser.add_argument("--host", default=HOST, help="Interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=PORT, help="Port to listen on (default: 7734)")
    args = parser.parse_args(argv)

    serve_forever(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
