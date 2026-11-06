#!/usr/bin/env python3
"""Backportable 14-case RFC 7951 gate for the verified GREEN -05 smoke sources.

Uses *actual* yanglint; a passing compiler-only smoke is required first.
This is schema/instance interoperability evidence, never device certification.
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

from official_yang_smoke import DRAFT, DRAFT_XML, DRAFT_MODULES, IMPORTS, EXTENSION, extract_draft

PINNED_DRAFT_SHA256 = 'd5c6ac62f1e13c59c448c9252667ff206623c3b86bf30fc2e98a081bd24414eb'
PINNED_EXTENSION_SHA256 = '15360eb4b29533939e0c7b4242567f7f84ba8e2ce6d6a7728d18015c934f7328'
PINNED_CORPUS_SHA256 = '86e15fc664b99cca0ef6abf8aa48ff13b1b5ba5bdb718009223a6e43b64e78ce'
EXPECTED_VALID = ('idle', 'prepared', 'acknowledged', 'reconciled', 'quarantined')
EXPECTED_INVALID = (
    'invalid-phase', 'invalid-ledger-enum', 'unknown-identity', 'invalid-uint64',
    'zero-window', 'unknown-augmented-leaf', 'missing-energy-object-key',
    'duplicate-dwell-key', 'invalid-augmentation-namespace',
)
FILENAME = lambda expectation, name: (
    f'{name}.json' if expectation == 'invalid' and name.startswith('invalid-')
    else f'{expectation}-{name}.json'
)
MAX_CASE_BYTES = 64_000


class EvidenceError(ValueError):
    """A true instance-validation result cannot be established."""


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def load_json(data: bytes):
    def no_duplicates(pairs):
        value = {}
        for key, element in pairs:
            if key in value:
                raise EvidenceError('duplicate JSON key')
            value[key] = element
        return value
    try:
        return json.loads(data, object_pairs_hook=no_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError('invalid JSON') from exc


def regular_file(path: Path, limit: int = 4_000_000) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f'missing or linked file: {path.name}')
    data = path.read_bytes()
    if not data or len(data) > limit:
        raise EvidenceError(f'empty or oversized file: {path.name}')
    return data


def verify_corpus(root: Path) -> list[tuple[str, str, str, Path, str]]:
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError('missing or linked instance corpus')
    manifest_bytes = regular_file(root / 'manifest.json', MAX_CASE_BYTES)
    if digest(manifest_bytes) != PINNED_CORPUS_SHA256:
        raise EvidenceError('instance corpus manifest differs from pinned review')
    manifest = load_json(manifest_bytes)
    expected = [
        (name, expectation, FILENAME(expectation, name))
        for expectation, names in (('valid', EXPECTED_VALID), ('invalid', EXPECTED_INVALID))
        for name in names
    ]
    entries = manifest.get('cases')
    if (manifest.get('format') != 'green-yang-instance-corpus-1'
            or manifest.get('draft') != DRAFT
            or manifest.get('experimental_module') != Path(EXTENSION).name
            or not isinstance(entries, list) or len(entries) != len(expected)):
        raise EvidenceError('unexpected instance corpus schema')
    if {p.name for p in root.iterdir()} != {name for _, _, name in expected} | {'manifest.json'}:
        raise EvidenceError('unexpected instance corpus inventory')
    cases = []
    for record, (case, expected_result, filename) in zip(entries, expected):
        if (type(record) is not dict or set(record) != {'case', 'expected', 'file', 'sha256'}
                or record['case'] != case or record['expected'] != expected_result
                or record['file'] != filename):
            raise EvidenceError('instance corpus case order/identity differs')
        data = regular_file(root / filename, MAX_CASE_BYTES)
        if digest(data) != record['sha256']:
            raise EvidenceError(f'instance bytes differ: {filename}')
        if not isinstance(load_json(data), dict):
            raise EvidenceError(f'instance is not a JSON object: {filename}')
        cases.append((case, expected_result, filename, root / filename, digest(data)))
    return cases


def verify_smoke(root: Path, repo: Path) -> tuple[Path, dict]:
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError('missing or linked source smoke output')
    report = load_json(regular_file(root / 'compiler-evidence.json', MAX_CASE_BYTES))
    if (report.get('format') != 'green-official-yang-smoke-1'
            or report.get('result') != 'passed' or report.get('reason') is not None
            or report.get('draft') != DRAFT
            or report.get('draft_sha256') != PINNED_DRAFT_SHA256
            or report.get('extension_sha256') != PINNED_EXTENSION_SHA256):
        raise EvidenceError('compiler-only evidence incomplete or wrong revision')
    for tool in ('pyang', 'yanglint'):
        item = report.get('tools', {}).get(tool)
        if (not isinstance(item, dict) or type(item.get('exit_code')) is not int
                or item['exit_code'] != 0
                or not str(item.get('version', '')).startswith(tool + ' ')):
            raise EvidenceError(f'{tool} compiler evidence invalid')
    sources = root / 'sources'
    if sources.is_symlink() or not sources.is_dir():
        raise EvidenceError('missing or linked smoke sources')
    needed = set(DRAFT_MODULES) | set(IMPORTS)
    expected_files = needed | {DRAFT_XML, 'augmentation.yang', 'manifest.json'}
    if {p.name for p in sources.iterdir()} != expected_files:
        raise EvidenceError('unexpected official source files')
    xml = regular_file(sources / DRAFT_XML)
    if digest(xml) != PINNED_DRAFT_SHA256:
        raise EvidenceError('published draft bytes changed')
    embedded = extract_draft(xml)
    hashes = report.get('module_sha256')
    if type(hashes) is not dict or set(hashes) != needed:
        raise EvidenceError('source hash inventory mismatch')
    for filename in sorted(needed):
        data = regular_file(sources / filename)
        if digest(data) != hashes[filename]:
            raise EvidenceError(f'official module fingerprint mismatch: {filename}')
        if filename in embedded and data != embedded[filename]:
            raise EvidenceError('stored module differs from original draft XML')
    extension = regular_file(repo / EXTENSION)
    if digest(extension) != PINNED_EXTENSION_SHA256:
        raise EvidenceError('local augmentation differs from compiler evidence')
    if regular_file(sources / 'augmentation.yang') != extension:
        raise EvidenceError('compiled augmentation differs from local schema')
    source_manifest = load_json(regular_file(sources / 'manifest.json', MAX_CASE_BYTES))
    if (source_manifest.get('draft_sha256') != PINNED_DRAFT_SHA256
            or source_manifest.get('module_sha256') != hashes
            or source_manifest.get('extension_sha256') != PINNED_EXTENSION_SHA256):
        raise EvidenceError('smoke source manifest differs from compiler report')
    return sources, report


def validate(smoke: Path, corpus: Path, repo: Path, *, which=shutil.which,
             runner=subprocess.run) -> dict:
    """Validate the fixed corpus with real yanglint; rejects fake/interrupted results."""
    cases = verify_corpus(corpus)
    sources, compilation = verify_smoke(smoke, repo)
    executable = which('yanglint')
    if not executable:
        raise EvidenceError('yanglint executable missing')
    try:
        version = runner([executable, '--version'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceError('yanglint version command unavailable') from exc
    version_text = (version.stdout or version.stderr).strip()
    if (type(version.returncode) is not int or version.returncode != 0
            or not re.fullmatch(r'yanglint [^\r\n]{1,120}', version_text)
            or version_text != compilation['tools']['yanglint']['version']):
        raise EvidenceError('yanglint version changed since compiler-only run')
    records = []
    for case, expectation, filename, path, fingerprint in cases:
        command = [executable, '-p', str(sources), '-t', 'data', '-e',
                   str(sources / 'ietf-power-and-energy@2026-11-01.yang'),
                   str(sources / 'augmentation.yang'), str(path)]
        try:
            outcome = runner(command, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EvidenceError(f'yanglint process unavailable: {case}') from exc
        if type(outcome.returncode) is not int or outcome.returncode < 0:
            raise EvidenceError(f'yanglint process interrupted: {case}')
        accepted = outcome.returncode == 0
        expected_acceptance = expectation == 'valid'
        entry = {'case': case, 'expected': expectation, 'file': filename,
                 'instance_sha256': fingerprint, 'exit_code': outcome.returncode,
                 'matched': accepted == expected_acceptance,
                 'stderr': (outcome.stderr or '')[:1200]}
        records.append(entry)
        if accepted != expected_acceptance:
            raise ValidationMismatch(f'yanglint {"rejected valid" if expected_acceptance else "accepted invalid"} case: {case}', records)
    return {'cases': records, 'yanglint_version': version_text,
            'source_draft_sha256': compilation['draft_sha256'],
            'extension_sha256': compilation['extension_sha256'],
            'corpus_manifest_sha256': PINNED_CORPUS_SHA256}


class ValidationMismatch(EvidenceError):
    def __init__(self, message: str, cases: list[dict]):
        super().__init__(message)
        self.cases = cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-output', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--corpus', type=Path, default=Path(__file__).resolve().parents[1] / 'conformance' / 'yang-instances')
    args = parser.parse_args(argv)
    if args.output.is_symlink() or (args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir()))):
        print('UNVERIFIED: output must be a real empty directory', file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {'format': 'green-official-yang-instances-1', 'result': 'unverified',
                'scope': 'fixed 14-case synthetic RFC 7951 corpus; no IETF endorsement or physical validation',
                'reason': None, 'cases': []}
    code = 2
    try:
        details = validate(args.smoke_output, args.corpus, args.repository)
        evidence.update(details)
        evidence['result'] = 'passed'
        code = 0
    except ValidationMismatch as exc:
        evidence['result'] = 'failed'
        evidence['reason'] = str(exc)
        evidence['cases'] = exc.cases
        code = 1
    except (OSError, EvidenceError, KeyError, TypeError) as exc:
        evidence['reason'] = str(exc)[:300]
    finally:
        (args.output / 'instance-evidence.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f"GREEN YANG instance result: {evidence['result']}")
    if evidence['reason']:
        print(evidence['reason'], file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
