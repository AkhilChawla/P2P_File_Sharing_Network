"""Local RFC storage helpers."""
from __future__ import annotations

from pathlib import Path


class RFCStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_rfc_files(self) -> list[Path]:
        return [p for p in self.root.glob("*.txt")]

    def path_for(self, rfc_number: int) -> Path:
        return self.root / f"rfc_{rfc_number}.txt"

    def save(self, rfc_number: int, content: bytes) -> Path:
        path = self.path_for(rfc_number)
        path.write_bytes(content)
        return path

    def read(self, rfc_number: int) -> bytes:
        path = self.path_for(rfc_number)
        return path.read_bytes()

