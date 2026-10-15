"""Stage hash-checked uv.lock wheels for offline worker image builds."""

import argparse
import hashlib
import re
import tomllib
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PACKAGES = {
    "beautifulsoup4",
    "html2text",
    "minify-html",
    "regex",
    "semchunk",
    "soupsieve",
    "tiktoken",
    "tqdm",
}


def provision(directory, architecture, *, download=False, package_names=None):
    package_names = PACKAGES if package_names is None else set(package_names)
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Artifact directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    packages = tomllib.loads(Path("uv.lock").read_text())["package"]
    wheels = []
    for package in packages:
        if package["name"] not in package_names:
            continue
        universal = [wheel for wheel in package["wheels"] if wheel["url"].endswith("none-any.whl")]
        selected = universal or [
            wheel
            for wheel in package["wheels"]
            if (
                ("cp312-cp312" in wheel["url"] or compatible_abi(wheel["url"]))
                and "manylinux" in wheel["url"]
                and architecture in wheel["url"]
            )
        ]
        if len(selected) != 1:
            raise ValueError("Expected one locked compatible worker wheel")
        wheels.append(selected[0])
    if len(wheels) != len(package_names):
        raise ValueError("Incomplete locked worker closure")

    def stage(wheel):
        name = wheel["url"].split("/")[-1]
        target = directory / name
        if target.is_symlink():
            raise ValueError("Wheel must not be a symlink")
        if target.is_file():
            data = target.read_bytes()
        elif download and wheel["url"].startswith("https://files.pythonhosted.org/packages/"):
            with urllib.request.urlopen(wheel["url"], timeout=60) as response:
                data = response.read(wheel["size"] + 1)
        else:
            raise ValueError("Missing wheel; opt in to build-time downloads")
        if len(data) != wheel["size"] or hashlib.sha256(data).hexdigest() != wheel[
            "hash"
        ].removeprefix("sha256:"):
            raise ValueError(f"Locked wheel integrity failure: {name}")
        target.write_bytes(data)
        return wheel["hash"].removeprefix("sha256:") + "  " + name

    with ThreadPoolExecutor(max_workers=4) as executor:
        manifest = list(executor.map(stage, wheels))
    (directory / "SHA256SUMS").write_text("\n".join(sorted(manifest)) + "\n")
    return len(wheels)


def compatible_abi(url):
    """A CPython stable-ABI wheel for 3.7+ can also run on the pinned 3.12 runtime."""
    match = re.search(r"-cp(3)(\d+)-abi3-", url)
    return bool(match and (int(match[1]), int(match[2])) <= (3, 12))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".runtime/cleanup-build")
    parser.add_argument("--architecture", choices=["aarch64", "x86_64"], default="aarch64")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    print(
        f"Verified {provision(args.directory, args.architecture, download=args.download)} locked cleanup wheels"
    )
