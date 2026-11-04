#!/usr/bin/env python3
"""Fail-closed external YANG compile gate, using authoritative source files.

Example:
  python scripts/validate_yang.py --modules /path/to/official/yang

The official GREEN -05 module and all its imported dependencies must be
provided by the caller. Absence of pyang or dependencies is a FAIL, never
reported as successful YANG validation. yanglint runs if installed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def validate(modules: Path, *, binary_lookup=shutil.which, runner=subprocess.run) -> int:
    here = Path(__file__).resolve().parents[1]
    extension = here / "yang" / "green-transition-guard-experimental@2026-11-04.yang"
    official = modules / "ietf-power-and-energy@2026-11-01.yang"
    if not extension.is_file() or not official.is_file():
        print("UNVERIFIED: expected experimental and authoritative GREEN source missing", file=sys.stderr)
        return 2
    body = official.read_text(encoding="utf-8")
    if "module ietf-power-and-energy" not in body or "revision 2026-11-01" not in body:
        print("UNVERIFIED: source module identity/revision mismatch", file=sys.stderr)
        return 2
    pyang = binary_lookup("pyang")
    if not pyang:
        print("UNVERIFIED: pyang missing", file=sys.stderr)
        return 2
    cmd = [pyang, "--strict", "-p", str(modules), str(extension)]
    result = runner(cmd, capture_output=True, text=True)
    if result.returncode:
        print("FAIL: pyang validation", file=sys.stderr)
        print(result.stdout + result.stderr, file=sys.stderr)
        return 1
    yanglint = binary_lookup("yanglint")
    if yanglint:
        # Explicit dependency directory avoids accepting a wrong revision.
        result = runner([yanglint, "-p", str(modules), str(official), str(extension)],
                        capture_output=True, text=True)
        if result.returncode:
            print("FAIL: yanglint validation", file=sys.stderr)
            print(result.stdout + result.stderr, file=sys.stderr)
            return 1
    print("COMPILED: pyang passed" + ("; yanglint passed" if yanglint else "; yanglint absent"))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", type=Path, required=True,
                        help="Directory holding pinned official YANG modules and imports")
    args = parser.parse_args()
    raise SystemExit(validate(args.modules))
