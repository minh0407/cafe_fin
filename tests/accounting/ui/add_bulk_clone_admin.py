"""Add a NEW audited Admin to a previously verified synthetic bulk clone.

Never resets an existing credential; never opens the original Runtime. Password
is CAFE_FIN_BULK_PASSWORD and remains only in the caller/process environment.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from cafe_fin.accounting.module import module_manifest
from cafe_fin.core.auth import Principal
from cafe_fin.core.db import AUDIT
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import DataRootService
from prepare_bulk_clone import (
    CLONE_PREFIX,
    SOURCE_PREFIX,
    accounting_digest,
    closed_source_guard,
    database_fingerprint,
    guarded_temporary_path,
    phase,
    ps_string,
    require,
    user_snapshot,
)
from sqlalchemy import select


def add_admin(args):
    require(args.runtime_closed, 'Confirm the source AND retained clone Runtimes are closed.')
    password = os.environ.get('CAFE_FIN_BULK_PASSWORD')
    require(isinstance(password, str) and 10 <= len(password) <= 128,
            'Set a new known synthetic CAFE_FIN_BULK_PASSWORD (10..128 characters).')
    preparation_path = Path(args.preparation).resolve(strict=True)
    preparation = json.loads(preparation_path.read_text(encoding='utf-8'))
    require(preparation.get('status') == 'PASS' and preparation.get('source_database_unchanged'),
            'Only an existing verified PASS clone preparation may be reused.')
    root = guarded_temporary_path(preparation['clone_root'], CLONE_PREFIX)
    source_root = guarded_temporary_path(preparation['source_root'], SOURCE_PREFIX)
    require(root != source_root, 'Clone must be independent from the source.')
    DataRootService(root).open_existing(writable=False)
    source_db, clone_db = source_root / 'database/cafe_fin.db', root / 'database/cafe_fin.db'
    require(clone_db.stat().st_nlink == 1 and not os.path.samefile(source_db, clone_db),
            'The retained clone must have independent file identity.')
    clone_wal = Path(str(clone_db) + '-wal')
    require(not clone_wal.exists() or clone_wal.stat().st_size == 0,
            'Retained clone has a nonempty WAL; close it safely first.')
    suffix = secrets.token_hex(8)
    report_path = root.parent / f'clone-admin-{suffix}.json'
    activation_path = root.parent / f'activate-bulk-admin-{suffix}.ps1'
    report = {'status': 'PREPARING', 'created_at': datetime.now(timezone.utc).isoformat(),
              'clone_root': str(root), 'source_root': str(source_root),
              'original_preparation': str(preparation_path), 'source_result': preparation['source_result'],
              'book_id': preparation['book_id'], 'username': args.username,
              'password': 'NOT STORED; CAFE_FIN_BULK_PASSWORD environment only'}
    with closed_source_guard(source_root):
        phase('retained clone Admin: verifying original frozen database hash')
        before = database_fingerprint(source_db)
        require(before == preparation['source_database_after'], 'Original source changed since verified preparation.')
        phase('retained clone Admin: streaming pre-auth accounting digest')
        clone_before = accounting_digest(clone_db)
        require(clone_before == preparation['clone_accounting_digest_after_auth'],
                'Retained clone accounting data changed since its verified preparation.')
        report.update(source_database_before=before, clone_accounting_digest_before=clone_before)
        try:
            runtime = Runtime(root, initialize=False, modules=ModuleRegistry((module_manifest(),)))
            try:
                users_before = user_snapshot(runtime)
                require(all(row['username'] != args.username for row in users_before.values()),
                        'Username exists: provide a fresh name; existing credentials will never be reset.')
                admins = [row for row in users_before.values() if row['active'] and row['role'] == 'admin']
                require(admins, 'No active cloned Admin exists for trusted bootstrap.')
                captured = sorted(admins, key=lambda row: row['id'])[0]
                actor = Principal(captured['id'], captured['username'], 'admin', ('*',), captured['version'])
                created = runtime.auth.create_user(actor, username=args.username, password=password,
                                                   role='admin', request_key='bulk-resume-admin:' + suffix)
                login = runtime.auth.login(args.username, password)
                principal = runtime.auth.authenticate(login['access_token'])
                require(principal.id == created['id'] and principal.role == 'admin', 'New Admin login verification failed.')
                runtime.auth.logout(login['access_token'])
                users_after = user_snapshot(runtime)
                require(len(users_after) == len(users_before) + 1 and all(users_after.get(key) == row for key, row in users_before.items()),
                        'Existing cloned users changed or unexpected users were added.')
                with runtime.reader() as connection:
                    audit = connection.execute(select(AUDIT.c.id).where(
                        AUDIT.c.actor == actor.id, AUDIT.c.entity == 'user',
                        AUDIT.c.entity_id == created['id'], AUDIT.c.action == 'create')).first()
                require(audit is not None, 'Audited user creation was not recorded.')
                report.update(synthetic_user_id=created['id'], existing_users_unchanged=True,
                              public_login_verified=True, new_admin_audited=True, runtime_job_runner_started=False)
            finally:
                runtime.close()
            phase('retained clone Admin: verifying post-auth accounting and source conservation')
            clone_after = accounting_digest(clone_db)
            require(clone_after == clone_before, 'Clone accounting data changed during user bootstrap.')
            after = database_fingerprint(source_db)
            require(after == before, 'Original source DB hash/size/mtime changed.')
            report.update(status='PASS', source_database_after=after, source_database_unchanged=True,
                          clone_accounting_digest_after=clone_after)
            environment = {'CAFE_FIN_BULK_ROOT': str(root), 'CAFE_FIN_BULK_RESULT': preparation['source_result'],
                           'CAFE_FIN_BULK_BOOK': preparation['book_id'], 'CAFE_FIN_BULK_USERNAME': args.username,
                           'CAFE_FIN_BULK_CODE_COLUMN': args.code_column, 'CAFE_FIN_BULK_READY': '1'}
            activation = "if (-not $env:CAFE_FIN_BULK_PASSWORD) { throw 'Set the same new synthetic clone password.' }\n"
            activation += '\n'.join(f'$env:{key} = {ps_string(value)}' for key, value in environment.items()) + '\n'
            activation_path.write_text(activation, encoding='utf-8')
            report['environment_activation'] = str(activation_path)
        except Exception as exc:
            report.update(status='FAIL', failure_type=type(exc).__name__, code=getattr(exc, 'code', 'BOOTSTRAP_FAILED'))
            raise
        finally:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'PASS', 'clone_root': str(root), 'book_id': preparation['book_id'],
            'username': args.username, 'activate': str(activation_path), 'report': str(report_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', required=True, type=Path)
    parser.add_argument('--runtime-closed', action='store_true')
    parser.add_argument('--username', required=True)
    parser.add_argument('--code-column', default='code')
    args = parser.parse_args()
    try:
        print(json.dumps(add_admin(args), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'FAIL', 'error_type': type(exc).__name__,
                          'code': getattr(exc, 'code', 'BOOTSTRAP_FAILED'),
                          'message': str(exc) if isinstance(exc, ValueError) else 'Bootstrap failed; source retained.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
