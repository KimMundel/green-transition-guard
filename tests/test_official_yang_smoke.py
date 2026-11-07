"""Offline tests for the isolated, real-compiler CI smoke gate."""
from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import official_yang_smoke as smoke


def _module(name: str, date: str) -> str:
    return (f"module {name} {{\n  yang-version 1.1;\n"
            f'  namespace "urn:ietf:params:xml:ns:yang:{name}";\n'
            f"  prefix x;\n  revision {date} {{ description 'x'; }}\n}}")


def _inputs():
    data = {filename: _module(name, filename.split("@")[1].split(".")[0]).encode()
            for filename, name in smoke.DRAFT_MODULES.items() | smoke.IMPORTS.items()}
    xml = "<rfc>" + "".join(
        f'<sourcecode name="{name}">{data[name].decode()}</sourcecode>'
        for name in smoke.DRAFT_MODULES
    ) + "</rfc>"
    urls = {f"{smoke.BASE}/archive/id/{smoke.DRAFT}.xml": xml.encode()}
    for name in smoke.IMPORTS:
        urls[f"{smoke.BASE}/ietf-ftp/yang/catalogmod/{name}"] = data[name]
    return urls


def _runner(args, **kwargs):
    executable = args[0]
    if args[1] == "--version":
        return CompletedProcess(args, 0, stdout=f"{executable} test-version\n", stderr="")
    return CompletedProcess(args, 0, stdout="", stderr="warning: example")


def _run(tmp_path, **kwargs):
    urls = _inputs()
    return smoke.run(
        tmp_path / "evidence", repository=ROOT,
        fetch=lambda url: urls[url], which=lambda tool: tool,
        runner=_runner, **kwargs,
    )


def test_real_compiler_evidence_requires_both_compilers(tmp_path):
    assert _run(tmp_path) == 0
    output = tmp_path / "evidence"
    report = json.loads((output / "compiler-evidence.json").read_text())
    assert report["result"] == "passed"
    assert len(report["module_sha256"]) == 6
    assert report["tools"]["pyang"]["exit_code"] == 0
    assert report["tools"]["yanglint"]["exit_code"] == 0
    assert (output / "sources" / smoke.DRAFT_XML).exists()
    assert (output / "sources" / "augmentation.yang").read_bytes() == (ROOT / smoke.EXTENSION).read_bytes()


def test_fetch_failure_is_unverified_with_report(tmp_path):
    output = tmp_path / "evidence"
    assert smoke.run(output, repository=ROOT, fetch=lambda _: (_ for _ in ()).throw(smoke.ProbeError("offline"))) == 2
    report = json.loads((output / "compiler-evidence.json").read_text())
    assert report["result"] == "unverified" and report["tools"] == {}


def test_missing_compiler_is_unverified(tmp_path):
    urls = _inputs()
    output = tmp_path / "evidence"
    assert smoke.run(output, repository=ROOT, fetch=lambda u: urls[u],
                     which=lambda name: None if name == "yanglint" else name,
                     runner=_runner) == 2
    report = json.loads((output / "compiler-evidence.json").read_text())
    assert report["result"] == "unverified" and "yanglint missing" in report["reason"]


def test_failed_compiler_is_failed(tmp_path):
    urls = _inputs()

    def fail(args, **kwargs):
        if args[0] == "pyang" and args[1] != "--version":
            return CompletedProcess(args, 2, stdout="", stderr="schema error")
        return _runner(args, **kwargs)

    output = tmp_path / "evidence"
    assert smoke.run(output, repository=ROOT, fetch=lambda u: urls[u],
                     which=lambda name: name, runner=fail) == 1
    report = json.loads((output / "compiler-evidence.json").read_text())
    assert report["result"] == "failed" and report["tools"]["pyang"]["exit_code"] == 2
    assert report["tools"].get("yanglint") is None


def test_incomplete_draft_is_unverified(tmp_path):
    urls = _inputs()
    urls[f"{smoke.BASE}/archive/id/{smoke.DRAFT}.xml"] = b"<rfc/>"
    output = tmp_path / "evidence"
    assert smoke.run(output, repository=ROOT, fetch=lambda u: urls[u],
                     which=lambda name: name, runner=_runner) == 2
    report = json.loads((output / "compiler-evidence.json").read_text())
    assert report["result"] == "unverified"
    assert "missing" in report["reason"]


def test_preexisting_evidence_directory_rejected(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "prior.txt").write_text("do not overwrite")
    with pytest.raises(smoke.ProbeError):
        smoke.run(output, repository=ROOT)
    assert (output / "prior.txt").read_text() == "do not overwrite"


def test_linked_directory_rejected(tmp_path, monkeypatch):
    original = tmp_path / "elsewhere"
    original.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(original, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        # Unprivileged Windows cannot create symlinks. Exercise the exact
        # rejection branch without asking for elevation or Developer Mode.
        real_is_symlink = type(link).is_symlink
        monkeypatch.setattr(
            type(link), "is_symlink",
            lambda self: self == link or real_is_symlink(self),
        )
    with pytest.raises(smoke.ProbeError):
        smoke.run(link, repository=ROOT)
    assert list(original.iterdir()) == []


def test_symlink_privilege_denied_path_is_checked(tmp_path, monkeypatch):
    def deny_symlink(self, *args, **kwargs):
        exc = OSError("Windows symlink privilege unavailable")
        exc.winerror = 1314
        raise exc

    monkeypatch.setattr(type(tmp_path), "symlink_to", deny_symlink)
    test_linked_directory_rejected(tmp_path, monkeypatch)


def test_unexpected_symlink_error_propagates(tmp_path, monkeypatch):
    def deny_symlink(self, *args, **kwargs):
        raise PermissionError("Other symlink failure")

    monkeypatch.setattr(type(tmp_path), "symlink_to", deny_symlink)
    with pytest.raises(PermissionError, match="Other symlink failure"):
        test_linked_directory_rejected(tmp_path, monkeypatch)


def test_duplicate_sourcecode_rejected():
    urls = _inputs()
    xml = urls[f"{smoke.BASE}/archive/id/{smoke.DRAFT}.xml"].decode()
    repeated = f'<sourcecode name="{next(iter(smoke.DRAFT_MODULES))}">foo</sourcecode>'
    with pytest.raises(smoke.ProbeError):
        smoke.extract_draft(xml.replace("</rfc>", repeated + "</rfc>").encode())
