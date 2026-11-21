"""SQLAlchemy 2.0 models mirroring docs/03-data-model.sql (the migration is the source of truth;
`tests/test_models.py` fails if they drift)."""

import enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from seetlu.core.ids import uuid7


class UserRole(StrEnum):
    owner = "owner"
    manager = "manager"
    staff = "staff"
    installer = "installer"
    support = "support"


class LangCode(StrEnum):
    fr = "fr"
    wo = "wo"
    en = "en"


class ShopStatus(StrEnum):
    draft = "draft"
    installing = "installing"
    active = "active"
    paused = "paused"
    closed = "closed"


class KitStatus(StrEnum):
    in_stock = "in_stock"
    assigned = "assigned"
    installing = "installing"
    active = "active"
    retired = "retired"


class KitHealth(StrEnum):
    ok = "ok"
    degraded = "degraded"
    offline = "offline"
    unknown = "unknown"


class CameraRole(StrEnum):
    door = "door"
    counter = "counter"
    shelf = "shelf"


class ZoneType(StrEnum):
    door_line = "door_line"
    customer_side = "customer_side"
    staff_side = "staff_side"
    shelf = "shelf"
    ignore = "ignore"


class EventType(StrEnum):
    entry = "entry"
    exit = "exit"
    service = "service"
    wait = "wait"
    unattended = "unattended"
    after_hours_motion = "after_hours_motion"
    kit_offline = "kit_offline"


class SaleSource(StrEnum):
    wave = "wave"
    orange_money = "orange_money"
    quick_log = "quick_log"
    pos = "pos"
    cash_declaration = "cash_declaration"


class VerdictCode(StrEnum):
    learning = "learning"
    normal = "normal"
    worth_a_look = "worth_a_look"
    large_gap = "large_gap"
    not_enough_activity = "not_enough_activity"
    incomplete_data = "incomplete_data"


class ConfidenceLevel(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class AlertType(StrEnum):
    not_opened = "not_opened"
    unattended = "unattended"
    after_hours_motion = "after_hours_motion"
    kit_offline = "kit_offline"


class CommandType(StrEnum):
    clip = "clip"
    snapshot = "snapshot"
    count_check_start = "count_check_start"
    count_check_stop = "count_check_stop"
    update_agent = "update_agent"
    reboot = "reboot"


class CommandStatus(StrEnum):
    queued = "queued"
    sent = "sent"
    done = "done"
    failed = "failed"
    unavailable = "unavailable"
    expired = "expired"


def pg_enum(cls: type[enum.Enum], name: str) -> ENUM:
    return ENUM(cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


TZ = DateTime(timezone=True)
NOW = text("now()")


class Base(DeclarativeBase):
    type_annotation_map = {  # noqa: RUF012
        uuid.UUID: UUID(as_uuid=True),
        datetime: TZ,
        date: Date,
        time: Time,
        str: Text,
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid7)


def created() -> Mapped[datetime]:
    return mapped_column(server_default=NOW)


# ---------- accounts and people ----------
class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str]
    plan: Mapped[str] = mapped_column(server_default=text("'pilot'"))
    language: Mapped[LangCode] = mapped_column(pg_enum(LangCode, "lang_code"), server_default=text("'fr'"))
    clip_access_for_managers: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = created()
    deleted_at: Mapped[datetime | None]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("users_account_id_idx", "account_id"),)
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    name: Mapped[str]
    phone_e164: Mapped[str] = mapped_column(unique=True)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    language: Mapped[LangCode] = mapped_column(pg_enum(LangCode, "lang_code"), server_default=text("'fr'"))
    receives_report: Mapped[bool] = mapped_column(server_default=text("false"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    reports_paused: Mapped[bool] = mapped_column(server_default=text("false"))  # 0003
    created_at: Mapped[datetime] = created()


class OtpCode(Base):
    __tablename__ = "otp_codes"
    __table_args__ = (
        Index("otp_codes_phone_e164_expires_at_idx", "phone_e164", "expires_at"),
        Index("otp_codes_request_ip_idx", "request_ip"),
    )
    id: Mapped[uuid.UUID] = pk()
    phone_e164: Mapped[str]
    code_hash: Mapped[str]
    expires_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    consumed_at: Mapped[datetime | None]
    request_ip: Mapped[str | None]  # 0002


class RefreshToken(Base):  # 0002
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("refresh_tokens_user_id_idx", "user_id"),)
    id: Mapped[uuid.UUID] = pk()  # = JWT jti
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    replaced_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created()


# ---------- shops ----------
class Shop(Base):
    __tablename__ = "shops"
    __table_args__ = (
        Index("shops_account_id_idx", "account_id"),
        CheckConstraint("service_min_s >= 10 AND service_min_s <= 60", name="shops_service_min_s_check"),
    )
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    name: Mapped[str]
    category: Mapped[str]
    address: Mapped[str | None]
    gps_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    gps_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(server_default=text("'Africa/Dakar'"))
    opening_hours: Mapped[dict[str, Any]]
    report_time: Mapped[time] = mapped_column(server_default=text("'21:00:00'"))
    cash_prompt_time: Mapped[time] = mapped_column(server_default=text("'20:30:00'"))
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(
        server_default=text("""'{"start":"22:00","end":"07:00"}'""")
    )
    expected_staff: Mapped[int] = mapped_column(server_default=text("0"))
    service_min_s: Mapped[int] = mapped_column(server_default=text("15"))
    wait_min_s: Mapped[int] = mapped_column(server_default=text("180"))
    unattended_min_s: Mapped[int] = mapped_column(server_default=text("300"))
    cdp_declaration_ref: Mapped[str | None]
    status: Mapped[ShopStatus] = mapped_column(
        pg_enum(ShopStatus, "shop_status"), server_default=text("'draft'")
    )
    activated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class UserShop(Base):
    __tablename__ = "user_shops"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True)


