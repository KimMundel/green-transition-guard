#!/usr/bin/env python3
"""Compile published GREEN Power/Energy YANG -06, then validate RFC 7951 instances.

Runs alongside the unchanged, release-pinned -05 validation. The two drafts
share module revision 2026-11-01 but contain different source bytes, so they
MUST be compiled in separate directories.

All input data are synthetic and no hardware is accessed or authorized.
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

import official_yang_smoke as compiler
import official_yang_instance_smoke as baseline

DRAFT_06 = 'draft-ietf-green-power-and-energy-yang-06'
DRAFT_XML_06 = DRAFT_06 + '.xml'
MODULE = 'ietf-power-and-energy@2026-11-01.yang'
MAX_BYTES = 4_000_000


class ValidationError(ValueError):
    """Evidence does not establish the requested validation result."""


def read_regular(path: Path, maximum: int = MAX_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValidationError(f'missing/linked file: {path.name}')
    data = path.read_bytes()
    if not data or len(data) > maximum:
        raise ValidationError(f'empty/oversized file: {path.name}')
    return data


def validate_new_schema(source: str) -> None:
    """Reject a stale -05 module accidentally returned from the -06 URL."""
    if not re.search(r'\bimport\s+ietf-yang-types\s*\{', source):
        raise ValidationError('-06 module lacks ietf-yang-types import')
    for leaf in ('total-energy-received', 'total-energy-provided'):
        if not re.search(r'\bleaf\s+' + leaf + r'\s*\{\s*type\s+yang:counter64\s*;', source):
            raise ValidationError(f'-06 expected counter64 leaf missing: {leaf}')
    if not re.search(r'\bleaf\s+discontinuity-time\s*\{\s*type\s+yang:date-and-time\s*;', source):
        raise ValidationError('-06 discontinuity-time leaf missing or wrong type')
    if not re.search(r'\bleaf\s+source-component-id\s*\{\s*type\s+leafref\s*\{\s*path\s+[\'\"]'
                     r'/hw:hardware/hw:component/hw:name[\'\"]\s*;', source):
        raise ValidationError('-06 hardware component name leafref is missing')


def verify_compilation(root: Path, repo: Path) -> tuple[Path, dict]:
    """Check every retained source and compiler result before invoking yanglint."""
    if root.is_symlink() or not root.is_dir():
        raise ValidationError('missing compiler output')
    report = json.loads(read_regular(root / 'compiler-evidence.json'))
    if (report.get('format') != 'green-official-yang-smoke-1'
            or report.get('draft') != DRAFT_06 or report.get('result') != 'passed'
            or report.get('reason') is not None):
        raise ValidationError('wrong draft or incomplete compiler evidence')
    expected = set(compiler.DRAFT_MODULES) | set(compiler.IMPORTS)
    digests = report.get('module_sha256')
    if not isinstance(digests, dict) or set(digests) != expected:
        raise ValidationError('compiler source inventory changed')
    sources = root / 'sources'
    if sources.is_symlink() or not sources.is_dir():
        raise ValidationError('missing compiler sources')
    if {p.name for p in sources.iterdir()} != expected | {DRAFT_XML_06, 'augmentation.yang', 'manifest.json'}:
        raise ValidationError('unexpected source file inventory')
    xml = read_regular(sources / DRAFT_XML_06)
    if sha256(xml).hexdigest() != report.get('draft_sha256'):
        raise ValidationError('draft bytes differ from compiled evidence')
    embedded = compiler.extract_draft(xml)
    validate_new_schema(embedded[MODULE].decode('utf-8'))
    for name in expected:
        data = read_regular(sources / name)
        if sha256(data).hexdigest() != digests[name] or (name in embedded and data != embedded[name]):
            raise ValidationError(f'module/source checksum mismatch: {name}')
    ext = read_regular(repo / compiler.EXTENSION)
    if sha256(ext).hexdigest() != baseline.PINNED_EXTENSION_SHA256:
        raise ValidationError('experimental YANG extension changed since baseline review')
    if read_regular(sources / 'augmentation.yang') != ext:
        raise ValidationError('compiled extension differs from reviewed source')
    manifest = json.loads(read_regular(sources / 'manifest.json'))
    if (manifest.get('draft') != DRAFT_06 or manifest.get('draft_sha256') != report['draft_sha256']
            or manifest.get('module_sha256') != digests
            or manifest.get('extension_sha256') != report['extension_sha256']):
        raise ValidationError('source manifest differs from compiler evidence')
    for tool in ('pyang', 'yanglint'):
        details = report.get('tools', {}).get(tool)
        if (not isinstance(details, dict) or type(details.get('exit_code')) is not int
                or details['exit_code'] != 0 or not str(details.get('version', '')).startswith(tool + ' ')):
            raise ValidationError(f'{tool} result not verified')
    return sources, report


def new_release_cases(corpus: Path, output: Path) -> list[tuple[str, str, str, Path, str]]:
    """Derive -06-specific cases from one of the unchanged, pinned -05 fixtures."""
    base = json.loads(read_regular(corpus / 'valid-idle.json', 64_000))
    entry = base['ietf-power-and-energy:energy-objects']['energy-object'][0]
    if entry.get('id') != 'synthetic-eo-1':
        raise ValidationError('unexpected instance base object')
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    for name, expectation, counters in (
        ('energy-counter-and-discontinuity', 'valid', {
            'total-energy-received': '18446744073709551615',
            'total-energy-provided': '0',
            'discontinuity-time': '2026-11-15T00:00:00Z',
        }),
        ('invalid-discontinuity-time', 'invalid', {
            'total-energy-received': '1',
            'discontinuity-time': 'not-a-date',
        }),
        ('invalid-counter64-overflow', 'invalid', {
            'total-energy-received': '18446744073709551616',
            'discontinuity-time': '2026-11-15T00:00:00Z',
        }),
    ):
        data = json.loads(json.dumps(base))
        data['ietf-power-and-energy:energy-objects']['energy-object'][0]['energy'] = counters
        raw = (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
        path = output / (name + '.json')
        path.write_bytes(raw)
        cases.append((name, expectation, path.name, path, sha256(raw).hexdigest()))
    return cases


def validate_instances(sources: Path, report: dict, corpus: Path, output: Path, *,
                       which=shutil.which, runner=subprocess.run) -> list[dict]:
    """Enforce same exact diagnostics as -05, plus scoped -06 negative cases."""
    # The historic corpus remains pinned to -05 intentionally; its fourteen
    # cases are replayed unchanged under the -06 schema as compatibility tests.
    cases = baseline.verify_corpus(corpus)
    cases += new_release_cases(corpus, output / 'new-release-cases')
    executable = which('yanglint')
    if not executable:
        raise ValidationError('yanglint unavailable')
    v = runner([executable, '--version'], capture_output=True, text=True, timeout=10)
    version = (v.stdout or v.stderr).strip()
    if v.returncode != 0 or version != report['tools']['yanglint']['version']:
        raise ValidationError('yanglint version changed between compiler and instance validation')
    records = []
    for name, expected, filename, path, fingerprint in cases:
        command = [executable, '-p', str(sources), '-t', 'data', '-e',
                   str(sources / MODULE), str(sources / 'augmentation.yang'), str(path)]
        try:
            result = runner(command, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValidationError(f'yanglint failed to execute: {name}') from exc
        if type(result.returncode) is not int or result.returncode < 0:
            raise ValidationError(f'yanglint interrupted: {name}')
        accepted = result.returncode == 0
        if expected == 'valid':
            diagnostic = None
            passed = accepted
        elif name in baseline.EXPECTED_INVALID_DIAGNOSTICS:
            diagnostic = baseline.diagnostic_matches(name, result.stderr or '')
            passed = not accepted and diagnostic
        else:
            # New release-specific negatives must fail in the correct leaf.
            target = ('discontinuity-time' if name == 'invalid-discontinuity-time'
                      else 'total-energy-received')
            diagnostic = any('libyang err' in line and target in line
                             for line in (result.stderr or '').splitlines())
            passed = not accepted and diagnostic
        records.append({'case': name, 'expected': expected, 'file': filename,
                        'instance_sha256': fingerprint, 'exit_code': result.returncode,
                        'matched': bool(passed), 'diagnostic_matched': diagnostic,
                        'stderr': (result.stderr or '')[:1200]})
        if not passed:
            raise ValidationError(f'{name}: unexpected validation result or diagnostic')
    return records


def run(output: Path, repository: Path, corpus: Path, *, compiler_run=None) -> int:
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        print('UNVERIFIED: output must be an empty, real directory', file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    result = {'format': 'green-official-yang-06-1', 'draft': DRAFT_06,
              'baseline_draft': 'draft-ietf-green-power-and-energy-yang-05',
              'scope': 'schema and synthetic RFC 7951 conformance only; no device or IETF approval',
              'status': 'unverified', 'reason': None, 'cases': []}
    code = 2
    old_draft, old_xml, old_imports = compiler.DRAFT, compiler.DRAFT_XML, compiler.IMPORTS
    try:
        # `official_yang_smoke` is imported and used in this process only;
        # the original -05 executable and its release pins stay unchanged.
        compiler.DRAFT, compiler.DRAFT_XML = DRAFT_06, DRAFT_XML_06
        # -06 cites RFC 9911. Its 2025 revisions provide counter64 and
        # date-and-time; retain the older 2013 dependency set for -05 only.
        imports = dict(compiler.IMPORTS)
        for old in ('ietf-yang-types@2013-07-15.yang',
                    'ietf-inet-types@2013-07-15.yang'):
            if old not in imports:
                raise ValidationError(f'missing expected legacy dependency: {old}')
            del imports[old]
        imports['ietf-yang-types@2025-12-22.yang'] = 'ietf-yang-types'
        imports['ietf-inet-types@2025-12-22.yang'] = 'ietf-inet-types'
        compiler.IMPORTS = imports
        compile_status = (compiler_run or compiler.run)(output / 'schema', repository=repository)
        if compile_status != 0:
            result['status'] = 'failed' if compile_status == 1 else 'unverified'
            result['reason'] = 'published -06 schema compilation did not pass'
            code = compile_status
        else:
            sources, evidence = verify_compilation(output / 'schema', repository)
            result['draft_sha256'] = evidence['draft_sha256']
            result['module_sha256'] = evidence['module_sha256']
            result['tools'] = evidence['tools']
            result['cases'] = validate_instances(sources, evidence, corpus, output)
            result['status'] = 'passed'
            code = 0
    except ValidationError as exc:
        result['status'] = 'failed'
        result['reason'] = str(exc)[:300]
        code = 1
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired, compiler.ProbeError) as exc:
        result['reason'] = str(exc)[:300]
    finally:
        # Tests import both validators in one process; never leak the -06
        # draft or dependency override into the pinned -05 baseline.
        compiler.DRAFT, compiler.DRAFT_XML, compiler.IMPORTS = old_draft, old_xml, old_imports
        (output / 'evidence.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
        print(f'GREEN -06 validation: {result["status"]}')
        if result['reason']:
            print(result['reason'], file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--repository', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--corpus', type=Path,
                   default=Path(__file__).resolve().parents[1] / 'conformance/yang-instances')
    args = p.parse_args(argv)
    return run(args.output, args.repository, args.corpus)


if __name__ == '__main__':
    raise SystemExit(main())
