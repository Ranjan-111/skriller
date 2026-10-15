"""Provision the pinned public tokenizer asset before starting offline workers."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
KEY = "fb374d419588a4632f3f557e76b4b70aebbca790"
DIGEST = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
MAX_BYTES = 8 * 1024 * 1024


def provision(directory, *, download=False):
    directory = Path(directory)
    target = directory / KEY
    if directory.is_symlink() or target.is_symlink():
        raise ValueError("Tokenizer cache must not be a symlink")
    if target.is_file():
        with target.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    elif download:
        with urllib.request.urlopen(URL, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
    else:
        raise ValueError("Missing tokenizer asset; opt in to setup-time download")
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != DIGEST:
        raise ValueError("Tokenizer asset integrity failure")
    if not target.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".runtime/tiktoken-cache")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    provision(args.directory, download=args.download)
    print("Pinned tokenizer asset verified; runtime needs no tokenizer download")
