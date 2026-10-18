"""Stage the minimal X worker closure from hash-checked lockfile wheels."""

import argparse

from scripts.provision_cleanup_assets import provision

PACKAGES = {
    "typing-extensions",
    "annotated-types",
    "pydantic",
    "typing-inspection",
    "pydantic-core",
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".runtime/x-build")
    parser.add_argument("--architecture", choices=["aarch64", "x86_64"], default="aarch64")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    count = provision(
        args.directory, args.architecture, download=args.download, package_names=PACKAGES
    )
    print(f"Verified {count} locked X worker wheels")
