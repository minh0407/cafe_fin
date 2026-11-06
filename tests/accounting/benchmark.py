"""Opt-in real local import benchmark; never collected as a pytest fixture.

Run with PYTHONPATH=backend and fresh --root/--output outside the repository.
All generated records are synthetic. No source row values are logged.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from cafe_fin.accounting import schema as s
from cafe_fin.accounting.jobs import CHUNK, AccountingJobs
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService, visible
from cafe_fin.core.errors import CoreError
from cafe_fin.core.imports import attempts, claims
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import sha256_file
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

PAGE = 500
POLL_SECONDS = 0.1
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'RECOVERABLE'}
COLUMNS = [
    dict(id='code', name='Mã', kind='text', required=True),
    dict(id='day', name='Ngày', kind='date', required=True),
    dict(id='amount', name='Thu VND', kind='money', precision=19, required=True),
    dict(id='quantity', name='Khối lượng', kind='decimal', scale=3, required=True),
    dict(id='category', name='Loại', kind='choice', choices=['Robusta', 'Arabica']),
    dict(id='note', name='Ghi chú', kind='text'),
    dict(id='currency', name='Đơn vị tiền', kind='choice', choices=['VND']),
    dict(id='warehouse', name='Kho tham khảo', kind='text'),
]
SEMANTICS = dict(date_column='day', income_column='amount', currency_column='currency')
MAPPING = {column['id']: chr(65 + index) for index, column in enumerate(COLUMNS)}


def key():
    return secrets.token_hex(16)


def source_hashes(repository):
    paths = list((repository / 'backend' / 'cafe_fin').rglob('*.py')) + [Path(__file__).resolve()]
    return {path.relative_to(repository).as_posix(): sha256_file(path) for path in paths}


def cents_for(row):
    return 10_000 + row % 100_000


def amount_for(row):
    cents = cents_for(row)
    return f'{cents // 100}.{cents % 100:02d}'


def record_for(row):
    original = row - 1 if row % 1000 == 2 else row
    milli = 1000 + original % 1000
    return [
        f'{original:012d}', (date(2026, 1, 1) + timedelta(days=original % 28)).isoformat(),
        'INVALID_AMOUNT' if row % 1000 == 0 else amount_for(original),
        f'{milli // 1000}.{milli % 1000:03d}', 'Robusta' if original % 2 else 'Arabica',
        '=literal source text' if original % 113 == 0 else 'Cà phê tổng hợp, kiểm chứng',
        'VND', 'LOCAL-01',
    ]


def generate(path, rows):
    invalid = duplicates = first_cents = full_cents = 0
    with path.open('x', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([column['name'] for column in COLUMNS])
        for index in range(1, rows + 1):
            original = index - 1 if index % 1000 == 2 else index
            cents = cents_for(original)
            full_cents += cents
            if index % 1000 == 0:
                invalid += 1
            else:
                first_cents += cents
            duplicates += int(index % 1000 == 2)
            writer.writerow(record_for(index))
        output.flush()
        os.fsync(output.fileno())
    return dict(rows=rows, columns=len(COLUMNS), data_cells=rows * len(COLUMNS),
                header_rows=1, invalid_rows=invalid, exact_duplicate_extra_rows=duplicates,
                duplicate_group_rows=duplicates * 2, invalid_rate='0.001 target (every 1000th)',
                exact_duplicate_extra_rate='0.001 target (rows 2,1002,2002,...)',
                expected_first_rows=rows - invalid, expected_first_cents=first_cents,
                expected_full_rows=rows, expected_full_cents=full_cents,
                fixture_bytes=path.stat().st_size, fixture_sha256=sha256_file(path))


def memory_counters():
    if os.name == 'nt':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                    'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return dict(rss_bytes=counters.WorkingSetSize, os_peak_rss_bytes=counters.PeakWorkingSetSize,
                    private_bytes=counters.PrivateUsage, source='Windows GetProcessMemoryInfo')
    # The required production target is Windows. Keep smoke runs explicit elsewhere.
    if Path('/proc/self/statm').exists():
        rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        return dict(rss_bytes=rss, source='/proc/self/statm (non-Windows smoke)')
    return dict(rss_bytes=None, source='unavailable')


def disk_sizes(root):
    result = defaultdict(int)
    if not root.exists():
        return {}
    for path in root.rglob('*'):
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
            relative = path.relative_to(root)
            result['total_file_bytes'] += size
            result[relative.parts[0] + '_bytes'] += size
            if path.name.endswith('-wal'):
                result['wal_bytes'] += size
            elif path.name.endswith('-shm'):
                result['shm_bytes'] += size
            elif path.name.endswith(('.tmp', '.part')):
                result['temporary_bytes'] += size
        except FileNotFoundError:
            continue  # Atomic replacement/deletion can race a resource sample.
    return dict(result)


class Measurements:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.result = dict(status='RUNNING', process_roles='API/service/parser/worker share one process; UI not run',
                           process_id=os.getpid(), phases={}, snapshots={}, worker_phase_seconds={},
                           foreground={}, sample_interval_seconds=POLL_SECONDS)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.active = 'startup'
        self.resources = defaultdict(dict)
        self.latencies = defaultdict(list)
        self.thread = threading.Thread(target=self._sample_loop, name='benchmark-resources', daemon=True)

    def save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output.with_suffix('.json.part')
        with self.lock:
            encoded = json.dumps(self.result, ensure_ascii=False, indent=2)
        temporary.write_text(encoded, encoding='utf-8')
        temporary.replace(self.output)

    def sample(self):
        memory, disk = memory_counters(), disk_sizes(self.root)
        with self.lock:
            resource = self.resources[self.active]
            for key_, value in memory.items():
                if isinstance(value, int):
                    resource[key_] = max(resource.get(key_, 0), value)
            resource['memory_source'] = memory['source']
            for key_, value in disk.items():
                resource['peak_' + key_] = max(resource.get('peak_' + key_, 0), value)

    def _sample_loop(self):
        while not self.stop.is_set():
            try:
                self.sample()
            except OSError:
                self.result['resource_sample_error'] = 'OS_RESOURCE_SAMPLE_FAILED'
            self.stop.wait(POLL_SECONDS)

    @contextmanager
    def phase(self, name):
        self.active = name
        started = time.perf_counter()
        self.sample()
        try:
            yield
        finally:
            self.sample()
            self.result['phases'][name] = dict(seconds=time.perf_counter() - started,
                                               resources=dict(self.resources[name]))
            self.save()

    def latency(self, name, callback):
        started = time.perf_counter()
        try:
            return callback()
        finally:
            self.latencies[name].append(time.perf_counter() - started)

    def finish(self):
        self.stop.set()
        self.thread.join(2)
        for name, values in self.latencies.items():
            ordered = sorted(values)
            self.result['foreground'][name] = dict(samples=len(values), min_seconds=ordered[0],
                median_seconds=statistics.median(values), max_seconds=ordered[-1],
                p95_seconds=ordered[min(len(ordered) - 1, (len(ordered) * 95) // 100)])
        self.save()


class WorkerInstrumentation:
    """Time real worker chunks and pause once after a durable parse receipt."""

    def __init__(self, measurements):
        self.measurements = measurements
        self.entered, self.release = threading.Event(), threading.Event()
        self.clock = threading.local()
        self.original_run = AccountingJobs.run
        self.original_commit = JobContext.commit_chunk

    def __enter__(self):
        instrument = self

        def run(worker, context, payload):
            instrument.clock.last = time.perf_counter()
            instrument.clock.kind = context.service.status(context.job_id)['kind']
            try:
                return instrument.original_run(worker, context, payload)
            finally:
                instrument.record('finalize_or_interruption')

        def commit(context, *args, **kwargs):
            result = instrument.original_commit(context, *args, **kwargs)
            instrument.record(kwargs['phase'])
            if kwargs['phase'] == 'parse' and not instrument.entered.is_set():
                instrument.entered.set()
                if not instrument.release.wait(10):
                    raise RuntimeError('benchmark checkpoint probe was not released')
            return result

        AccountingJobs.run = run
        JobContext.commit_chunk = commit
        return self

    def record(self, phase):
        now = time.perf_counter()
        kind = getattr(self.clock, 'kind', 'unknown')
        with self.measurements.lock:
            grouped = self.measurements.result['worker_phase_seconds'].setdefault(kind, {})
            grouped[phase] = grouped.get(phase, 0) + now - getattr(self.clock, 'last', now)
        self.clock.last = now

    def __exit__(self, *_):
        self.release.set()
        AccountingJobs.run = self.original_run
        JobContext.commit_chunk = self.original_commit


def wait_job(runtime, job_id, measurements, *, probe=None, timeout=86_400):
    deadline = time.perf_counter() + timeout
    polls = 0
    while time.perf_counter() < deadline:
        status = measurements.latency('job_status', lambda: runtime.jobs.status(job_id))
        if status['state'] in TERMINAL:
            if status['state'] != 'COMPLETED':
                raise CoreError(status.get('error_code') or status['state'], 'Benchmark job failed.')
            return status
        if runtime.runner.error_code:
            raise CoreError(runtime.runner.error_code, 'Benchmark runner failed.')
        if probe is not None and polls % 20 == 0:
            probe()
        polls += 1
        time.sleep(POLL_SECONDS)
    raise CoreError('BENCHMARK_JOB_TIMEOUT', 'Benchmark exceeded bounded timeout.')


def assert_counts(runtime, service, actor, book_id, batch_id, expected_rows, expected_cents):
    rows = service.list_rows(actor, book_id, page_size=PAGE)
    if rows['total'] != expected_rows:
        raise AssertionError('Published row count does not match deterministic fixture')
    summary = service.summary(actor, book_id, '2026-01-01', '2026-02-01')
    expected_amount = f'{expected_cents // 100}.{expected_cents % 100:02d}'
    if summary['totals'].get('VND', {}).get('income') != expected_amount:
        raise AssertionError('Authoritative Decimal summary does not match deterministic fixture')
    with runtime.reader() as conn:
        lineage = conn.execute(select(func.count()).select_from(claims).where(claims.c.job_id == batch_id)).scalar_one()
        targets = conn.execute(select(func.count(func.distinct(claims.c.target_id))).where(claims.c.job_id == batch_id)).scalar_one()
        published = conn.execute(select(func.count()).select_from(s.entries).where(s.entries.c.book_id == book_id, visible())).scalar_one()
        attempt_count = conn.execute(select(func.count()).select_from(attempts).where(attempts.c.job_id == batch_id, attempts.c.state == 'PUBLISHED')).scalar_one()
    if lineage != expected_rows or targets != expected_rows or published != expected_rows:
        raise AssertionError('Lineage/target uniqueness reconciliation failed')
    return dict(published_rows=published, lineage_rows=lineage, distinct_targets=targets,
                published_attempts=attempt_count, exact_income=expected_amount)


def snapshot(runtime, batch_id):
    with runtime.reader() as conn:
        stage_rows = conn.execute(select(func.count()).select_from(s.stage).where(s.stage.c.batch_id == batch_id)).scalar_one()
        payload_bytes = conn.execute(select(func.sum(func.length(s.stage.c.raw_json) + func.length(s.stage.c.typed_json) + func.length(s.stage.c.metadata_json))).where(s.stage.c.batch_id == batch_id)).scalar_one()
        result = dict(stage_rows=stage_rows, staged_json_character_count=payload_bytes,
                      journal_mode=conn.execute(text('PRAGMA journal_mode')).scalar_one(),
                      sqlite_page_bytes=conn.execute(text('PRAGMA page_count')).scalar_one() * conn.execute(text('PRAGMA page_size')).scalar_one())
        try:
            result['stage_table_page_bytes'] = conn.execute(text('SELECT SUM(pgsize) FROM dbstat WHERE name = :name'), {'name': s.stage.name}).scalar_one()
        except Exception:
            result['stage_table_page_bytes'] = 'NOT AVAILABLE: SQLite dbstat absent'
    return result | {'disk': disk_sizes(runtime.root.path)}


def confirm(service, actor, batch):
    return service.confirm(actor, batch['id'], dict(expected_version=batch['version'],
        staging_revision=batch['revision'], mapping_revision=batch['mapping_revision'],
        decision_revision=batch['decision_revision'], validation_token=batch['validation_token'],
        mode='valid_rows_only', request_key=key()))


def request_export(runtime, actor, book_id):
    # Invoke the actual additive accounting export route, with a real local user.
    # No HTTP server/browser or authentication latency is part of this benchmark.
    app = FastAPI()
    app.state.runtime = runtime

    @app.middleware('http')
    async def principal(request, call_next):
        request.state.principal = actor
        return await call_next(request)

    app.include_router(module_manifest().router, prefix='/accounting')
    with TestClient(app) as client:
        response = client.post(f'/accounting/books/{book_id}/exports', json={'format': 'csv', 'request_key': key()})
    if response.status_code != 200:
        raise CoreError('BENCHMARK_EXPORT_SUBMIT_FAILED', 'Actual export route failed.')
    return response.json()


def run(args, measurements):
    root = args.root
    fixture_path = root.with_name(root.name + '-source.csv')
    with measurements.phase('generate_streaming_csv'):
        fixture = generate(fixture_path, args.rows)
        measurements.result['fixture'] = fixture
    runtime = None
    password = secrets.token_urlsafe(24)
    try:
        with measurements.phase('bootstrap_real_sqlite'):
            runtime = Runtime(root, initialize=True, modules=ModuleRegistry((module_manifest(),)))
            session = runtime.auth.setup('benchmark-admin', password)
            actor = runtime.auth.authenticate(session['access_token'])
            service = AccountingService(runtime)
            semantics = dict(SEMANTICS)
            if args.business_key_columns:
                semantics['business_key_columns'] = list(args.business_key_columns)
            book = service.create_book(actor, 'Synthetic benchmark', COLUMNS, semantics, key())
            probe_book = service.create_book(actor, 'Foreground probe', COLUMNS, SEMANTICS, key())
            probe_row = service.create_row(actor, probe_book['id'], dict(zip(MAPPING, record_for(7), strict=True)), key())

        def probe():
            nonlocal probe_row
            measurements.latency('foreground_book_filter', lambda: service.list_rows(actor, book['id'],
                page_size=PAGE, filters=[dict(column_id='amount', op='gte', value='0.00')]))
            probe_row = measurements.latency('foreground_update_other_book', lambda: service.mutate_row(
                actor, probe_row['id'], probe_row['version'], key(), values={'note': 'Synthetic foreground update'}))

        with measurements.phase('store_original_bytes'):
            with fixture_path.open('rb') as source:
                stored = runtime.files.put(source, category='workbooks', original_name='synthetic-source.csv',
                    actor=actor.id, request_key=key(), authorize=service.authorize(actor))
            if stored.sha256 != fixture['fixture_sha256']:
                raise AssertionError('FileStore changed original bytes')

        with WorkerInstrumentation(measurements) as instrument:
            with measurements.phase('parse_before_restart_checkpoint'):
                batch = service.create_batch(actor, book['id'], stored.id, {}, key())
                runtime.start()
                if not instrument.entered.wait(30):
                    raise CoreError('BENCHMARK_NO_PARSE_CHECKPOINT', 'Worker did not produce first parse receipt.')
            with measurements.phase('restart_resume_probe'):
                runtime.runner.stop_event.set()
                instrument.release.set()
                runtime.runner.close()
                interrupted = runtime.jobs.status(batch['job_id'])
                if interrupted['state'] != 'RECOVERABLE' or interrupted['checkpoint'].get('parsed', 0) < 1:
                    raise AssertionError('Restart probe failed to retain durable parse checkpoint')
                measurements.result['restart_probe'] = dict(kind='graceful worker stop after committed parse chunk',
                    hard_process_kill=False, checkpoint=interrupted['checkpoint'], state_before_restart=interrupted['state'])
                runtime.close()
                runtime = Runtime(root, modules=ModuleRegistry((module_manifest(),)))
                session = runtime.auth.login('benchmark-admin', password)
                actor = runtime.auth.authenticate(session['access_token'])
                service = AccountingService(runtime)
                runtime.start()
                batch = service.cancel_resume(actor, batch['id'], 'resume')
            with measurements.phase('parse_resumed'):
                wait_job(runtime, batch['job_id'], measurements, probe=probe)
                batch = service.get_batch(actor, batch['id'])
                measurements.result['snapshots']['parsed'] = snapshot(runtime, batch['id'])
                if batch['counts']['source_rows'] != args.rows:
                    raise AssertionError('Resumed parser lost or duplicated source rows')

            with measurements.phase('mapping'):
                batch = service.mapping(actor, batch['id'], batch['version'], MAPPING, {}, key())
            with measurements.phase('validate_and_deduplicate_first'):
                batch = service.validate(actor, batch['id'], batch['version'], key())
                wait_job(runtime, batch['job_id'], measurements, probe=probe)
                batch = service.get_batch(actor, batch['id'])
                measurements.result['first_validation_counts'] = batch['counts']
                if batch['counts']['invalid'] != fixture['invalid_rows']:
                    raise AssertionError('Validation count disagrees with injected invalid rows')
                measurements.result['snapshots']['validated'] = snapshot(runtime, batch['id'])
            with measurements.phase('keep_duplicate_warnings'):
                batch = service.decisions(actor, batch['id'], batch['version'], [], 'keep', key())
            with measurements.phase('confirm_first_publish'):
                batch = confirm(service, actor, batch)
                wait_job(runtime, batch['job_id'], measurements, probe=probe)
                batch = service.get_batch(actor, batch['id'])
                measurements.result['first_reconciliation'] = assert_counts(runtime, service, actor, book['id'], batch['id'],
                    fixture['expected_first_rows'], fixture['expected_first_cents'])
                measurements.result['snapshots']['first_published'] = snapshot(runtime, batch['id'])

            expected_rows, expected_cents = fixture['expected_first_rows'], fixture['expected_first_cents']
            if not args.skip_second_pass and fixture['invalid_rows']:
                with measurements.phase('patch_invalid_rows'):
                    # Source ordering is stable; only at most 500 patches are held.
                    patched = 0
                    for page in range(1, (fixture['invalid_rows'] + PAGE - 1) // PAGE + 1):
                        staged = service.staging_page(actor, batch['id'], page=page, page_size=PAGE, status='invalid')
                        patches = [dict(row_id=row['row_id'], expected_version=row['revision'],
                            values={'amount': amount_for(row['source_row'] - 1)}) for row in staged['items']]
                        batch = service.patch_staging(actor, batch['id'], batch['version'], patches, key())
                        patched += len(patches)
                    if patched != fixture['invalid_rows']:
                        raise AssertionError('Patch paging skipped invalid source rows')
                with measurements.phase('validate_and_deduplicate_second'):
                    batch = service.validate(actor, batch['id'], batch['version'], key())
                    wait_job(runtime, batch['job_id'], measurements, probe=probe)
                    batch = service.get_batch(actor, batch['id'])
                    batch = service.decisions(actor, batch['id'], batch['version'], [], 'keep', key())
                with measurements.phase('confirm_second_publish'):
                    batch = confirm(service, actor, batch)
                    wait_job(runtime, batch['job_id'], measurements, probe=probe)
                    batch = service.get_batch(actor, batch['id'])
                    expected_rows, expected_cents = fixture['expected_full_rows'], fixture['expected_full_cents']
                    measurements.result['second_reconciliation'] = assert_counts(runtime, service, actor, book['id'], batch['id'], expected_rows, expected_cents)

            with measurements.phase('export_csv_real_route_and_worker'):
                export = request_export(runtime, actor, book['id'])
                wait_job(runtime, export['job_id'], measurements, probe=probe)
                with runtime.reader() as conn:
                    export_file_id = conn.execute(select(s.exports.c.file_id).where(s.exports.c.id == export['export_id'])).scalar_one()
                with runtime.files.read(export_file_id) as source:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(chunk)
                export_file = runtime.files.get(export_file_id)
                with runtime.files.read(export_file_id) as source:
                    import io
                    reader = csv.reader(io.TextIOWrapper(source, encoding='utf-8-sig', newline=''))
                    header = next(reader)
                    export_rows = sum(1 for _ in reader)
                if export_rows != expected_rows or len(header) != len(COLUMNS):
                    raise AssertionError('Derived export row/cell count reconciliation failed')
                measurements.result['export'] = dict(rows=export_rows, columns=len(header),
                    data_cells=export_rows * len(header), bytes=export_file.size, sha256=digest.hexdigest(), derived=True)
            with measurements.phase('final_reconciliation'):
                with runtime.files.read(stored.id):
                    pass  # FileStore verifies the source SHA-256 again.
                if sha256_file(fixture_path) != fixture['fixture_sha256']:
                    raise AssertionError('Original synthetic source changed')
                measurements.result['final_reconciliation'] = assert_counts(runtime, service, actor, book['id'], batch['id'], expected_rows, expected_cents)
                measurements.result['snapshots']['final'] = snapshot(runtime, batch['id'])
                measurements.result['final_counts'] = batch['counts']
                measurements.result['restart_probe']['resumed_source_rows'] = args.rows
                measurements.result['source_hash_unchanged'] = True
                measurements.result['second_pass'] = 'SKIPPED_BY_FLAG' if args.skip_second_pass else 'COMPLETE' if fixture['invalid_rows'] else 'NO_INVALID_ROWS'
        measurements.result['status'] = 'PASS'
    finally:
        if runtime is not None:
            runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=int, default=50_000)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--skip-second-pass', action='store_true')
    parser.add_argument('--business-key-columns', nargs='+', choices=[column['id'] for column in COLUMNS],
        default=[], help='Explicit stable column IDs for the primary book; use code for exact-pair fixture.')
    args = parser.parse_args()
    if not 2 <= args.rows <= 1_000_000:
        parser.error('--rows must be between 2 and 1000000')
    if len(args.business_key_columns) != len(set(args.business_key_columns)):
        parser.error('--business-key-columns must not repeat a stable column ID')
    default_parent = Path(tempfile.mkdtemp(prefix='cafe-fin-benchmark-')) if args.root is None else None
    args.root = (args.root or default_parent / 'data').resolve()
    args.output = (args.output or args.root.with_name(args.root.name + '-result.json')).resolve()
    repository = Path(__file__).resolve().parents[2]
    if args.root.is_relative_to(repository) or args.output.is_relative_to(repository):
        parser.error('Synthetic data/results must be outside the repository')
    if args.root.exists() and any(args.root.iterdir()):
        parser.error('--root must be a new empty data directory; existing data is never deleted')
    if args.output.exists() or args.root.with_name(args.root.name + '-source.csv').exists():
        parser.error('Output/fixture already exists; use a fresh benchmark directory')
    args.root.parent.mkdir(parents=True, exist_ok=True)
    measurements = Measurements(args.root, args.output)
    measurements.result['scenario'] = dict(
        name='explicit_business_key' if args.business_key_columns else 'no_business_key',
        business_key_columns=list(args.business_key_columns))
    measurements.result['environment'] = dict(python=sys.version, platform=platform.platform(),
        architecture=platform.machine(), cpu_logical=os.cpu_count(), sqlite=sqlite3.sqlite_version,
        chunk_rows=CHUNK, page_rows=PAGE, ui_cache_rows='NOT RUN: no UI',
        free_disk_before_bytes=shutil.disk_usage(args.root.parent).free,
        packages={name: importlib.metadata.version(name) for name in ('sqlalchemy', 'openpyxl', 'fastapi')},
        hardware_inventory='Collect CPU/RAM/SSD separately in PowerShell; this runner does not infer SSD type')
    measurements.result['code_provenance'] = dict(
        base_git_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repository, text=True).strip(),
        worktree_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repository, text=True).strip()),
        source_file_sha256_start=source_hashes(repository),
        immutable_release_evidence=False,
        note='Development worktree may contain uncommitted changes; modules remain loaded in-process across Runtime restart')
    clock = time.get_clock_info('perf_counter')
    measurements.result['environment']['timing_clock'] = dict(name='time.perf_counter',
        monotonic=clock.monotonic, resolution_seconds=clock.resolution, implementation=clock.implementation)
    measurements.result['method'] = dict(worker_timing='Intervals from worker start/previous committed chunk through next durable chunk; grouped by actual chunk phase; tail includes finalize/interruption',
        resource_peaks='100 ms sampled process RSS/private bytes and file sizes; OS PeakWorkingSetSize cumulative across phases',
        restart='Controlled graceful stop at committed parse receipt, close/reopen Runtime, authenticated resume; not a hard-kill crash probe',
        foreground='real indexed filter on import book and versioned update on separate probe book while background job runs',
        fixture_generator_version=1, partial_import_second_pass=not args.skip_second_pass,
        no_ui=True, no_external_services=True, data_root=str(args.root))
    measurements.thread.start()
    started = time.perf_counter()
    exit_code = 0
    try:
        run(args, measurements)
    except Exception as exc:
        measurements.result['status'] = 'FAIL'
        measurements.result['failure'] = dict(type=type(exc).__name__, code=getattr(exc, 'code', 'BENCHMARK_ASSERTION_OR_RUNTIME_FAILURE'),
            message=exc.message if isinstance(exc, CoreError) else str(exc) if isinstance(exc, AssertionError) else None)
        exit_code = 1
    finally:
        measurements.result['total_seconds'] = time.perf_counter() - started
        end_hashes = source_hashes(repository)
        measurements.result['code_provenance']['source_file_sha256_end'] = end_hashes
        start_hashes = measurements.result['code_provenance']['source_file_sha256_start']
        measurements.result['code_provenance']['files_changed_during_run'] = sorted(
            name for name in start_hashes.keys() | end_hashes.keys() if start_hashes.get(name) != end_hashes.get(name))
        measurements.result['final_disk'] = disk_sizes(args.root)
        measurements.finish()
    print(json.dumps({'status': measurements.result['status'], 'rows': args.rows, 'output': str(args.output)}, ensure_ascii=False))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())