# ---------- kits, cameras, zones ----------
class Kit(Base):
    __tablename__ = "kits"
    __table_args__ = (Index("kits_shop_id_idx", "shop_id"),)
    id: Mapped[uuid.UUID] = pk()
    serial: Mapped[str] = mapped_column(unique=True)
    claim_token_hash: Mapped[str]
    device_token_hash: Mapped[str | None]
    shop_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("shops.id"))
    installer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[KitStatus] = mapped_column(
        pg_enum(KitStatus, "kit_status"), server_default=text("'in_stock'")
    )
    health: Mapped[KitHealth] = mapped_column(
        pg_enum(KitHealth, "kit_health"), server_default=text("'unknown'")
    )
    agent_version: Mapped[str | None]
    frigate_version: Mapped[str | None]
    target_agent_version: Mapped[str | None]
    config_version: Mapped[int] = mapped_column(server_default=text("1"))
    last_seen_at: Mapped[datetime | None]
    installed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (UniqueConstraint("kit_id", "name", name="cameras_kit_id_name_key"),)
    id: Mapped[uuid.UUID] = pk()
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id", ondelete="CASCADE"))
    role: Mapped[CameraRole] = mapped_column(pg_enum(CameraRole, "camera_role"))
    name: Mapped[str]
    rtsp_main_path: Mapped[str]
    rtsp_sub_path: Mapped[str]
    detect_width: Mapped[int] = mapped_column(server_default=text("640"))
    detect_height: Mapped[int] = mapped_column(server_default=text("360"))
    detect_fps: Mapped[int] = mapped_column(server_default=text("5"))
    calibration_snapshot_key: Mapped[str | None]


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (
        CheckConstraint(
            "inward_side = ANY (ARRAY['left'::text, 'right'::text])", name="zones_inward_side_check"
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    camera_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    type: Mapped[ZoneType] = mapped_column(pg_enum(ZoneType, "zone_type"))
    geometry: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)
    inward_side: Mapped[str | None]
    created_at: Mapped[datetime] = created()


# ---------- time-series ----------
class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("events_shop_id_type_started_at_idx", "shop_id", "type", text("started_at DESC")),
        Index("events_started_at_idx", text("started_at DESC")),  # created by create_hypertable
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # generated on the edge (idempotency key)
    started_at: Mapped[datetime] = mapped_column(primary_key=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id"))
    camera_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cameras.id"))
    type: Mapped[EventType] = mapped_column(pg_enum(EventType, "event_type"))
    ended_at: Mapped[datetime | None]
    duration_s: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "CASE WHEN ended_at IS NULL THEN NULL "
            "ELSE (EXTRACT(epoch FROM (ended_at - started_at)))::integer END",
            persisted=True,
        ),
    )
    is_staff: Mapped[bool] = mapped_column(server_default=text("false"))
    confidence: Mapped[float] = mapped_column(REAL(), server_default=text("1.0"))
    frigate_event_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    meta: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    received_at: Mapped[datetime] = created()


