from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import declarative_base, sessionmaker

# Streamlit Community Cloud clona apenas arquivos versionados. Como pastas vazias
# nao existem no Git, garantimos a criacao da pasta local antes de abrir o SQLite.
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "equipment_guard.db"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

if DATABASE_URL.startswith("sqlite"):
    if DATABASE_URL.startswith("sqlite:///"):
        raw_path = DATABASE_URL[len("sqlite:///"):]
        if raw_path and raw_path != ":memory:":
            db_path = Path(raw_path)
            if not db_path.is_absolute():
                db_path = (BASE_DIR / db_path).resolve()
                DATABASE_URL = f"sqlite:///{db_path.as_posix()}"
            db_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class Aditivo(Base):
    __tablename__ = "aditivos"
    addition_number = Column(String(80), primary_key=True)
    source_filename = Column(String(255))
    imported_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    planned_send_date = Column(Date)
    workflow_status = Column(String(40), nullable=False, default="PENDENTE_CONFERENCIA")
    sent_at = Column(DateTime)
    notes = Column(Text)


class AditivoItem(Base):
    __tablename__ = "aditivo_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    row_hash = Column(String(64), unique=True, nullable=False, index=True)
    source_row = Column(Integer)
    addition_number = Column(String(80), ForeignKey("aditivos.addition_number"), nullable=False, index=True)
    ticket_number = Column(String(80), index=True)
    collaborator = Column(String(255))
    role = Column(String(255))
    identity_key = Column(String(500), index=True)
    collaborator_is_position = Column(Boolean, nullable=False, default=False)
    equipment_type = Column(String(120))
    model = Column(String(255))
    processor = Column(String(255))
    memory = Column(String(120))
    disk = Column(String(120))
    screen = Column(String(120))
    office = Column(String(120))
    windows = Column(String(180))
    video_card = Column(String(180))
    delivery_location = Column(Text)
    contact_email = Column(String(255))
    cost_center = Column(String(180), index=True)
    cnpj = Column(String(40))
    ticket_status = Column(String(100))
    ticket_subject = Column(Text)
    ticket_description = Column(Text)
    analysis_status = Column(String(40), nullable=False, default="PENDENTE_MILVUS", index=True)
    duplicate_score = Column(Float)
    duplicate_ticket = Column(String(80))
    analysis_reason = Column(Text)
    evidence_json = Column(Text)
    manual_note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TicketCache(Base):
    __tablename__ = "ticket_cache"
    ticket_number = Column(String(80), primary_key=True)
    status = Column(String(100))
    collaborator = Column(String(255))
    role = Column(String(255))
    cost_center = Column(String(180))
    subject = Column(Text)
    description = Column(Text)
    raw_json = Column(Text)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def obj_dict(obj: Any) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def get_aditivo(number: str) -> dict[str, Any] | None:
    with session_scope() as s:
        row = s.get(Aditivo, str(number))
        return obj_dict(row) if row else None


def list_aditivos(limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.scalars(select(Aditivo).order_by(Aditivo.imported_at.desc()).limit(limit)).all()
        return [obj_dict(x) for x in rows]


def upsert_aditivo(data: dict[str, Any]) -> None:
    with session_scope() as s:
        row = s.get(Aditivo, str(data["addition_number"]))
        if row is None:
            row = Aditivo(addition_number=str(data["addition_number"]))
            s.add(row)
        for key in ("source_filename", "planned_send_date", "workflow_status", "sent_at", "notes"):
            if key in data:
                setattr(row, key, data[key])
        if not row.imported_at:
            row.imported_at = datetime.utcnow()


def insert_or_update_item(data: dict[str, Any]) -> int:
    with session_scope() as s:
        row = s.scalar(select(AditivoItem).where(AditivoItem.row_hash == data["row_hash"]))
        if row is None:
            row = AditivoItem(row_hash=data["row_hash"], addition_number=str(data["addition_number"]))
            s.add(row)
        for key, value in data.items():
            if hasattr(row, key) and key not in {"id", "created_at"}:
                setattr(row, key, value)
        s.flush()
        return int(row.id)


def update_item_analysis(item_id: int, status: str, note: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(AditivoItem, int(item_id))
        if not row:
            return
        row.analysis_status = status
        if note is not None:
            row.manual_note = note


def list_items(addition_number: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(AditivoItem)
        if addition_number is not None:
            q = q.where(AditivoItem.addition_number == str(addition_number))
        q = q.order_by(AditivoItem.id)
        return [obj_dict(x) for x in s.scalars(q).all()]


def previous_approved_equipment(identity_key: str, equipment_type: str, exclude_addition: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = (
            select(AditivoItem)
            .join(Aditivo, Aditivo.addition_number == AditivoItem.addition_number)
            .where(
                AditivoItem.identity_key == identity_key,
                func.lower(AditivoItem.equipment_type) == str(equipment_type).lower(),
                AditivoItem.analysis_status == "APROVADO",
                Aditivo.workflow_status.in_(["LIBERADO_ENVIO", "ENVIADO"]),
                AditivoItem.addition_number != str(exclude_addition),
            )
        )
        return [obj_dict(x) for x in s.scalars(q).all()]


def same_ticket_identity(ticket_number: str, identity_key: str, exclude_addition: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(AditivoItem).where(
            AditivoItem.ticket_number == str(ticket_number),
            AditivoItem.identity_key == identity_key,
            AditivoItem.addition_number != str(exclude_addition),
        )
        return [obj_dict(x) for x in s.scalars(q).all()]


def upsert_ticket_cache(data: dict[str, Any]) -> None:
    number = str(data.get("ticket_number") or "").strip()
    if not number:
        return
    with session_scope() as s:
        row = s.get(TicketCache, number)
        if row is None:
            row = TicketCache(ticket_number=number)
            s.add(row)
        for key in ("status", "collaborator", "role", "cost_center", "subject", "description", "raw_json"):
            setattr(row, key, data.get(key))
        row.synced_at = datetime.utcnow()


def get_ticket_cache(ticket_number: str) -> dict[str, Any] | None:
    with session_scope() as s:
        row = s.get(TicketCache, str(ticket_number))
        return obj_dict(row) if row else None


def set_aditivo_status(number: str, status: str, notes: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(Aditivo, str(number))
        if not row:
            return
        row.workflow_status = status
        if notes is not None:
            row.notes = notes
        if status == "ENVIADO":
            row.sent_at = datetime.utcnow()


def dashboard_rows() -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = s.execute(
            select(
                AditivoItem.id,
                AditivoItem.addition_number,
                AditivoItem.equipment_type,
                AditivoItem.analysis_status,
                AditivoItem.cost_center,
                AditivoItem.role,
                AditivoItem.collaborator,
                AditivoItem.ticket_number,
                Aditivo.workflow_status,
                Aditivo.imported_at,
                Aditivo.planned_send_date,
                Aditivo.sent_at,
            ).join(Aditivo, Aditivo.addition_number == AditivoItem.addition_number)
        ).all()
        return [dict(r._mapping) for r in rows]
