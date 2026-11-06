import uuid

from sqlalchemy import Connection, insert, select

from .db import AUDIT, canonical_json
from .errors import CoreError
from .time import utc_now


class AuditService:
    @staticmethod
    def record(
        conn: Connection,
        *,
        actor: str,
        entity: str,
        entity_id: str,
        action: str,
        before=None,
        after=None,
    ) -> str:
        audit_id = str(uuid.uuid4())
        conn.execute(
            insert(AUDIT).values(
                id=audit_id,
                actor=actor,
                entity=entity,
                entity_id=entity_id,
                action=action,
                before_json=None if before is None else canonical_json(before),
                after_json=None if after is None else canonical_json(after),
                recorded_at=utc_now(),
            )
        )
        return audit_id

    @staticmethod
    def page(conn: Connection, entity: str, entity_id: str, page: int = 1, page_size: int = 100):
        if page < 1 or not 1 <= page_size <= 500:
            raise CoreError("INVALID_PAGE", "Tham số phân trang không hợp lệ.")
        return list(
            conn.execute(
                select(AUDIT)
                .where(AUDIT.c.entity == entity, AUDIT.c.entity_id == entity_id)
                .order_by(AUDIT.c.recorded_at, AUDIT.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
        )


def require_version(current: int, expected: int) -> int:
    if type(expected) is not int or current != expected:
        raise CoreError("VERSION_CONFLICT", "Bản ghi đã thay đổi, hãy tải lại trước khi sửa.", 409)
    return current + 1
