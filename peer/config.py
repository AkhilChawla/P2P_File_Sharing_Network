"""Configuration helpers for the peer process."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PeerConfig:
    server_host: str = "localhost"
    server_port: int = 7734
    peer_host: str = "localhost"
    peer_port: int = 6000
    rfc_store: str = "rfc_store"
    sample_dir: str = "sample_rfc"
