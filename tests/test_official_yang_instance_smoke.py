"""Offline *synthetic* contract tests. They do not claim a real yanglint result."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import official_yang_instance_smoke as gate
import official_yang_smoke as smoke

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / 'conformance' / 'yang-instances'


def fixture_smoke(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / 'smoke'
    sources = root / 'sources'
    sources.mkdir(parents=True)
    xml_root = Element('rfc')
    modules = {}
    for filename, name in smoke.DRAFT_MODULES.items():
        entry = SubElement(xml_root, 'sourcecode', {'name': filename})
        content = (f'module {name} {{ namespace '
                   f'"urn:ietf:params:xml:ns:yang:{name}"; '
                   f'prefix x; revision 2026-11-01 {{}} }}')
        entry.text = content
        modules[filename] = (content + '\n').encode()
    xml = tostring(xml_root)
    (sources / smoke.DRAFT_XML).write_bytes(xml)
    for name in smoke.IMPORTS:
        modules[name] = (f'module {smoke.IMPORTS[name]} {{ }}\n').encode()
    hashes = {}
    for name, data in modules.items():
        (sources / name).write_bytes(data)
        hashes[name] = sha256(data).hexdigest()
    extension = (REPO / smoke.EXTENSION).read_bytes()
    (sources / 'augmentation.yang').write_bytes(extension)
    draft_hash = sha256(xml).hexdigest()
    extension_hash = sha256(extension).hexdigest()
    (sources / 'manifest.json').write_text(json.dumps({
        'draft_sha256': draft_hash,
        'module_sha256': hashes,
        'extension_sha256': extension_hash,
    }), encoding='utf-8')
    (root / 'compiler-evidence.json').write_text(json.dumps({
        'format': 'green-official-yang-smoke-1', 'result': 'passed',
        'reason': None, 'draft': smoke.DRAFT, 'draft_sha256': draft_hash,
        'extension_sha256': extension_hash, 'module_sha256': hashes,
        'tools': {
            'pyang': {'version': 'pyang 2.7.1', 'exit_code': 0},
            'yanglint': {'version': 'yanglint 2.1.30', 'exit_code': 0},
        },
    }), encoding='utf-8')
    monkeypatch.setattr(gate, 'PINNED_DRAFT_SHA256', draft_hash)
    monkeypatch.setattr(gate, 'PINNED_EXTENSION_SHA256', extension_hash)
    return root


def fake_runner(*, invert_case: str | None = None, signal: bool = False, version='yanglint 2.1.30'):
    def execute(command, **kwargs):
        if '--version' in command:
            return subprocess.CompletedProcess(command, 0, stdout=version + '\n', stderr='')
        filename = Path(command[-1]).name
        is_valid = filename.startswith('valid-')
        if invert_case == filename:
            is_valid = not is_valid
        return subprocess.CompletedProcess(command, -9 if signal else (0 if is_valid else 1),
                                           stdout='', stderr='synthetic diagnostic')
    return execute


def test_review_corpus_is_pinned():
    actual = gate.verify_corpus(CORPUS)
    assert len(actual) == 14
    assert sum(case[1] == 'valid' for case in actual) == 5
    assert sum(case[1] == 'invalid' for case in actual) == 9


def test_verified_compiler_sources_are_required(tmp_path, monkeypatch):
    root = fixture_smoke(tmp_path, monkeypatch)
    assert len(gate.verify_smoke(root, REPO)[1]['module_sha256']) == 6
    report = root / 'compiler-evidence.json'
    data = json.loads(report.read_text())
    data['tools']['yanglint']['exit_code'] = 1
    report.write_text(json.dumps(data))
    with pytest.raises(gate.EvidenceError, match='compiler evidence'):
        gate.verify_smoke(root, REPO)


def test_passing_14_case_contract(tmp_path, monkeypatch):
    root = fixture_smoke(tmp_path, monkeypatch)
    result = gate.validate(root, CORPUS, REPO, which=lambda _: '/synthetic/yanglint', runner=fake_runner())
    assert len(result['cases']) == 14
    assert all(item['matched'] for item in result['cases'])
    assert result['corpus_manifest_sha256'] == gate.PINNED_CORPUS_SHA256


@pytest.mark.parametrize('filename', ['valid-idle.json', 'invalid-phase.json'])
def test_altered_fixture_fails_before_validator(tmp_path, monkeypatch, filename):
    root = fixture_smoke(tmp_path, monkeypatch)
    modified = tmp_path / 'review'
    shutil.copytree(CORPUS, modified)
    (modified / filename).write_text('{"altered":true}')
    with pytest.raises(gate.EvidenceError, match='instance bytes differ'):
        gate.validate(root, modified, REPO, which=lambda _: '/synthetic/yanglint', runner=fake_runner())


@pytest.mark.parametrize('filename,reason', [
    ('valid-idle.json', 'rejected valid'),
    ('invalid-phase.json', 'accepted invalid'),
])
def test_mismatched_acceptance_fails(tmp_path, monkeypatch, filename, reason):
    root = fixture_smoke(tmp_path, monkeypatch)
    with pytest.raises(gate.ValidationMismatch, match=reason) as exc:
        gate.validate(root, CORPUS, REPO, which=lambda _: '/synthetic/yanglint',
                      runner=fake_runner(invert_case=filename))
    assert exc.value.cases[-1]['matched'] is False


def test_version_drift_and_missing_binary_fail_closed(tmp_path, monkeypatch):
    root = fixture_smoke(tmp_path, monkeypatch)
    with pytest.raises(gate.EvidenceError, match='executable missing'):
        gate.validate(root, CORPUS, REPO, which=lambda _: None, runner=fake_runner())
    with pytest.raises(gate.EvidenceError, match='version changed'):
        gate.validate(root, CORPUS, REPO, which=lambda _: '/synthetic/yanglint',
                      runner=fake_runner(version='yanglint 9.9'))


def test_interrupted_validator_is_unverified(tmp_path, monkeypatch):
    root = fixture_smoke(tmp_path, monkeypatch)
    with pytest.raises(gate.EvidenceError, match='process interrupted'):
        gate.validate(root, CORPUS, REPO, which=lambda _: '/synthetic/yanglint',
                      runner=fake_runner(signal=True))


def test_forged_source_module_is_rejected(tmp_path, monkeypatch):
    root = fixture_smoke(tmp_path, monkeypatch)
    file = root / 'sources' / 'ietf-power-and-energy@2026-11-01.yang'
    file.write_bytes(file.read_bytes() + b'\n// forged')
    with pytest.raises(gate.EvidenceError, match='fingerprint mismatch'):
        gate.verify_smoke(root, REPO)


def test_duplicate_keys_are_rejected():
    with pytest.raises(gate.EvidenceError, match='duplicate JSON key'):
        gate.load_json(b'{"x":0,"x":1}')


def test_no_report_means_no_pass(tmp_path, monkeypatch):
    root = fixture_smoke(tmp_path, monkeypatch)
    (root / 'compiler-evidence.json').unlink()
    output = tmp_path / 'result'
    assert gate.main(['--smoke-output', str(root), '--output', str(output),
                      '--repository', str(REPO), '--corpus', str(CORPUS)]) == 2
    report = json.loads((output / 'instance-evidence.json').read_text())
    assert report['result'] == 'unverified'
    assert not report['cases']
