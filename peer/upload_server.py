"""Peer upload server that responds to P2P-CI GET requests."""
from __future__ import annotations

import logging
import platform
import socket
import threading
from email.utils import formatdate
from pathlib import Path
from typing import Optional

from shared import protocol


class PeerUploadServer:
    def __init__(self, host: str, port: int, storage, logger: logging.Logger) -> None:
        self.host = host
        self.port = port
        self.storage = storage
        self.logger = logger
        self._socket: Optional[socket.socket] = None
        self._shutdown = threading.Event()

    def start(self) -> None:
        if self._socket:
            raise RuntimeError("Upload server already running")
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen()
        threading.Thread(target=self._serve, name="UploadServer", daemon=True).start()
        self.logger.info("Upload server listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        self._shutdown.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._shutdown.is_set():
            try:
                self._socket.settimeout(1.0)
                conn, addr = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()

    def _handle_client(self, conn: socket.socket, addr) -> None:
        with conn:
            try:
                request_text = self._recv_text(conn)
                if not request_text:
                    return
                # Log the full incoming GET request at INFO so peer operators can see downloads.
                self.logger.info("P2P request from %s:%s\n%s", addr[0], addr[1], request_text.replace(protocol.CRLF, "\n"))
                request_line, headers, _ = protocol.parse_message(request_text)
                method, resource, version = protocol.parse_request_line(request_line)
                if version != protocol.PROTOCOL_VERSION:
                    self._send_error(conn, 505, "P2P-CI Version Not Supported")
                    return
                if method != "GET":
                    self._send_error(conn, 400, "Bad Request")
                    return
                if "Host" not in headers or "OS" not in headers:
                    self._send_error(conn, 400, "Bad Request")
                    return
                parts = resource.split()
                if len(parts) != 2 or parts[0] != "RFC":
                    self._send_error(conn, 400, "Bad Request")
                    return
                try:
                    rfc_number = int(parts[1])
                except ValueError:
                    self._send_error(conn, 400, "Bad Request")
                    return
                path: Path = self.storage.path_for(rfc_number)
                if not path.exists():
                    self.logger.warning("RFC %s not found for peer request %s", rfc_number, addr)
                    self._send_error(conn, 404, "Not Found")
                    return
                content = path.read_bytes()
                stat = path.stat()
                headers_list = [
                    ("Date", formatdate(usegmt=True)),
                    ("OS", platform.platform()),
                    ("Last-Modified", formatdate(stat.st_mtime, usegmt=True)),
                    ("Content-Length", str(len(content))),
                    # The specification mandates Content-Type to be text/plain for this project.
                    ("Content-Type", "text/plain"),
                ]
                payload = protocol.build_status(
                    protocol.PROTOCOL_VERSION,
                    200,
                    "OK",
                    headers_list,
                    content.decode("utf-8"),
                )
                self.logger.debug(
                    "P2P response to %s:%s\n%s",
                    addr[0],
                    addr[1],
                    payload.decode("utf-8").replace(protocol.CRLF, "\n"),
                )
                conn.sendall(payload)
            except FileNotFoundError:
                self._send_error(conn, 404, "Not Found")
            except protocol.ProtocolError as exc:
                self.logger.warning("Malformed P2P request from %s:%s -> %s", addr[0], addr[1], exc)
                self._send_error(conn, 400, "Bad Request")
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.exception("Unhandled error serving %s:%s -> %s", addr[0], addr[1], exc)
                self._send_error(conn, 500, "Internal Server Error")

    def _send_error(self, conn: socket.socket, status: int, reason: str) -> None:
        payload = protocol.build_status(
            protocol.PROTOCOL_VERSION,
            status,
            reason,
            [
                ("Date", formatdate(usegmt=True)),
                ("OS", platform.platform()),
                ("Content-Length", "0"),
                # Use text/plain to match the project specification
                ("Content-Type", "text/plain"),
            ],
            "",
        )
        self.logger.debug(
            "P2P error response %s %s\n%s",
            status,
            reason,
            payload.decode("utf-8").replace(protocol.CRLF, "\n"),
        )
        conn.sendall(payload)

    def _recv_text(self, conn: socket.socket) -> str:
        conn.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8") if data else ""
