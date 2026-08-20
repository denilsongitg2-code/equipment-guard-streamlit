from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from typing import Any, BinaryIO

import pandas as pd

EXPECTED = {
    "aditivo": "addition_number",
    "chamado": "ticket_number",
    "colaborador": "collaborator",
    "cargo": "role",
    "tipo": "equipment_type",
    "modelo": "model",
    "processador": "processor",
    "memoria": "memory",
    "hd": "disk",
    "tela": "screen",
    "office": "office",
    "windows": "windows",
    "placa de video": "video_card",
    "local de entrega": "delivery_location",
    "email contato": "contact_email",
    "centro de custos para faturamento": "cost_center",
    "cnpj": "cnpj",
}


def normalize(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s+", " ", text)
    return text


def clean(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def detect_header_row(file_or_bytes: BinaryIO | bytes, sheet_name: int | str = 0) -> int:
    if hasattr(file_or_bytes, "seek"):
        file_or_bytes.seek(0)
    raw = pd.read_excel(file_or_bytes, sheet_name=sheet_name, header=None, nrows=15)
    best_idx, best_score = 0, -1
    expected = set(EXPECTED)
    for idx, row in raw.iterrows():
        values = {normalize(v) for v in row.tolist() if clean(v)}
        score = len(values & expected)
        if score > best_score:
            best_idx, best_score = int(idx), score
    if best_score < 3:
        raise ValueError("Não encontrei a linha de cabeçalho. Preciso localizar pelo menos Aditivo, Chamado e Colaborador/Cargo.")
    return best_idx


def read_aditivo(file_or_bytes: BinaryIO | bytes, sheet_name: int | str = 0) -> tuple[pd.DataFrame, int]:
    header = detect_header_row(file_or_bytes, sheet_name)
    if hasattr(file_or_bytes, "seek"):
        file_or_bytes.seek(0)
    df = pd.read_excel(file_or_bytes, sheet_name=sheet_name, header=header)
    rename = {}
    for col in df.columns:
        key = normalize(col)
        if key in EXPECTED:
            rename[col] = EXPECTED[key]
    df = df.rename(columns=rename)
    required = {"addition_number", "ticket_number", "role", "equipment_type"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError("Colunas obrigatórias não encontradas: " + ", ".join(missing))
    df = df.dropna(how="all")
    for c in EXPECTED.values():
        if c not in df.columns:
            df[c] = None
    return df[list(EXPECTED.values())], header


def identity_for(collaborator: Any, role: Any, cost_center: Any) -> tuple[str, bool]:
    person = normalize(clean(collaborator))
    job = normalize(clean(role))
    cc = normalize(clean(cost_center))
    is_position = bool(job) and (not person or person == job)
    if is_position:
        return f"cargo:{job}|cc:{cc or 'sem-cc'}", True
    if person:
        return f"pessoa:{person}", False
    if job:
        return f"cargo:{job}|cc:{cc or 'sem-cc'}", True
    return f"sem-identidade|cc:{cc or 'sem-cc'}", True


def row_hash(row: dict[str, Any]) -> str:
    raw = "|".join(str(row.get(k) or "") for k in (
        "addition_number", "source_row", "ticket_number", "collaborator", "role", "equipment_type", "model", "cost_center"
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for source_row, (_, r) in enumerate(df.iterrows(), start=1):
        data = {c: clean(r.get(c)) for c in df.columns}
        data["source_row"] = source_row
        if not data.get("addition_number") or not data.get("equipment_type"):
            continue
        data["addition_number"] = str(data["addition_number"])
        if data.get("ticket_number"):
            data["ticket_number"] = str(data["ticket_number"])
        identity, is_position = identity_for(data.get("collaborator"), data.get("role"), data.get("cost_center"))
        data["identity_key"] = identity
        data["collaborator_is_position"] = is_position
        data["row_hash"] = row_hash(data)
        records.append(data)
    return records
