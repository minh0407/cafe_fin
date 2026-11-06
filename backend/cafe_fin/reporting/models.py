"""Reporting commands. Decimal values remain strings through JSON and exports."""

from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=1, max_length=128)


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    from_on: str
    through_on: str
    book_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("from_on", "through_on")
    @classmethod
    def day(cls, value):
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Ngày cần có định dạng YYYY-MM-DD.")
        return value

    @field_validator("book_ids")
    @classmethod
    def books(cls, value):
        if len(set(value)) != len(value) or any(not x or len(x) > 128 for x in value):
            raise ValueError("Mã sổ trống, lặp hoặc quá dài.")
        return sorted(value)

    @model_validator(mode="after")
    def range(self):
        first, last = date.fromisoformat(self.from_on), date.fromisoformat(self.through_on)
        if last < first or (last - first).days > 365 or last == date.max:
            raise ValueError("Khoảng báo cáo tối đa 366 ngày, ngày cuối không trước ngày đầu.")
        return self


class Preview(Period, Command):
    reason: str = Field(default="", max_length=1000)


class Save(Command):
    expected_version: int = Field(ge=1)


class Export(Command):
    format: Literal["pdf", "xlsx", "txt"]


class Enqueue(Command):
    # Only reporting-owned sanitized summary exports can be attachments.
    attachment_export_id: str | None = Field(default=None, max_length=128)


class DeliverySettings(Command):
    expected_version: int = Field(ge=0)
    group_id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    oa_id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9_-]*$")
    enabled: bool = False
    timezone: str = "Asia/Ho_Chi_Minh"
    send_at: str | None = None
    attachments_enabled: bool = False

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Múi giờ không hợp lệ.") from None
        return value

    @field_validator("send_at")
    @classmethod
    def clock(cls, value):
        if value is not None:
            parsed = time.fromisoformat(value)
            if parsed.strftime("%H:%M") != value:
                raise ValueError("Giờ gửi cần có định dạng HH:MM.")
        return value

    @model_validator(mode="after")
    def configured(self):
        if self.enabled and (not self.group_id or not self.oa_id or not self.send_at):
            raise ValueError("Bật lịch cần OA, nhóm và giờ gửi.")
        return self


class Credentials(BaseModel):
    # Not a Command: secret bytes must NEVER enter core request receipts or audit.
    model_config = ConfigDict(extra="forbid", strict=True)
    app_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    app_secret: str = Field(min_length=1, max_length=2048)
    refresh_token: str = Field(min_length=1, max_length=4096)
    access_token: str = Field(default="", max_length=4096)


class Retry(Command):
    expected_version: int = Field(ge=1)
