"""Opt-in closed-benchmark clone bootstrap. NEVER run during a timed benchmark.

The original Runtime is never opened. Only a guarded, completed synthetic source
is read, and only a fresh isolated clone receives an audited synthetic Admin.
Password input is CAFE_FIN_BULK_PASSWORD; it is never printed or written to output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cafe_fin.accounting import schema as accounting
from cafe_fin.accounting.module import module_manifest
from cafe_fin.core.auth import USERS, Principal
from cafe_fin.core.db import AUDIT
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import FILES, LAYOUT, MARKER, DataRootService
from sqlalchemy import select

EXPECTED_ROWS = 1_000_000
SOURCE_PREFIX = ('cafe-fin-frozen-20261106', 'cafe-fin-final-033e900-683b8f62fae848e1a7aa50259e323a6f')
CLONE_PREFIX = 'cafe-fin-bulk-ui-'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def phase(message):
    print('Bulk clone: ' + message, file=sys.stderr, flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def guarded_temporary_path(path, prefix):
    path = Path(path).resolve()
    relative = path.relative_to(Path(tempfile.gettempdir()).resolve())
    require(relative.parts and relative.parts[0].lower().startswith(prefix),
            'Path is not in the dedicated synthetic Temp prefix.')
    for part in (path, *path.parents):
        require(not part.is_symlink() and not (hasattr(part, 'is_junction') and part.is_junction()),
                'Synthetic data paths cannot use links or junctions.')
    return path


def database_fingerprint(path):
    info = path.stat()
    return {'sha256': sha256(path), 'size': info.st_size, 'mtime_ns': info.st_mtime_ns}


@contextmanager
def closed_source_guard(root):
    # Production Runtime owns byte 0 of this existing lock. Opening r+b is only
    # to acquire/release the same OS lock: no write/truncate/create operation.
    lock = root / '.instance.lock'
    require(lock.is_file() and lock.stat().st_size >= 1, 'Missing existing source Runtime lock file.')
    with lock.open('r+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            wal = root / 'database/cafe_fin.db-wal'
            require(not wal.exists() or wal.stat().st_size == 0,
                    'Source WAL is not empty. Close/checkpoint the benchmark through its owner first.')
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def readonly_database(path):
    # With a closed/checkpointed source, immutable avoids journal/shm side effects.
    connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.execute('PRAGMA query_only=ON')
    return connection


def accounting_digest(path):
    """Stream rows without retaining a million-row collection or logging values."""
    output = {}
    with closing(readonly_database(path)) as connection:
        for table, ordering in ((accounting.books, 'id'), (accounting.schemas, 'book_id, revision'),
                                (accounting.entries, 'book_id, logical_row, id')):
            digest, count = hashlib.sha256(), 0
            cursor = connection.execute(f'SELECT * FROM "{table.name}" ORDER BY {ordering}')
            columns = [field[0] for field in cursor.description]
            digest.update(json.dumps(columns, separators=(',', ':')).encode('utf-8') + b'\n')
            while rows := cursor.fetchmany(256):
                for row in rows:
                    digest.update(json.dumps(row, ensure_ascii=False, separators=(',', ':'),
                                             allow_nan=False).encode('utf-8') + b'\n')
                    count += 1
            output[table.name] = {'rows': count, 'sha256': digest.hexdigest()}
    return output


def user_snapshot(runtime):
    # Hashes stay in process solely to verify old credentials were not changed.
    # They are never serialized into the preparation report or env script.
    with runtime.reader() as connection:
        return {row['id']: dict(row) for row in connection.execute(select(USERS)).mappings()}


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def prepare(args):
    require(args.runtime_closed, 'Pass --runtime-closed only AFTER the owner confirms benchmark exit.')
    password = os.environ.get('CAFE_FIN_BULK_PASSWORD')
    require(isinstance(password, str) and 10 <= len(password) <= 128,
            'Set CAFE_FIN_BULK_PASSWORD to a new known synthetic password (10..128 characters).')
    require(3 <= len(args.username) <= 64 and args.username.strip() == args.username,
            'Synthetic username must contain 3..64 characters without edge whitespace.')
    result_file = Path(args.result).resolve(strict=True)
    result = json.loads(result_file.read_text(encoding='utf-8'))
    require(result.get('status') == 'PASS', 'Source benchmark result is not PASS.')
    require(result.get('fixture', {}).get('rows') == EXPECTED_ROWS,
            'Source benchmark fixture is not exactly 1,000,000 rows.')
    require(result.get('final_reconciliation', {}).get('published_rows') == EXPECTED_ROWS,
            'Source result does not reconcile 1,000,000 published rows.')
    source_root = guarded_temporary_path(result.get('method', {}).get('data_root', ''), SOURCE_PREFIX)
    source = DataRootService(source_root).open_existing(writable=False)
    source_db = source.database_path
    report = {
        'status': 'PREPARING', 'created_at': datetime.now(timezone.utc).isoformat(),
        'source_root': str(source_root), 'source_result': str(result_file),
        'source_result_sha256': sha256(result_file), 'expected_published_rows': EXPECTED_ROWS,
        'method': 'closed-source immutable SQLite backup + verified core_files + clone-only audited AuthService.create_user',
        'password_source': 'CAFE_FIN_BULK_PASSWORD environment; never stored or printed',
    }
    # No destination is created until source completion/path/lock checks pass.
    with closed_source_guard(source_root):
        phase('completed source lock acquired; hashing original database')
        before = database_fingerprint(source_db)
        require(source_db.stat().st_nlink == 1, 'Source DB must not be a hard link.')
        with closing(readonly_database(source_db)) as connection:
            connection.row_factory = sqlite3.Row
            file_rows = [dict(row) for row in connection.execute(
                f'SELECT relative_key, size, sha256 FROM "{FILES.name}" ORDER BY relative_key')]
            if args.book:
                book_id = args.book
                count = connection.execute(
                    f'SELECT COUNT(*) FROM "{accounting.entries.name}" WHERE book_id=? AND deleted_at IS NULL',
                    (book_id,)).fetchone()[0]
                require(count == EXPECTED_ROWS, 'Requested book does not have exactly 1,000,000 rows.')
            else:
                candidates = connection.execute(
                    f'SELECT book_id FROM "{accounting.entries.name}" WHERE deleted_at IS NULL '
                    'GROUP BY book_id HAVING COUNT(*)=?', (EXPECTED_ROWS,)).fetchall()
                require(len(candidates) == 1, 'Provide --book: exactly one million-row book could not be selected.')
                book_id = candidates[0][0]
            book = connection.execute(f'SELECT id, name, schema_revision, data_revision FROM "{accounting.books.name}" WHERE id=?', (book_id,)).fetchone()
            require(book is not None, 'Benchmark book metadata is missing.')
            required_bytes = before['size'] + sum(row['size'] for row in file_rows) + 512 * 1024**2
            require(shutil.disk_usage(tempfile.gettempdir()).free > required_bytes,
                    'Insufficient free Temp volume space for the independent clone and safety margin.')
            if args.root:
                clone_root = guarded_temporary_path(args.root, CLONE_PREFIX)
                require(not clone_root.exists(), 'Clone root already exists. A new destination is required.')
                clone_root.parent.mkdir(parents=True, exist_ok=True)
                parent = clone_root.parent
            else:
                parent = Path(tempfile.mkdtemp(prefix=CLONE_PREFIX))
                clone_root = parent / 'data'
            clone_root = guarded_temporary_path(clone_root, CLONE_PREFIX)
            require(clone_root != source_root and not clone_root.is_relative_to(source_root),
                    'Clone must be separate from the source.')
            manifest_path = parent / 'clone-preparation.json'
            activation_path = parent / 'activate-bulk-env.ps1'
            require(not manifest_path.exists() and not activation_path.exists(),
                    'Destination preparation artifacts already exist; choose a new parent.')
            report.update(clone_root=str(clone_root), book=dict(book), book_id=book_id,
                          source_database_before=before)
            manifest_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            try:
                clone_root.mkdir(exist_ok=False)
                for folder in LAYOUT:
                    (clone_root / folder).mkdir()
                clone_db = clone_root / 'database/cafe_fin.db'
                with closing(sqlite3.connect(clone_db)) as destination:
                    connection.backup(destination, pages=256)
                    require(destination.execute('PRAGMA integrity_check').fetchone()[0] == 'ok',
                            'Cloned SQLite DB failed integrity_check.')
                    require(destination.execute('PRAGMA foreign_key_check').fetchone() is None,
                            'Cloned SQLite DB failed foreign_key_check.')
                phase('SQLite backup and integrity checks complete; copying immutable files')
                clone = DataRootService(clone_root)
                shutil.copyfile(source.resolve_key(MARKER), clone.resolve_key(MARKER))
                require(sha256(source.resolve_key(MARKER)) == sha256(clone.resolve_key(MARKER)),
                        'Copied app marker hash mismatch.')
                copied = []
                for row in file_rows:
                    require(row['relative_key'].split('/')[0] in {'documents', 'workbooks', 'imports', 'reports'},
                            'Referenced immutable file is outside FileStore categories.')
                    source_file = source.resolve_key(row['relative_key'])
                    target_file = clone.resolve_key(row['relative_key'])
                    require(source_file.is_file() and source_file.stat().st_size == row['size'],
                            'Referenced source file missing or size mismatch.')
                    require(sha256(source_file) == row['sha256'], 'Referenced source file hash mismatch.')
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source_file, target_file)
                    require(target_file.stat().st_size == row['size'] and sha256(target_file) == row['sha256'],
                            'Copied referenced file failed hash verification.')
                    copied.append({'key': row['relative_key'], 'size': row['size'], 'sha256': row['sha256']})
                clone.open_existing(writable=False)
                require(clone_db.stat().st_nlink == 1 and not os.path.samefile(source_db, clone_db),
                        'Clone DB must have independent storage/file identity.')
                phase('immutable files verified; streaming source accounting digest')
                source_entries = accounting_digest(source_db)
                phase('streaming clone accounting digest before authentication bootstrap')
                clone_entries = accounting_digest(clone_db)
                require(clone_entries == source_entries, 'Clone accounting rows/schema digest differs from source.')
                report.update(copied_files=copied, app_marker_sha256=sha256(clone_root / MARKER),
                              source_accounting_digest=source_entries, clone_accounting_digest_before_auth=clone_entries)
                # Construct and authorize a trusted principal ONLY from cloned DB.
                # Runtime.start is deliberately never called: no job recovery/runner.
                runtime = Runtime(clone_root, initialize=False, modules=ModuleRegistry((module_manifest(),)))
                phase('clone-only Runtime initialized; creating audited synthetic Admin')
                try:
                    users_before = user_snapshot(runtime)
                    admins = [row for row in users_before.values() if row['active'] and row['role'] == 'admin']
                    require(admins, 'Clone has no active synthetic Admin for audited test bootstrap.')
                    existing = sorted(admins, key=lambda row: row['id'])[0]
                    actor = Principal(id=existing['id'], username=existing['username'], role='admin',
                                      permissions=('*',), version=existing['version'])
                    require(all(row['username'] != args.username for row in users_before.values()),
                            'Requested new synthetic username already exists; original credentials will not be reset.')
                    created = runtime.auth.create_user(actor, username=args.username, password=password,
                                                       role='admin', request_key='bulk-clone-admin:' + secrets.token_hex(16))
                    login = runtime.auth.login(args.username, password)
                    authenticated = runtime.auth.authenticate(login['access_token'])
                    require(authenticated.id == created['id'] and authenticated.role == 'admin',
                            'New clone-only Admin failed public login/authenticate verification.')
                    runtime.auth.logout(login['access_token'])
                    users_after = user_snapshot(runtime)
                    require(all(users_after.get(key) == row for key, row in users_before.items()),
                            'An existing cloned user or credential changed.')
                    require(len(users_after) == len(users_before) + 1,
                            'Expected exactly one new synthetic clone Admin.')
                    with runtime.reader() as audit_connection:
                        audit = audit_connection.execute(select(AUDIT.c.id).where(
                            AUDIT.c.actor == actor.id, AUDIT.c.entity == 'user',
                            AUDIT.c.entity_id == created['id'], AUDIT.c.action == 'create')).first()
                    require(audit is not None, 'Clone-only synthetic Admin creation audit is missing.')
                    report.update(synthetic_username=args.username, synthetic_user_id=created['id'],
                                  public_login_verified=True, existing_users_unchanged=True,
                                  new_admin_audited=True, runtime_job_runner_started=False)
                finally:
                    runtime.close()
                phase('clone Runtime closed; streaming post-auth accounting digest')
                clone_after = accounting_digest(clone_db)
                require(clone_after == source_entries, 'Clone accounting data changed during Auth bootstrap.')
                report['clone_accounting_digest_after_auth'] = clone_after
                require(sha256(result_file) == report['source_result_sha256'], 'Source result changed during preparation.')
                phase('verifying original database hash/size/mtime conservation')
                after = database_fingerprint(source_db)
                require(after == before, 'Original frozen source DB hash/size/mtime changed during preparation.')
                report.update(source_database_after=after, source_database_unchanged=True,
                              source_entries_unchanged_via_database_hash=True, status='PASS')
                # Keep the password in the caller's environment only. Dot-sourcing
                # this credential-free file sets the other exact UI inputs.
                environment = {'CAFE_FIN_BULK_ROOT': str(clone_root), 'CAFE_FIN_BULK_RESULT': str(result_file),
                               'CAFE_FIN_BULK_BOOK': book_id, 'CAFE_FIN_BULK_USERNAME': args.username,
                               'CAFE_FIN_BULK_CODE_COLUMN': args.code_column, 'CAFE_FIN_BULK_READY': '1'}
                activation = "if (-not $env:CAFE_FIN_BULK_PASSWORD) { throw 'Set the same synthetic clone password before activation.' }\n"
                activation += '\n'.join(f'$env:{name} = {ps_string(value)}' for name, value in environment.items()) + '\n'
                activation_path.write_text(activation, encoding='utf-8')
                report['environment_activation'] = str(activation_path)
            except Exception as exc:
                report.update(status='FAIL', failure_type=type(exc).__name__,
                              failure_code=getattr(exc, 'code', 'CLONE_PREPARATION_FAILED'))
                after = database_fingerprint(source_db)
                report.update(source_database_after=after, source_database_unchanged=after == before)
                raise
            finally:
                manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'PASS', 'clone_root': str(clone_root), 'book_id': book_id,
            'username': args.username, 'report': str(manifest_path), 'activate': str(activation_path),
            'password': 'NOT STORED; retain CAFE_FIN_BULK_PASSWORD in the caller environment'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', required=True, type=Path)
    parser.add_argument('--runtime-closed', action='store_true')
    parser.add_argument('--root', type=Path, help='Optional NEW Temp/cafe-fin-bulk-ui-*/... destination')
    parser.add_argument('--book', help='Optional explicit million-row book UUID; otherwise require a unique match')
    parser.add_argument('--username', default='bulk-ui-admin')
    parser.add_argument('--code-column', default='code')
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args), ensure_ascii=False))
        return 0
    except Exception as exc:
        # No traceback, SQL parameters, password hashes or credential binding in
        # output. A failed partial clone is retained for owner inspection.
        print(json.dumps({'status': 'FAIL', 'error_type': type(exc).__name__,
                          'code': getattr(exc, 'code', 'CLONE_PREPARATION_FAILED'),
                          'message': str(exc) if isinstance(exc, ValueError) else 'Preparation failed; source retained.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
