"""Offline contract tests; a real pyang/yanglint run is the GitHub CI gate."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import official_yang_06_smoke as release

VALID_SCHEMA = '''
module ietf-power-and-energy {
  import ietf-yang-types { prefix yang; }
  leaf source-component-id { type leafref {
    path "/hw:hardware/hw:component/hw:name";
  } }
  leaf total-energy-received { type yang:counter64; }
  leaf total-energy-provided { type yang:counter64; }
  leaf discontinuity-time { type yang:date-and-time; }
}
'''


def test_06_fields_are_required():
    release.validate_new_schema(VALID_SCHEMA)
    for old in (
        VALID_SCHEMA.replace('type yang:counter64', 'type uint64', 1),
        VALID_SCHEMA.replace('type yang:date-and-time', 'type string'),
        VALID_SCHEMA.replace('import ietf-yang-types', 'import ietf-inet-types'),
        VALID_SCHEMA.replace('/hw:hardware/hw:component/hw:name', '/hw:hardware/hw:component/hw:uuid'),
    ):
        with pytest.raises(release.ValidationError):
            release.validate_new_schema(old)


def synthetic_corpus(tmp_path):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    sample = {'ietf-power-and-energy:energy-objects': {
        'energy-object': [{'id': 'synthetic-eo-1', 'green-transition-guard-experimental:transition-safety':
                           {'operation-phase': 'idle'}}]}}
    (corpus / 'valid-idle.json').write_text(json.dumps(sample))
    return corpus


def test_06_new_cases_derive_from_existing_fixture(tmp_path):
    corpus = synthetic_corpus(tmp_path)
    cases = release.new_release_cases(corpus, tmp_path / 'generated')
    assert [case[1] for case in cases] == ['valid', 'invalid', 'invalid']
    assert len(cases) == 3
    for _, _, _, path, digest in cases:
        assert sha256(path.read_bytes()).hexdigest() == digest
        assert 'energy' in json.loads(path.read_bytes())['ietf-power-and-energy:energy-objects']['energy-object'][0]
    first = json.loads(cases[0][3].read_bytes())['ietf-power-and-energy:energy-objects']['energy-object'][0]
    assert first['energy']['total-energy-received'] == '18446744073709551615'
    assert 'energy' not in json.loads((corpus / 'valid-idle.json').read_bytes())['ietf-power-and-energy:energy-objects']['energy-object'][0]


def test_incorrect_base_fixture_identity_fails(tmp_path):
    corpus = synthetic_corpus(tmp_path)
    path = corpus / 'valid-idle.json'
    path.write_text(path.read_text().replace('synthetic-eo-1', 'different'))
    with pytest.raises(release.ValidationError, match='unexpected instance'):
        release.new_release_cases(corpus, tmp_path / 'cases')


def test_release_06_instance_gate_requires_correct_diagnostic(tmp_path, monkeypatch):
    corpus = synthetic_corpus(tmp_path)
    fake_baseline = corpus / 'invalid-phase.json'
    fake_baseline.write_text('{"bad":true}')
    old = [('idle', 'valid', 'valid-idle.json', corpus / 'valid-idle.json', 'sha-valid'),
           ('invalid-phase', 'invalid', 'invalid-phase.json', fake_baseline, 'sha-invalid')]
    monkeypatch.setattr(release.baseline, 'verify_corpus', lambda _: list(old))
    monkeypatch.setattr(release.baseline, 'diagnostic_matches', lambda case, diagnostic: 'running' in diagnostic)
    sources = tmp_path / 'sources'
    sources.mkdir()
    report = {'tools': {'yanglint': {'version': 'yanglint 2.1.30'}}}

    def runner(cmd, **kwargs):
        if '--version' in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='yanglint 2.1.30', stderr='')
        name = Path(cmd[-1]).name
        if name in ('valid-idle.json', 'energy-counter-and-discontinuity.json'):
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        detail = ('running' if name == 'invalid-phase.json'
                  else 'discontinuity-time' if 'discontinuity' in name
                  else 'total-energy-received')
        return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='libyang err : ' + detail)

    records = release.validate_instances(sources, report, corpus, tmp_path / 'output',
                                         which=lambda _: '/usr/bin/yanglint', runner=runner)
    assert len(records) == 5 and all(record['matched'] for record in records)


def test_wrong_negative_diagnostic_fails_closed(tmp_path, monkeypatch):
    corpus = synthetic_corpus(tmp_path)
    monkeypatch.setattr(release.baseline, 'verify_corpus', lambda _: [])
    sources = tmp_path / 'sources'
    sources.mkdir()
    report = {'tools': {'yanglint': {'version': 'yanglint 2.1.30'}}}

    def runner(cmd, **kwargs):
        if '--version' in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='yanglint 2.1.30', stderr='')
        name = Path(cmd[-1]).name
        return subprocess.CompletedProcess(cmd, 0 if name.startswith('energy-counter') else 1,
                                           stdout='', stderr='libyang err : unrelated schema failure')

    with pytest.raises(release.ValidationError, match='invalid-discontinuity-time'):
        release.validate_instances(sources, report, corpus, tmp_path / 'output',
                                   which=lambda _: '/usr/bin/yanglint', runner=runner)


def test_report_correctly_distinguishes_failed_compilation(tmp_path):
    result = release.run(tmp_path / 'output', tmp_path, tmp_path,
                         compiler_run=lambda out, **kwargs: 1)
    assert result == 1
    evidence = json.loads((tmp_path / 'output' / 'evidence.json').read_text())
    assert evidence['status'] == 'failed'
    assert evidence['draft'] == release.DRAFT_06


def test_wrong_compiler_report_rejected(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    schema = tmp_path / 'schema'
    schema.mkdir()
    (schema / 'compiler-evidence.json').write_text(json.dumps({
        'format': 'green-official-yang-smoke-1', 'draft': 'draft-ietf-green-power-and-energy-yang-05',
        'result': 'passed', 'reason': None,
    }))
    with pytest.raises(release.ValidationError, match='wrong draft'):
        release.verify_compilation(schema, repo)


def test_no_reuse_of_prior_output(tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'file').write_text('exists')
    assert release.run(output, tmp_path, tmp_path, compiler_run=lambda *a, **kw: 0) == 2
    assert not (output / 'evidence.json').exists()


def test_synthetic_counter_overflow_never_becomes_accepted_when_validator_rejects(tmp_path, monkeypatch):
    corpus = synthetic_corpus(tmp_path)
    monkeypatch.setattr(release.baseline, 'verify_corpus', lambda _: [])
    sources = tmp_path / 'sources'
    sources.mkdir()
    report = {'tools': {'yanglint': {'version': 'yanglint 2.1.30'}}}

    def runner(cmd, **kwargs):
        if '--version' in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout='yanglint 2.1.30', stderr='')
        name = Path(cmd[-1]).name
        if name == 'energy-counter-and-discontinuity.json':
            return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
        if name == 'invalid-discontinuity-time.json':
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='libyang err : /energy/discontinuity-time')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    with pytest.raises(release.ValidationError, match='invalid-counter64-overflow'):
        release.validate_instances(sources, report, corpus, tmp_path / 'output',
                                   which=lambda _: '/usr/bin/yanglint', runner=runner)


def test_original_05_constants_survive_06_runner(tmp_path):
    original = (release.compiler.DRAFT, release.compiler.DRAFT_XML,
                release.compiler.IMPORTS.copy())
    assert release.run(tmp_path / 'output', tmp_path, tmp_path,
                       compiler_run=lambda output, **kwargs: 1) == 1
    assert (release.compiler.DRAFT, release.compiler.DRAFT_XML,
            release.compiler.IMPORTS) == original
