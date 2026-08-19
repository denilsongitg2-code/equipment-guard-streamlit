from __future__ import annotations

import json
import os
from difflib import SequenceMatcher
from typing import Any

import database as db
from services.excel_service import normalize

BLOCK_THRESHOLD = float(os.getenv("DUPLICATE_BLOCK_THRESHOLD", "0.86"))
REVIEW_THRESHOLD = float(os.getenv("DUPLICATE_REVIEW_THRESHOLD", "0.74"))


def ratio(a: Any, b: Any) -> float:
    x, y = normalize(a), normalize(b)
    if not x or not y:
        return 0.0
    return SequenceMatcher(None, x, y).ratio()


def candidate_score(item: dict[str, Any], candidate: dict[str, Any]) -> float:
    semantic = float(candidate.get("score") or 0)
    person = ratio(item.get("collaborator"), candidate.get("collaborator"))
    role = ratio(item.get("role"), candidate.get("role"))
    cc = 1.0 if normalize(item.get("cost_center")) and normalize(item.get("cost_center")) == normalize(candidate.get("cost_center")) else 0.0
    return min(1.0, semantic * 0.70 + person * 0.15 + role * 0.10 + cc * 0.05)


def analyse_item(item: dict[str, Any], milvus) -> dict[str, Any]:
    ticket = str(item.get("ticket_number") or "").strip()
    addition = str(item.get("addition_number") or "")

    previous = db.previous_approved_equipment(item["identity_key"], item.get("equipment_type") or "", addition)
    if previous:
        return {
            "analysis_status": "BLOQUEADO",
            "duplicate_score": 1.0,
            "duplicate_ticket": previous[0].get("ticket_number"),
            "analysis_reason": "Já existe equipamento do mesmo tipo aprovado/enviado para esta pessoa ou posição.",
            "evidence_json": json.dumps(previous[:5], ensure_ascii=False, default=str),
        }

    if ticket:
        same = db.same_ticket_identity(ticket, item["identity_key"], addition)
        if same:
            return {
                "analysis_status": "BLOQUEADO",
                "duplicate_score": 1.0,
                "duplicate_ticket": ticket,
                "analysis_reason": "O mesmo chamado já foi usado anteriormente para a mesma pessoa/posição.",
                "evidence_json": json.dumps(same[:5], ensure_ascii=False, default=str),
            }

    if not milvus:
        return {
            "analysis_status": "PENDENTE_MILVUS",
            "analysis_reason": "Milvus não conectado; não liberar a locação sem conferência manual.",
            "evidence_json": "[]",
        }

    source_ticket = milvus.get_ticket(ticket) if ticket else None
    if not source_ticket:
        return {
            "analysis_status": "REVISAR",
            "analysis_reason": f"Chamado {ticket or '-'} não localizado na coleção fonte do Milvus.",
            "evidence_json": "[]",
        }

    db.upsert_ticket_cache({
        "ticket_number": source_ticket.get("ticket_number"),
        "status": source_ticket.get("status"),
        "collaborator": source_ticket.get("collaborator"),
        "role": source_ticket.get("role"),
        "cost_center": source_ticket.get("cost_center"),
        "subject": source_ticket.get("subject"),
        "description": source_ticket.get("description"),
        "raw_json": json.dumps(source_ticket.get("raw") or {}, ensure_ascii=False, default=str),
    })

    candidates = milvus.search_similar(source_ticket, limit=10)
    ranked = []
    for c in candidates:
        score = candidate_score(item, c)
        ranked.append({**c, "risk_score": score})
    ranked.sort(key=lambda x: x["risk_score"], reverse=True)
    top = ranked[0] if ranked else None

    base = {
        "ticket_status": source_ticket.get("status"),
        "ticket_subject": source_ticket.get("subject"),
        "ticket_description": source_ticket.get("description"),
        "evidence_json": json.dumps(ranked[:5], ensure_ascii=False, default=str),
    }
    if not top:
        return {**base, "analysis_status": "APROVADO", "analysis_reason": "Nenhum chamado aberto semelhante foi encontrado no Milvus."}

    risk = float(top["risk_score"])
    top_ticket = str(top.get("ticket_number") or "")
    if risk >= BLOCK_THRESHOLD:
        return {
            **base,
            "analysis_status": "BLOQUEADO",
            "duplicate_score": risk,
            "duplicate_ticket": top_ticket,
            "analysis_reason": f"Alto indício de duplicidade com o chamado {top_ticket} (risco {risk:.0%}).",
        }
    if risk >= REVIEW_THRESHOLD:
        return {
            **base,
            "analysis_status": "REVISAR",
            "duplicate_score": risk,
            "duplicate_ticket": top_ticket,
            "analysis_reason": f"Possível duplicidade com o chamado {top_ticket} (risco {risk:.0%}); revisar antes de alugar.",
        }
    return {
        **base,
        "analysis_status": "APROVADO",
        "duplicate_score": risk,
        "duplicate_ticket": top_ticket,
        "analysis_reason": f"Chamados semelhantes abaixo do limite de risco (maior risco {risk:.0%}).",
    }
