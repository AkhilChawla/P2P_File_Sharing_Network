"""Peer client logic for interacting with the centralized index server."""
from __future__ import annotations

import json
import logging
import platform
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from shared import protocol

from . import storage
from .config import PeerConfig
from .upload_server import PeerUploadServer


@dataclass
class ServerResponse:
    status_code: int
    reason: str
    headers: Dict[str, str]
    body: str
    raw: str
    status_line: str


@dataclass
class PeerLocation:
    number: int
    title: str
    host: str
    port: int


def _recv_peer_response(sock: socket.socket) -> str:
    buffer = b""
    sock.settimeout(5)
    content_length: Optional[int] = None
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk
        if content_length is None and b"\r\n\r\n" in buffer:
            head, body = buffer.split(b"\r\n\r\n", 1)
            headers = {}
            for line in head.decode("utf-8").split("\r\n")[1:]:
                if not line:
                    continue
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()
            try:
                content_length = int(headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length == 0:
                break
        if content_length is not None:
            body = buffer.split(b"\r\n\r\n", 1)[1]
            if len(body) >= content_length:
                break
    return buffer.decode("utf-8")


class CentralServerClient:
    def __init__(
        self,
        server_host: str,
        server_port: int,
        peer_host: str,
        peer_port: int,
        logger,
        *,
        offline: bool = False,
        offline_index: str | None = None,
    ) -> None:
        self.server_host = server_host
        self.server_port = server_port
        self.peer_host = peer_host
        self.peer_port = peer_port
        self.logger = logger
        self.offline = offline
        self.offline_index_path = Path(offline_index) if offline_index else Path("offline_index.json")
        if self.offline:
            self.offline_index_path.parent.mkdir(parents=True, exist_ok=True)
        self._socket: Optional[socket.socket] = None

    def add(self, rfc_number: int, title: str) -> ServerResponse:
        headers = {"Host": self.peer_host, "Port": str(self.peer_port), "Title": title}
        return self._send_request("ADD", f"RFC {rfc_number}", headers)

    def lookup(self, rfc_number: int, title: str = "") -> ServerResponse:
        headers = {
            "Host": self.peer_host,
            "Port": str(self.peer_port),
            "Title": title or f"RFC {rfc_number}",
        }
        return self._send_request("LOOKUP", f"RFC {rfc_number}", headers)

    def list_all(self) -> ServerResponse:
        headers = {"Host": self.peer_host, "Port": str(self.peer_port)}
        return self._send_request("LIST", "ALL", headers)

    def _send_request(self, method: str, resource: str, headers: dict[str, str]) -> ServerResponse:
        if self.offline:
            return self._handle_offline(method, resource, headers)
        payload = protocol.build_request(method, resource, headers)
        request_text = payload.decode("utf-8")
        self.logger.debug("Sending to server\n%s", request_text.replace(protocol.CRLF, "\n"))
        self._ensure_connection()
        assert self._socket is not None
        try:
            self._socket.sendall(payload)
            response = self._receive_response()
        except (OSError, ConnectionError, TimeoutError) as exc:
            self.close()
            raise ConnectionError("Central server communication failed") from exc
        self.logger.debug(
            "Received from server\n%s",
            response.raw.replace(protocol.CRLF, "\n"),
        )
        return response

    def _ensure_connection(self) -> socket.socket:
        if self._socket is None:
            try:
                sock = socket.create_connection((self.server_host, self.server_port), timeout=5)
                sock.settimeout(5)
                self._socket = sock
            except OSError as exc:
                self._socket = None
                raise ConnectionError(
                    f"Unable to connect to central server at {self.server_host}:{self.server_port}"
                ) from exc
        return self._socket

    def _receive_response(self) -> ServerResponse:
        if self._socket is None:
            raise ConnectionError("Central server connection not established")
        buffer = b""
        terminator = (protocol.CRLF * 2).encode("utf-8")
        while True:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise ConnectionError("Central server closed connection")
            buffer += chunk
            if buffer.endswith(terminator):
                break
        raw = buffer.decode("utf-8")
        status_line, headers, body = protocol.parse_message(raw)
        _, status_code, reason = protocol.parse_status_line(status_line)
        return ServerResponse(
            status_code=status_code,
            reason=reason,
            headers=headers,
            body=body,
            raw=raw,
            status_line=status_line,
        )

    def close(self) -> None:
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _handle_offline(self, method: str, resource: str, headers: dict[str, str]) -> ServerResponse:
        index = self._offline_load_index()
        rfcs = index.setdefault("rfcs", {})
        if method == "ADD":
            try:
                rfc_number = self._parse_rfc_resource(resource)
            except ValueError as exc:
                return self._offline_response(400, "Bad Request", str(exc))
            host = headers.get("Host")
            port = headers.get("Port")
            title = headers.get("Title", "")
            if host is None or port is None:
                return self._offline_response(400, "Bad Request", "Missing Host/Port headers")
            try:
                port_value = int(port)
            except ValueError:
                return self._offline_response(400, "Bad Request", "Port header must be numeric")
            rfcs[str(rfc_number)] = {"host": host, "port": port_value, "title": title}
            self._offline_save_index(index)
            body = self._format_index_lines({str(rfc_number): rfcs[str(rfc_number)]})
            return self._offline_response(200, "OK", body)
        if method == "LIST":
            body = self._format_index_lines(rfcs)
            status = 200 if body else 404
            reason = "OK" if status == 200 else "Not Found"
            return self._offline_response(status, reason, body)
        if method == "LOOKUP":
            try:
                rfc_number = self._parse_rfc_resource(resource)
            except ValueError as exc:
                return self._offline_response(400, "Bad Request", str(exc))
            entries = rfcs.get(str(rfc_number))
            if not entries:
                return self._offline_response(404, "Not Found", "")
            body = self._format_index_lines({str(rfc_number): entries})
            return self._offline_response(200, "OK", body)
        return self._offline_response(400, "Bad Request", f"Unsupported method {method} in offline mode")

    def _offline_response(self, status: int, reason: str, body: str) -> ServerResponse:
        parts = [f"{protocol.PROTOCOL_VERSION} {status} {reason}"]
        if body:
            parts.append("")
            parts.append(body)
        raw = protocol.CRLF.join(parts) + protocol.CRLF + protocol.CRLF
        return ServerResponse(status, reason, {}, body, raw, f"{protocol.PROTOCOL_VERSION} {status} {reason}")

    def _offline_load_index(self) -> dict:
        path = self.offline_index_path
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.logger.warning("Offline index %s is corrupted; starting fresh.", path)
            return {}

    def _offline_save_index(self, data: dict) -> None:
        path = self.offline_index_path
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _parse_rfc_resource(resource: str) -> int:
        parts = resource.split()
        if len(parts) != 2 or parts[0] != "RFC":
            raise ValueError("Resource must look like 'RFC <number>'")
        return int(parts[1])

    @staticmethod
    def _format_index_lines(rfcs: dict) -> str:
        lines: List[str] = []
        for rfc_number in sorted(rfcs, key=lambda value: int(value)):
            entry = rfcs[rfc_number]
            title = entry.get("title", "")
            lines.append(f"RFC {rfc_number} {title} {entry['host']} {entry['port']}")
        return protocol.CRLF.join(lines)


@dataclass
class DownloadResult:
    path: Path
    add_response: Optional[ServerResponse]
    peer_raw_response: str


class PeerNode:
    def __init__(
        self,
        config: PeerConfig,
        central_client: CentralServerClient,
        upload_server: PeerUploadServer,
        storage_backend: storage.RFCStorage,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.central_client = central_client
        self.upload_server = upload_server
        self.storage = storage_backend
        self.logger = logger

    def start(self) -> None:
        """Start the upload server and register any existing RFCs with the central server.

        This method starts the local upload server and performs an initial registration of 
        all RFC files found in the configured
        ``rfc_store`` directory.
        """
        self.upload_server.start()
        try:
            # register existing local RFCs with the central server
            self.sync_local_rfcs()
        except Exception as exc:  # pylint: disable=broad-except
            # Log but don't prevent startup if registration fails
            self.logger.warning("Initial RFC registration failed: %s", exc)

    def shutdown(self) -> None:
        self.upload_server.stop()
        self.central_client.close()

    def sync_local_rfcs(self) -> None:
        """Register all RFC files in the local store with the central server.

        This method enumerates each ``rfc_*.txt`` file in the configured
        ``rfc_store`` directory, extracts the RFC number from its filename,
        attempts to read the first line of the file as its title (falling back to
        ``"RFC <number>"``), and issues an ``ADD`` request to the central
        server for each.  Errors are logged and do not abort processing of
        subsequent files.
        """
        files = self.storage.list_rfc_files()
        for path in files:
            try:
                number = self._extract_rfc_number(path)
                # infer title from first line of the file if possible
                try:
                    with path.open("r", encoding="utf-8") as fp:
                        first_line = fp.readline().strip()
                except Exception:
                    first_line = ""
                title = first_line or f"RFC {number}"
                resp = self.central_client.add(number, title)
                if resp.status_code != 200:
                    self.logger.warning(
                        "Failed to register local RFC %s: %s %s",
                        number,
                        resp.status_code,
                        resp.reason,
                    )
                else:
                    self.logger.info("Registered local RFC %s (%s)", number, title)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("Unable to sync file %s: %s", path, exc)

    def add_local_rfc(self, rfc_number: int, title: str, source_path: Path) -> ServerResponse:
        target = self.storage.path_for(rfc_number)
        data = Path(source_path).read_bytes()
        target.write_bytes(data)
        response = self.central_client.add(rfc_number, title)
        if response.status_code != 200:
            raise RuntimeError(f"ADD failed: {response.status_code} {response.reason}")
        self.logger.info("Added RFC %s (%s) from %s", rfc_number, title, source_path)
        return response

    def list_index(self) -> ServerResponse:
        response = self.central_client.list_all()
        if response.status_code == 404:
            self.logger.info("LIST returned empty index.")
        elif response.status_code != 200:
            raise RuntimeError(f"LIST failed: {response.status_code} {response.reason}")
        else:
            entries = self._parse_peer_lines(response.body)
            self._refresh_local_from_entries(entries)
        return response

    def lookup_rfc(self, rfc_number: int, title: str | None = None) -> Tuple[ServerResponse, List[PeerLocation]]:
        lookup_title = title or f"RFC {rfc_number}"
        response = self.central_client.lookup(rfc_number, lookup_title)
        if response.status_code == 404:
            self.logger.info("LOOKUP for RFC %s returned no results.", rfc_number)
            return response, []
        if response.status_code != 200:
            raise RuntimeError(f"LOOKUP failed: {response.status_code} {response.reason}")
        entries = self._parse_peer_lines(response.body)
        self._refresh_local_from_entries(entries)
        return response, entries

    def download_specific(self, rfc_number: int, host: str, port: int, title: Optional[str] = None) -> DownloadResult:
        response_text, body = self._download_from_peer(rfc_number, host, port)
        path = self.storage.save(rfc_number, body.encode("utf-8"))
        title = title or self._infer_title(path)
        add_response = self.central_client.add(rfc_number, title)
        if add_response.status_code != 200:
            self.logger.warning(
                "ADD after download failed for RFC %s: %s %s",
                rfc_number,
                add_response.status_code,
                add_response.reason,
            )
        else:
            self.logger.info("Downloaded RFC %s from %s:%s", rfc_number, host, port)
        return DownloadResult(path=path, add_response=add_response, peer_raw_response=response_text)

    def download_from_peers(self, rfc_number: int, peers: List[PeerLocation]) -> DownloadResult:
        for peer in peers:
            if peer.host == self.central_client.peer_host and peer.port == self.central_client.peer_port:
                path = self.storage.path_for(rfc_number)
                if path.exists():
                    self.logger.info("RFC %s already up to date locally.", rfc_number)
                    return DownloadResult(path=path, add_response=None, peer_raw_response="")
                continue
            try:
                return self.download_specific(rfc_number, peer.host, peer.port, peer.title)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("Failed download from %s:%s: %s", peer.host, peer.port, exc)
                continue
        raise RuntimeError("No peers available or download failed.")

    def seed_from_directory(self, directory: str) -> int:
        seed_dir = Path(directory)
        if not seed_dir.exists():
            raise FileNotFoundError(directory)
        imported = 0
        for sample in seed_dir.glob("*.txt"):
            rfc_number = self._extract_rfc_number(sample)
            data = sample.read_bytes()
            self.storage.path_for(rfc_number).write_bytes(data)
            imported += 1
        return imported

    def _download_from_peer(self, rfc_number: int, host: str, port: int) -> Tuple[str, str]:
        headers = {
            "Host": host,
            "OS": platform.platform(),
        }
        payload = protocol.build_request("GET", f"RFC {rfc_number}", headers)
        with socket.create_connection((host, port), timeout=5) as sock:
            self.logger.info("GET request -> %s:%s (RFC %s)", host, port, rfc_number)
            sock.sendall(payload)
            response_text = _recv_peer_response(sock)
        status_line, header_map, body = protocol.parse_message(response_text)
        self.logger.info("GET response <- %s:%s [%s]", host, port, status_line)
        status_line, header_map, body = protocol.parse_message(response_text)
        _, status_code, reason = protocol.parse_status_line(status_line)
        if status_code != 200:
            raise RuntimeError(f"Peer responded with {status_code} {reason}")
        expected = header_map.get("Content-Length")
        if expected and len(body.encode("utf-8")) != int(expected):
            raise RuntimeError("Content length mismatch")
        return response_text, body

    def _parse_peer_lines(self, body: str) -> List[PeerLocation]:
        peers: List[PeerLocation] = []
        for line in body.strip().splitlines():
            if not line:
                continue
            parts = line.split()
            if len(parts) < 5 or parts[0] != "RFC":
                continue
            number = int(parts[1])
            host = parts[-2]
            port = int(parts[-1])
            title = " ".join(parts[2:-2]) if len(parts) > 4 else ""
            peers.append(PeerLocation(number, title, host, port))
        return peers

    @staticmethod
    def _extract_rfc_number(path: Path) -> int:
        stem = path.stem
        num = stem.split("_")[-1]
        return int(num)

    @staticmethod
    def _infer_title(path: Path) -> str:
        with path.open("r", encoding="utf-8") as file:
            first_line = file.readline().strip()
        return first_line or f"RFC {path.stem.split('_')[-1]}"

    def _refresh_local_from_entries(self, entries: List[PeerLocation]) -> None:
        if self.central_client.offline:
            return
        for entry in entries:
            path = self.storage.path_for(entry.number)
            if not path.exists():
                continue
            if entry.host == self.central_client.peer_host and entry.port == self.central_client.peer_port:
                continue
            try:
                _, body = self._download_from_peer(entry.number, entry.host, entry.port)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning("Failed to refresh RFC %s from %s:%s: %s", entry.number, entry.host, entry.port, exc)
                continue
            self.storage.save(entry.number, body.encode("utf-8"))
            self.logger.info(
                "Refreshed local RFC %s with latest version from %s:%s",
                entry.number,
                entry.host,
                entry.port,
            )
