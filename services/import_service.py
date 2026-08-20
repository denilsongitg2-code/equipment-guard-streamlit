from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

import database as db
from services.analysis_service import analyse_item
from services.excel_service import dataframe_to_records
from services.schedule_service import next_send_date


def import_aditivo(df, filename: str, milvus=None) -> dict[str, Any]:
    records = dataframe_to_records(df)
    if not records:
        raise ValueError("A planilha não possui linhas válidas para importação.")

    additions = sorted({str(x["addition_number"]) for x in records})
    for number in additions:
        db.upsert_aditivo({
            "addition_number": number,
            "source_filename": filename,
            "planned_send_date": next_send_date(date.today()),
            "workflow_status": "PENDENTE_CONFERENCIA",
        })

    sync_count = 0
    if milvus:
        try:
            sync_count = milvus.sync_open_tickets()
        except Exception:
            sync_count = 0

    # Detecta repetição dentro do próprio arquivo sem tratar chamadas multiusuário como duplicidade automática.
    exact_counter = Counter((r.get("ticket_number"), r.get("identity_key"), (r.get("equipment_type") or "").lower()) for r in records)

    stats = Counter()
    for item in records:
        duplicate_in_file = exact_counter[(item.get("ticket_number"), item.get("identity_key"), (item.get("equipment_type") or "").lower())] > 1
        if duplicate_in_file:
            analysis = {
                "analysis_status": "BLOQUEADO",
                "duplicate_score": 1.0,
                "duplicate_ticket": item.get("ticket_number"),
                "analysis_reason": "Mesma combinação de chamado + pessoa/posição + tipo de equipamento aparece mais de uma vez no arquivo.",
                "evidence_json": "[]",
            }
        else:
            analysis = analyse_item(item, milvus)
        payload = {**item, **analysis}
        db.insert_or_update_item(payload)
        stats[analysis["analysis_status"]] += 1

    return {
        "aditivos": additions,
        "linhas": len(records),
        "chamados_abertos_consultados": sync_count,
        "status": dict(stats),
    }
