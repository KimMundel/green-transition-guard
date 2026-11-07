#!/usr/bin/env python3
"""Standalone real-compiler probe for the pinned, experimental GREEN augmentation.

This narrow CI gate can run on older repository branches. It deliberately
checks schema compilation only; RFC 7951 instance conformance is a separate
milestone. All source bytes, tool exits and bounded diagnostics are retained.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.request import urlopen
from xml.etree import ElementTree

DRAFT = "draft-ietf-green-power-and-energy-yang-05"
DRAFT_XML = f"{DRAFT}.xml"
BASE = "https://www.ietf.org"
EXTENSION = "yang/green-transition-guard-experimental@2026-11-04.yang"
DRAFT_MODULES = {
    "ietf-power-and-energy@2026-11-01.yang": "ietf-power-and-energy",
    "iana-power-and-energy@2026-11-01.yang": "iana-power-and-energy",
}
IMPORTS = {
    "ietf-hardware@2018-03-13.yang": "ietf-hardware",
    "iana-hardware@2018-03-13.yang": "iana-hardware",
    "ietf-inet-types@2013-07-15.yang": "ietf-inet-types",
    "ietf-yang-types@2013-07-15.yang": "ietf-yang-types",
}
MAX_BYTES = 4_000_000


class ProbeError(Exception):
    """Source or execution cannot establish a verified compiler result."""


def fetch_url(url: str) -> bytes:
    if not url.startswith(BASE + "/"):
        raise ProbeError("source URL must be on the fixed IETF host")
    with urlopen(url, timeout=25) as response:
        if not response.geturl().startswith(BASE + "/"):
            raise ProbeError("redirect leaves fixed IETF host")
        data = response.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise ProbeError("source is empty or oversized")
    return data


def check_module(filename: str, data: bytes, name: str) -> None:
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProbeError("non-UTF-8 module") from exc
    revision = filename.split("@", 1)[1].removesuffix(".yang")
    if not re.search(rf"\bmodule\s+{re.escape(name)}\s*\{{", source):
        raise ProbeError(f"unexpected module name in {filename}")
    if not re.search(rf"\brevision\s+{re.escape(revision)}\s*\{{", source):
        raise ProbeError(f"unexpected module revision in {filename}")
    if not re.search(r"\bnamespace\s+['\"]urn:ietf:params:xml:ns:yang:" +
                     re.escape(name) + r"['\"]\s*;", source):
        raise ProbeError(f"unexpected namespace in {filename}")


def extract_draft(xml: bytes) -> dict[str, bytes]:
    if not xml or len(xml) > MAX_BYTES:
        raise ProbeError("draft XML missing or oversized")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ProbeError("invalid draft XML") from exc
    result: dict[str, bytes] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"sourcecode", "artwork"}:
            continue
        filename = node.get("name") or node.get("filename")
        if filename not in DRAFT_MODULES:
            continue
        if filename in result:
            raise ProbeError("duplicate draft module")
        data = ("".join(node.itertext()).strip("\r\n") + "\n").encode("utf-8")
        check_module(filename, data, DRAFT_MODULES[filename])
        result[filename] = data
    if set(result) != set(DRAFT_MODULES):
        raise ProbeError("draft missing required named module sources")
    return result


def run(output: Path, *, repository: Path, fetch=fetch_url,
        which=shutil.which, runner=subprocess.run) -> int:
    """Capture enough data to distinguish success, failure and missing proof."""
    report: dict = {
        "format": "green-official-yang-smoke-1", "draft": DRAFT,
        "draft_sha256": None, "extension_sha256": None,
        "module_sha256": {}, "tools": {}, "result": "unverified", "reason": None,
        "scope": "schema-compilation-only; not instance-conformance or IETF approval",
    }
    if output.is_symlink():
        raise ProbeError("output must be a real directory")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ProbeError("output must be empty")
    report_path = output / "compiler-evidence.json"
    try:
        extension = repository / EXTENSION
        if extension.is_symlink() or not extension.is_file():
            raise ProbeError("experimental augmentation missing or linked")
        extension_bytes = extension.read_bytes()
        if not extension_bytes or len(extension_bytes) > MAX_BYTES:
            raise ProbeError("invalid augmentation bytes")
        report["extension_sha256"] = sha256(extension_bytes).hexdigest()
        draft_url = f"{BASE}/archive/id/{DRAFT}.xml"
        xml = fetch(draft_url)
        draft_modules = extract_draft(xml)
        others = {}
        for filename, name in IMPORTS.items():
            data = fetch(f"{BASE}/ietf-ftp/yang/catalogmod/{filename}")
            check_module(filename, data, name)
            others[filename] = data
        modules = draft_modules | others
        report["draft_sha256"] = sha256(xml).hexdigest()
        report["module_sha256"] = {
            filename: sha256(data).hexdigest() for filename, data in sorted(modules.items())
        }
        directory = output / "sources"
        directory.mkdir()
        (directory / DRAFT_XML).write_bytes(xml)
        for filename, data in modules.items():
            (directory / filename).write_bytes(data)
        (directory / "augmentation.yang").write_bytes(extension_bytes)
        (directory / "manifest.json").write_text(json.dumps({
            "draft": DRAFT, "draft_url": draft_url,
            "draft_sha256": report["draft_sha256"],
            "module_sha256": report["module_sha256"],
            "extension_sha256": report["extension_sha256"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for tool in ("pyang", "yanglint"):
            executable = which(tool)
            if not executable:
                raise ProbeError(f"{tool} missing")
            version = runner([executable, "--version"], capture_output=True, text=True, timeout=10)
            version_text = (version.stdout or version.stderr).strip()
            if version.returncode != 0 or not re.fullmatch(rf"{tool} [^\r\n]{{1,120}}", version_text):
                raise ProbeError(f"{tool} version could not be established")
            if tool == "pyang":
                args = [executable, "--strict", "-p", str(directory), str(directory / "augmentation.yang")]
            else:
                args = [executable, "-p", str(directory),
                        str(directory / "ietf-power-and-energy@2026-11-01.yang"),
                        str(directory / "augmentation.yang")]
            result = runner(args, capture_output=True, text=True, timeout=60)
            if type(result.returncode) is not int or result.returncode < 0:
                raise ProbeError(f"{tool} did not finish")
            report["tools"][tool] = {
                "version": version_text, "exit_code": result.returncode,
                "stdout": result.stdout[:4096], "stderr": result.stderr[:4096],
            }
            if result.returncode != 0:
                report["result"] = "failed"
                report["reason"] = f"{tool} rejected the schema"
                return 1
        report["result"] = "passed"
        return 0
    except (ProbeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        report["reason"] = str(exc)[:300]
        return 2
    finally:
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"GREEN YANG compiler result: {report['result']}")
        if report["reason"]:
            print(report["reason"], file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    options = parser.parse_args()
    return run(options.output, repository=options.repository)


if __name__ == "__main__":
    raise SystemExit(main())
