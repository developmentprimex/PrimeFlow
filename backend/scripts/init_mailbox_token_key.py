"""Provision a persistent, separate mailbox encryption key without printing it.

Run on Windows as the backend service identity (Administrator/SYSTEM in production).
The directory must be dedicated to this key. Existing keys are validated, never replaced.
"""
import argparse
import os
from pathlib import Path
import subprocess

from cryptography.fernet import Fernet


def provision_key(path: Path) -> bool:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        # Protect before writing; use SIDs so this works on localized Windows.
        subprocess.run([
            "icacls", str(path.parent), "/inheritance:r", "/grant:r",
            "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F",
        ], check=True, capture_output=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        Fernet(path.read_bytes().strip())
        return False
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(Fernet.generate_key() + b"\n")
    Fernet(path.read_bytes().strip())
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    args = parser.parse_args()
    created = provision_key(args.path)
    print("Mailbox encryption key created." if created else "Existing mailbox encryption key validated; unchanged.")
