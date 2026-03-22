#!/usr/bin/env python3
"""Record the fabprint setup phase (interactive — requires login).

Usage:
    python scripts/record_setup.py

This records the setup wizard (email, password, verification code, printer
selection) and saves it to docs/recordings/setup.fixed.cast. The demo
build script (record_demo.py) uses this file as-is.

Re-run this script whenever the setup wizard changes or you need a fresh
recording.

Requires: pexpect, asciinema
"""

from __future__ import annotations

import getpass
import subprocess
import sys
import time
from pathlib import Path

from record_demo import (
    RECORDINGS_DIR,
    TYPING_DELAY,
    expect,
    start_recording,
    status,
    stop_recording,
    type_command,
    type_comment,
    type_slowly,
)

CAST_FILE = RECORDINGS_DIR / "setup.fixed.cast"
EMAIL = "paul@fremantle.org"


def read_clipboard() -> str:
    """Read text from the system clipboard (macOS)."""
    return subprocess.check_output(["pbpaste"], text=True).strip()


def record_setup(password: str) -> None:
    """Record the setup phase."""
    # Back up and clear credentials for a fresh setup demo
    cred_path = Path.home() / ".config" / "fabprint" / "credentials.toml"
    cred_backup = None
    if cred_path.exists():
        cred_backup = cred_path.read_text()
        cred_path.unlink()
        status("backed up and cleared credentials")

    child = start_recording(CAST_FILE)

    try:
        type_comment(child, "# Step 1: fabprint setup — run once per printer")
        type_command(child, "fabprint setup")

        # Printer name — accept default "workshop"
        expect(child, "Printer name")
        time.sleep(0.5)
        child.send("\r")
        status("accepted default printer name")

        # Choose type — 2 = bambu-cloud
        expect(child, "Choose type")
        time.sleep(0.5)
        child.sendline("2")
        status("selected bambu-cloud")

        # Confirm cloud login
        expect(child, "Log in now")
        time.sleep(0.5)
        child.sendline("y")

        # Email
        expect(child, "Email")
        time.sleep(0.5)
        type_slowly(child, EMAIL, delay=TYPING_DELAY)
        time.sleep(0.3)
        child.send("\r")
        status(f"entered email: {EMAIL}")

        # Password — send pre-collected (masked on screen)
        expect(child, "Password")
        time.sleep(0.5)
        child.sendline(password)
        status("sent password")

        # Wait for verification code to be sent
        expect(child, "Verification code sent")
        time.sleep(1)
        status("verification code sent")

        # === INTERACTIVE: wait for user to get code ===
        print("\n" + "=" * 50, file=sys.stderr)
        print("CHECK YOUR EMAIL for the verification code.", file=sys.stderr)
        print("Copy the code to your clipboard, then press Enter.", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        input()

        code = read_clipboard()
        status(f"got code from clipboard: {code[:2]}****")

        expect(child, "Enter verification code")
        time.sleep(0.5)
        child.sendline(code)
        status("sent verification code")

        expect(child, "Login successful")
        time.sleep(1)
        status("login successful")

        # Pick printer #1
        expect(child, "Pick a printer")
        time.sleep(0.5)
        child.sendline("1")

        expect(child, "Selected:")
        time.sleep(1)

        expect(child, "Wrote.*credentials")
        time.sleep(2)
        status("setup complete")
    finally:
        stop_recording(child)

        # Restore credentials backup
        if cred_backup:
            cred_path.parent.mkdir(parents=True, exist_ok=True)
            cred_path.write_text(cred_backup)
            cred_path.chmod(0o600)
            status("restored credentials backup")

    print(f"\nSetup recording saved to: {CAST_FILE}", file=sys.stderr)
    print(f"Play: asciinema play {CAST_FILE}", file=sys.stderr)


def main() -> None:
    print("=== fabprint setup recorder ===", file=sys.stderr)
    print(f"Email: {EMAIL}", file=sys.stderr)
    password = getpass.getpass("Bambu Cloud password (won't appear in recording): ")
    if not password:
        print("Password required.", file=sys.stderr)
        sys.exit(1)

    record_setup(password)


if __name__ == "__main__":
    main()