class Heartbeat(Base):
    __tablename__ = "heartbeats"
    __table_args__ = (Index("heartbeats_at_idx", text("at DESC")),)  # created by create_hypertable
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id"), primary_key=True)
    at: Mapped[datetime] = mapped_column(primary_key=True)
    power_source: Mapped[str | None]
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    storage_pct: Mapped[int | None] = mapped_column(SmallInteger)
    cpu_temp_c: Mapped[float | None] = mapped_column(REAL())
    fps: Mapped[dict[str, Any] | None]
    network: Mapped[str | None]
    agent_version: Mapped[str | None]
    frigate_version: Mapped[str | None]
    queue_depth: Mapped[int | None]


# ---------- sales ----------
class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("shop_id", "source", "external_ref", name="sales_shop_id_source_external_ref_key"),
        CheckConstraint("amount_xof >= 0", name="sales_amount_xof_check"),
        Index("sales_shop_id_local_date_idx", "shop_id", "local_date"),
        Index(
            "sales_one_cash_decl",
            "shop_id",
            "local_date",
            unique=True,
            postgresql_where=text("source = 'cash_declaration'::sale_source AND voided_at IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    source: Mapped[SaleSource] = mapped_column(pg_enum(SaleSource, "sale_source"))
    amount_xof: Mapped[int] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime]
    local_date: Mapped[date]
    external_ref: Mapped[str | None]
    entered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    device_id: Mapped[uuid.UUID | None]
    raw_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created()
    voided_at: Mapped[datetime | None]


class UnparsedNotification(Base):
    __tablename__ = "unparsed_notifications"
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    package_name: Mapped[str]
    received_at: Mapped[datetime]
    raw_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created()


class PhoneDevice(Base):
    __tablename__ = "phone_devices"
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    token_hash: Mapped[str]
    model: Mapped[str | None]
    app_version: Mapped[str | None]
    parser_version: Mapped[str | None]
    last_seen_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class PhonePairCode(Base):
    __tablename__ = "phone_pair_codes"
    __table_args__ = (Index("phone_pair_codes_code_hmac_idx", "code_hmac"),)
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    code_hmac: Mapped[str]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


class PhonePairFailure(Base):
    __tablename__ = "phone_pair_failures"
    __table_args__ = (Index("phone_pair_failures_ip_at_idx", "ip", "at"),)
    id: Mapped[uuid.UUID] = pk()
    ip: Mapped[str]
    at: Mapped[datetime] = created()


# ---------- reports, baselines, corrections ----------
class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("shop_id", "local_date", name="daily_reports_shop_id_local_date_key"),)
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    local_date: Mapped[date]
    visitors_in: Mapped[int | None]
    served: Mapped[int | None]
    waits: Mapped[int | None]
    unattended_min: Mapped[int | None]
    busiest_hour: Mapped[int | None] = mapped_column(SmallInteger)
    sales_count: Mapped[int] = mapped_column(server_default=text("0"))
    sales_xof: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    sales_by_source: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    cash_declared_xof: Mapped[int | None] = mapped_column(BigInteger)
    rps_xof: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    baseline: Mapped[dict[str, Any] | None]
    verdict: Mapped[VerdictCode] = mapped_column(pg_enum(VerdictCode, "verdict_code"))
    confidence: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    missing_hours: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), server_default=text("'{}'"))
    moments: Mapped[list[Any]] = mapped_column(server_default=text("'[]'"))
    vs_last_week: Mapped[dict[str, Any] | None]
    computed_at: Mapped[datetime] = created()
    sent_at: Mapped[datetime | None]
    message_id: Mapped[str | None]


class DayCorrection(Base):
    __tablename__ = "day_corrections"
    __table_args__ = (
        CheckConstraint(
            "metric = ANY (ARRAY['visitors_in'::text, 'served'::text])", name="day_corrections_metric_check"
        ),
    )
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    local_date: Mapped[date]
    metric: Mapped[str]
    reported_value: Mapped[int | None]
    corrected_value: Mapped[int | None]
    note: Mapped[str | None]
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()


# ---------- alerts ----------
class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (UniqueConstraint("shop_id", "type", name="alert_rules_shop_id_type_key"),)
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    type: Mapped[AlertType] = mapped_column(pg_enum(AlertType, "alert_type"))
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))


class AlertSent(Base):
    __tablename__ = "alerts_sent"
    __table_args__ = (Index("alerts_sent_shop_id_local_date_idx", "shop_id", "local_date"),)
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    type: Mapped[AlertType] = mapped_column(pg_enum(AlertType, "alert_type"))
    local_date: Mapped[date]
    event_id: Mapped[uuid.UUID | None]
    sent_at: Mapped[datetime] = created()
    message_id: Mapped[str | None]


