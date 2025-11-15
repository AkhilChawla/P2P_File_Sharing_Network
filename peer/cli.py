"""Command-line interface for running the peer client + upload server."""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .client import CentralServerClient, PeerNode
from .config import PeerConfig
from .logging_utils import configure_logging
from .storage import RFCStorage
from .upload_server import PeerUploadServer


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Peer client + upload server for CSC/ECE 573 P2P project.")
    parser.add_argument("--server-host", default="localhost", help="Centralized server host (default: localhost)")
    parser.add_argument("--server-port", type=int, default=7734, help="Centralized server port (default: 7734)")
    parser.add_argument("--peer-host", default="localhost", help="Peer host to advertise (default: localhost)")
    parser.add_argument("--peer-port", type=int, default=6000, help="Peer upload server port (default: 6000)")
    parser.add_argument("--rfc-store", default="rfc_store", help="Directory where RFC files are stored locally")
    parser.add_argument("--sample-dir", default="sample_rfc", help="Sample RFC directory used by the seed command")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--offline", action="store_true", help="Run without a centralized server (uses local index file)")
    parser.add_argument("--offline-index", default="offline_index.json", help="Path to shared index file when --offline is set")
    return parser


class PeerShell:
    def __init__(self, peer: PeerNode) -> None:
        self.peer = peer
        self.logger = peer.logger

    def run(self) -> None:
        try:
            self.peer.start()
        except (ConnectionError, TimeoutError) as exc:
            if self.peer.config.offline:
                raise
            self.logger.error("Unable to reach central server: %s", exc)
            print("Failed to contact central server. Exiting.")
            self.peer.shutdown()
            return
        print("Peer started. Type 'help' for commands. Ctrl-D or 'exit' to quit.")
        try:
            while True:
                try:
                    raw = input("peer> ")
                except EOFError:
                    print()
                    break
                except KeyboardInterrupt:
                    print()
                    break
                command = raw.strip()
                if not command:
                    continue
                if command.lower() in {"exit", "quit"}:
                    break
                try:
                    self._dispatch(command)
                except (ConnectionError, TimeoutError) as exc:
                    if self.peer.config.offline:
                        raise
                    self.logger.error("Connection to central server lost: %s", exc)
                    print("Central server connection lost. Exiting.")
                    break
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.error("Command failed: %s", exc)
        finally:
            self.peer.shutdown()

    def _dispatch(self, command: str) -> None:
        tokens = shlex.split(command)
        if not tokens:
            return
        cmd, *args = tokens
        cmd = cmd.lower()
        if cmd == "help":
            self._print_help()
        elif cmd == "sync":
            self.peer.sync_local_rfcs()
            print("Synced local RFCs with central server.")
        elif cmd == "seed":
            directory = args[0] if args else self.peer.config.sample_dir
            imported = self.peer.seed_from_directory(directory)
            print(f"Imported {imported} RFC(s) from {directory}.")
        elif cmd == "list":
            response = self.peer.list_index()
            # Print the raw response exactly as received from the server
            print("LIST response:")
            print(response.raw.replace("\r\n", "\n"))
        elif cmd == "local":
            files = self.peer.storage.list_rfc_files()
            if not files:
                print("No local RFCs.")
            else:
                for path in files:
                    print(path.name)
        elif cmd == "lookup":
            if not args:
                raise ValueError("Usage: lookup <rfc_number> [title]")
            rfc_number = int(args[0])
            title = " ".join(args[1:]) if len(args) > 1 else None
            response, _ = self.peer.lookup_rfc(rfc_number, title)
            print("LOOKUP response:")
            # print the raw server response
            print(response.raw.replace("\r\n", "\n"))
        elif cmd == "add":
            if len(args) < 3:
                raise ValueError("Usage: add <rfc_number> <file_path> \"Title\"")
            rfc_number = int(args[0])
            file_path = Path(args[1])
            title = " ".join(args[2:])
            response = self.peer.add_local_rfc(rfc_number, title, file_path)
            print("ADD response:")
            # Print the raw response from the server
            print(response.raw.replace("\r\n", "\n"))
        elif cmd in {"get", "download"}:
            if len(args) < 3:
                raise ValueError("Usage: get <rfc_number> <host> <port>")
            rfc_number = int(args[0])
            target_host = args[1]
            try:
                target_port = int(args[2])
            except ValueError as exc:
                raise ValueError("Port must be an integer") from exc
            try:
                result = self.peer.download_specific(rfc_number, target_host, target_port)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"GET response: failed to download RFC {rfc_number} from {target_host}:{target_port}: {exc}")
                print()
                return
            print("GET response from peer:")
            print(result.peer_raw_response.replace("\r\n", "\n"))
            print(f"\nSaved to {result.path}")
            if result.add_response and result.add_response.status_code == 200:
                print("Server registration updated with downloaded RFC.")
            elif result.add_response:
                print(
                    f"Server registration failed: {result.add_response.status_code} {result.add_response.reason}"
                )
            print()
        else:
            raise ValueError(f"Unknown command: {cmd}")

    @staticmethod
    def _print_help() -> None:
        print(
            "Commands:\n"
            "  help                      Show this message\n"
            "  sync                      Register all local RFCs with the central server\n"
            "  seed [dir]                Copy sample RFCs into the local store and register them\n"
            "  list                      List the central index as returned by the server\n"
            "  local                     List RFC files stored locally\n"
            "  lookup <rfc> [title]      Find peers that host an RFC\n"
            "  add <rfc> <file> \"Title\"  Copy a file into the local store and ADD to server\n"
            "  get <rfc> <host> <port>   Download RFC content from a specific peer\n"
            "  exit                      Quit the shell\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = PeerConfig(
        server_host=args.server_host,
        server_port=args.server_port,
        peer_host=args.peer_host,
        peer_port=args.peer_port,
        rfc_store=args.rfc_store,
        sample_dir=args.sample_dir,
        offline=args.offline,
        offline_index=args.offline_index,
    )
    logger = configure_logging(args.verbose)
    store = RFCStorage(config.rfc_store)
    upload_server = PeerUploadServer(config.peer_host, config.peer_port, store, logger)
    central_client = CentralServerClient(
        config.server_host,
        config.server_port,
        config.peer_host,
        config.peer_port,
        logger,
        offline=config.offline,
        offline_index=config.offline_index,
    )
    peer = PeerNode(config, central_client, upload_server, store, logger)
    shell = PeerShell(peer)
    shell.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
