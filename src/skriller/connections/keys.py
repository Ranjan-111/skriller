"""Explicit private keyring files using copied Agent-Reach safe path helpers."""

import base64
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from agent_reach.utils.paths import (
    atomic_write_private_text,
    make_private_dir,
    read_small_text_no_follow,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Keyring:
    active: str
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self):
        if not 1 <= len(self.keys) <= 3 or self.active not in self.keys:
            raise ValueError("Keyring requires an active key and at most three versions")
        if any(
            not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name) or len(value) != 32
            for name, value in self.keys.items()
        ):
            raise ValueError("Versioned AES-256 keys required")
        object.__setattr__(self, "keys", MappingProxyType(dict(self.keys)))

    @classmethod
    def load(cls, path: str | Path | None):
        if path is None:
            raise KeyUnavailable("Source connection encryption is not configured")
        try:
            mode = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o077 or mode.st_uid != os.getuid():
                raise ValueError("Keyring must be a private owner file")
            text = read_small_text_no_follow(path, max_bytes=4096)
            data = json.loads(text or "")
            if set(data) != {"active", "keys"}:
                raise ValueError("Invalid keyring envelope")
            return cls(
                data["active"],
                {
                    name: base64.b64decode(value, validate=True)
                    for name, value in data["keys"].items()
                },
            )
        except Exception:  # noqa: BLE001 - never expose key content/path/provider exceptions
            raise KeyUnavailable("Source connection encryption key is unavailable") from None

    @classmethod
    def create_file(cls, path: str | Path, *, version: str = "v1"):
        target = Path(path)
        make_private_dir(target.parent)
        lock = target.parent / (target.name + ".init-lock")
        try:
            descriptor = os.open(
                lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
        except FileExistsError:
            raise ValueError("Keyring initialization is already in progress") from None
        try:
            if target.exists() or target.is_symlink():
                raise ValueError("Refusing to replace an existing keyring")
            ring = cls(version, {version: AESGCM.generate_key(bit_length=256)})
            encoded = {
                "active": version,
                "keys": {version: base64.b64encode(ring.keys[version]).decode()},
            }
            atomic_write_private_text(target, json.dumps(encoded))
            return ring
        finally:
            os.close(descriptor)
            lock.unlink(missing_ok=True)