# ---------- edge commands and clips ----------
class EdgeCommand(Base):
    __tablename__ = "edge_commands"
    __table_args__ = (Index("edge_commands_kit_id_status_idx", "kit_id", "status"),)
    id: Mapped[uuid.UUID] = pk()
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id"))
    type: Mapped[CommandType] = mapped_column(pg_enum(CommandType, "command_type"))
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    status: Mapped[CommandStatus] = mapped_column(
        pg_enum(CommandStatus, "command_status"), server_default=text("'queued'")
    )
    result: Mapped[dict[str, Any] | None]
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
    notify_user_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default=text("'{}'")
    )  # 0003: WhatsApp users waiting for this clip/snapshot
    notified_at: Mapped[datetime | None]  # 0003


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        CheckConstraint("kind = ANY (ARRAY['clip'::text, 'snapshot'::text])", name="clips_kind_check"),
    )
    id: Mapped[uuid.UUID] = pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    event_id: Mapped[uuid.UUID | None]
    command_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("edge_commands.id"))
    object_key: Mapped[str]
    kind: Mapped[str]
    duration_s: Mapped[int | None]
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    saved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()


# ---------- count check ----------
class CountCheck(Base):
    __tablename__ = "count_checks"
    id: Mapped[uuid.UUID] = pk()
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id"))
    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    manual_count: Mapped[int | None]
    agent_count: Mapped[int | None]
    error_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    override_reason: Mapped[str | None]


# ---------- support grants, audit ----------
class SupportGrant(Base):
    __tablename__ = "support_grants"
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    granted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    granted_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = created()


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("audit_log_account_id_at_idx", "account_id", text("at DESC")),)
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID | None]
    actor_id: Mapped[uuid.UUID | None]
    actor_role: Mapped[UserRole | None] = mapped_column(pg_enum(UserRole, "user_role"))
    action: Mapped[str]
    target_type: Mapped[str | None]
    target_id: Mapped[uuid.UUID | None]
    detail: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    at: Mapped[datetime] = created()


# ---------- billing ----------
class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[uuid.UUID] = pk()
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    plan: Mapped[str]
    monthly_service_xof: Mapped[int] = mapped_column(BigInteger)
    kit_financing_months: Mapped[int] = mapped_column(server_default=text("0"))
    kit_monthly_xof: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    next_due_date: Mapped[date]
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    created_at: Mapped[datetime] = created()


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"))
    amount_xof: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str]
    external_ref: Mapped[str | None]
    paid_at: Mapped[datetime]
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


# ---------- dev messaging (0002) ----------
class MockMessage(Base):
    __tablename__ = "mock_messages"
    __table_args__ = (
        CheckConstraint(
            "kind = ANY (ARRAY['template'::text, 'text'::text, 'media'::text])",
            name="mock_messages_kind_check",
        ),
        Index("mock_messages_to_phone_created_at_idx", "to_phone", text("created_at DESC")),
    )
    id: Mapped[uuid.UUID] = pk()
    to_phone: Mapped[str]
    kind: Mapped[str]
    template: Mapped[str | None]
    lang: Mapped[str | None]
    params: Mapped[list[Any]] = mapped_column(server_default=text("'[]'"))
    buttons: Mapped[list[Any]] = mapped_column(server_default=text("'[]'"))
    body: Mapped[str | None]
    url: Mapped[str | None]
    created_at: Mapped[datetime] = created()


# ---------- WhatsApp conversations (0003) ----------
class WaInbound(Base):
    __tablename__ = "wa_inbound"
    id: Mapped[uuid.UUID] = pk()
    wa_message_id: Mapped[str] = mapped_column(unique=True)
    from_phone: Mapped[str]
    body: Mapped[str | None]
    received_at: Mapped[datetime] = created()
    processed_at: Mapped[datetime | None]


class WaSession(Base):
    __tablename__ = "wa_sessions"
    phone_e164: Mapped[str] = mapped_column(primary_key=True)
    state: Mapped[str]
    context: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    expires_at: Mapped[datetime]
    updated_at: Mapped[datetime] = created()


class ScheduledSend(Base):
    __tablename__ = "scheduled_sends"
    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(primary_key=True)
    local_date: Mapped[date] = mapped_column(primary_key=True)
    sent_at: Mapped[datetime] = created()
