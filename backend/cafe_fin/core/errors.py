from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoreError(Exception):
    code: str
    message: str
    status: int = 400
    field_errors: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.code

    def envelope(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "field_errors": self.field_errors,
                "details": self.details,
            },
            "request_id": request_id,
        }
