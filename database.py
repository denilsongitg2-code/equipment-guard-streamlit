from __future__ import annotations

import os
import re
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker

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


class IntegrationMap(Base):
    __tablename__ = "integration_map"
    id = Column(Integer, primary_key=True, autoincrement=True)
    hiring_id = Column(String(40), unique=True, nullable=False, index=True)
    collaborator = Column(String(255), index=True)
    role = Column(String(255), nullable=False, index=True)
    manager = Column(String(255))
    cost_center = Column(String(180), nullable=False, index=True)
    phone = Column(String(80))
    email = Column(String(255), index=True)
    planned_start_date = Column(Date, index=True)
    confirmed_start_date = Column(Date)
    integration_date = Column(Date)
    presence_status = Column(String(60), default="PENDENTE")
    integration_kit_status = Column(String(60), default="PENDENTE")
    sie_registration_status = Column(String(60), default="PENDENTE")
    sie_trail_status = Column(String(60), default="PENDENTE")
    feedz_registration_status = Column(String(60), default="PENDENTE")
    feedz_integration_status = Column(String(60), default="PENDENTE")
    wellz_status = Column(String(60), default="PENDENTE")
    ti_status = Column(String(60), default="PENDENTE")
    email_status = Column(String(60), default="PENDENTE")
    record_status = Column(String(40), nullable=False, default="ATIVO", index=True)
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EquipmentRequest(Base):
    __tablename__ = "equipment_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_code = Column(String(40), unique=True, nullable=False, index=True)
    hiring_id = Column(String(40), ForeignKey("integration_map.hiring_id"), nullable=False, index=True)
    request_type = Column(String(40), nullable=False, default="NOVA_CONTRATACAO")
    nomenclature = Column(String(120), nullable=False, default="Solicitação de equipamento")
    status = Column(String(60), nullable=False, default="SOLICITACAO_CRIADA", index=True)
    requested_by = Column(String(255))
    delivery_location = Column(Text)
    software_notes = Column(Text)
    notes = Column(Text)
    milvus_ticket = Column(String(80), index=True)
    milvus_status = Column(String(100))
    addition_number = Column(String(80), index=True)
    addition_sent_at = Column(Date)
    sla_due_date = Column(Date, index=True)
    delivered_at = Column(Date)
    closed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EquipmentRequestItem(Base):
    __tablename__ = "equipment_request_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("equipment_requests.id"), nullable=False, index=True)
    equipment_type = Column(String(80), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    details = Column(Text)
    status = Column(String(60), nullable=False, default="SOLICITADO")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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


def _norm(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


def _next_code(session, model, field_name: str, prefix: str) -> str:
    field = getattr(model, field_name)
    latest = session.scalar(select(field).where(field.like(f"{prefix}%")).order_by(field.desc()).limit(1))
    seq = 1
    if latest:
        try:
            seq = int(str(latest).rsplit("-", 1)[1]) + 1
        except Exception:
            seq = 1
    return f"{prefix}{seq:06d}"


# ---------- Mapa de Integração / RH ----------

def create_integration_record(data: dict[str, Any]) -> str:
    year = (data.get("planned_start_date") or date.today()).year
    with session_scope() as s:
        hiring_id = _next_code(s, IntegrationMap, "hiring_id", f"CONT-{year}-")
        row = IntegrationMap(hiring_id=hiring_id)
        for key, value in data.items():
            if hasattr(row, key) and key not in {"id", "hiring_id", "created_at", "updated_at"}:
                setattr(row, key, value)
        s.add(row)
        s.flush()
        return hiring_id


def update_integration_record(hiring_id: str, data: dict[str, Any]) -> None:
    with session_scope() as s:
        row = s.scalar(select(IntegrationMap).where(IntegrationMap.hiring_id == str(hiring_id)))
        if not row:
            return
        for key, value in data.items():
            if hasattr(row, key) and key not in {"id", "hiring_id", "created_at"}:
                setattr(row, key, value)
        row.updated_at = datetime.utcnow()


def get_integration_record(hiring_id: str) -> dict[str, Any] | None:
    with session_scope() as s:
        row = s.scalar(select(IntegrationMap).where(IntegrationMap.hiring_id == str(hiring_id)))
        return obj_dict(row) if row else None


def list_integration_records(limit: int = 1000, active_only: bool = False) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(IntegrationMap)
        if active_only:
            q = q.where(IntegrationMap.record_status == "ATIVO")
        q = q.order_by(IntegrationMap.created_at.desc()).limit(limit)
        return [obj_dict(x) for x in s.scalars(q).all()]


def find_integration_duplicates(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Bloqueio conservador: e-mail exato OU nome+CC+data de início exatos."""
    rows = list_integration_records(limit=2000, active_only=True)
    email = _norm(data.get("email"))
    name = _norm(data.get("collaborator"))
    cc = _norm(data.get("cost_center"))
    planned = data.get("planned_start_date")
    out = []
    for row in rows:
        if email and _norm(row.get("email")) == email:
            out.append(row)
            continue
        if name and cc and _norm(row.get("collaborator")) == name and _norm(row.get("cost_center")) == cc:
            if not planned or row.get("planned_start_date") == planned:
                out.append(row)
    return out


# ---------- Solicitações RH ----------

ACTIVE_REQUEST_STATUSES = {
    "SOLICITACAO_CRIADA", "EM_ANALISE_TI", "APROVADA_TI", "AGUARDANDO_ADITIVO",
    "ADITIVO_ENVIADO", "AGUARDANDO_FORNECEDOR", "RECEBIDO_TI", "PRONTO_ENTREGA",
    "ENTREGUE", "CONCLUIDO",
}


def _existing_equipment_for_hiring(session, hiring_id: str, equipment_type: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(EquipmentRequest.request_code, EquipmentRequest.status, EquipmentRequestItem.equipment_type)
        .join(EquipmentRequestItem, EquipmentRequestItem.request_id == EquipmentRequest.id)
        .where(
            EquipmentRequest.hiring_id == str(hiring_id),
            func.lower(EquipmentRequestItem.equipment_type) == str(equipment_type).lower(),
            EquipmentRequest.status != "CANCELADO",
        )
    ).all()
    return [dict(r._mapping) for r in rows]


def create_equipment_request(
    hiring_id: str,
    equipment_items: list[dict[str, Any]],
    requested_by: str | None = None,
    delivery_location: str | None = None,
    software_notes: str | None = None,
    notes: str | None = None,
    request_type: str = "NOVA_CONTRATACAO",
) -> str:
    if not equipment_items:
        raise ValueError("Selecione pelo menos um equipamento.")
    with session_scope() as s:
        integration = s.scalar(select(IntegrationMap).where(IntegrationMap.hiring_id == str(hiring_id)))
        if not integration:
            raise ValueError("ID de contratação não encontrado no Mapa de Integração.")

        conflicts = []
        if request_type == "NOVA_CONTRATACAO":
            for item in equipment_items:
                eq = str(item.get("equipment_type") or "").strip()
                if not eq:
                    continue
                existing = _existing_equipment_for_hiring(s, hiring_id, eq)
                if existing:
                    conflicts.append((eq, existing[0]["request_code"], existing[0]["status"]))
        if conflicts:
            detail = "; ".join(f"{eq} já consta em {code} ({status})" for eq, code, status in conflicts)
            raise ValueError(f"Duplicidade bloqueada para o ID {hiring_id}: {detail}.")

        year = date.today().year
        code = _next_code(s, EquipmentRequest, "request_code", f"SOL-{year}-")
        req = EquipmentRequest(
            request_code=code,
            hiring_id=str(hiring_id),
            request_type=request_type,
            requested_by=requested_by,
            delivery_location=delivery_location,
            software_notes=software_notes,
            notes=notes,
        )
        s.add(req)
        s.flush()
        for item in equipment_items:
            eq = str(item.get("equipment_type") or "").strip()
            if not eq:
                continue
            s.add(EquipmentRequestItem(
                request_id=req.id,
                equipment_type=eq,
                quantity=max(1, int(item.get("quantity") or 1)),
                details=item.get("details"),
            ))
        s.flush()
        return code


def list_equipment_requests(hiring_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = (
            select(
                EquipmentRequest.id,
                EquipmentRequest.request_code,
                EquipmentRequest.hiring_id,
                EquipmentRequest.request_type,
                EquipmentRequest.nomenclature,
                EquipmentRequest.status,
                EquipmentRequest.requested_by,
                EquipmentRequest.delivery_location,
                EquipmentRequest.software_notes,
                EquipmentRequest.notes,
                EquipmentRequest.milvus_ticket,
                EquipmentRequest.milvus_status,
                EquipmentRequest.addition_number,
                EquipmentRequest.addition_sent_at,
                EquipmentRequest.sla_due_date,
                EquipmentRequest.delivered_at,
                EquipmentRequest.created_at,
                IntegrationMap.collaborator,
                IntegrationMap.role,
                IntegrationMap.manager,
                IntegrationMap.cost_center,
                IntegrationMap.email,
                IntegrationMap.planned_start_date,
            )
            .join(IntegrationMap, IntegrationMap.hiring_id == EquipmentRequest.hiring_id)
        )
        if hiring_id:
            q = q.where(EquipmentRequest.hiring_id == str(hiring_id))
        q = q.order_by(EquipmentRequest.created_at.desc()).limit(limit)
        return [dict(r._mapping) for r in s.execute(q).all()]


def get_equipment_request(request_code: str) -> dict[str, Any] | None:
    rows = list_equipment_requests(limit=2000)
    req = next((x for x in rows if x["request_code"] == str(request_code)), None)
    if not req:
        return None
    with session_scope() as s:
        request_id = req["id"]
        items = s.scalars(select(EquipmentRequestItem).where(EquipmentRequestItem.request_id == request_id).order_by(EquipmentRequestItem.id)).all()
        req = dict(req)
        req["items"] = [obj_dict(x) for x in items]
    return req


def update_equipment_request(request_code: str, **changes: Any) -> None:
    with session_scope() as s:
        row = s.scalar(select(EquipmentRequest).where(EquipmentRequest.request_code == str(request_code)))
        if not row:
            return
        allowed = {
            "status", "milvus_ticket", "milvus_status", "addition_number", "addition_sent_at",
            "sla_due_date", "delivered_at", "notes", "delivery_location", "software_notes",
        }
        for key, value in changes.items():
            if key in allowed:
                setattr(row, key, value)
        if changes.get("status") in {"CONCLUIDO", "CANCELADO"}:
            row.closed_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()


def equipment_request_items(request_code: str) -> list[dict[str, Any]]:
    req = get_equipment_request(request_code)
    return req.get("items", []) if req else []


# ---------- Aditivos (legado/contingência) ----------

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
