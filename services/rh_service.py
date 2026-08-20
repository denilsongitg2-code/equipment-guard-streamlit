from __future__ import annotations

from typing import Any

EQUIPMENT_TYPES = ["Notebook", "Celular", "Tablet", "Monitor", "Teclado", "Mouse"]
REQUEST_STATUSES = [
    "SOLICITACAO_CRIADA",
    "EM_ANALISE_TI",
    "APROVADA_TI",
    "AGUARDANDO_ADITIVO",
    "ADITIVO_ENVIADO",
    "AGUARDANDO_FORNECEDOR",
    "RECEBIDO_TI",
    "PRONTO_ENTREGA",
    "ENTREGUE",
    "CONCLUIDO",
    "CANCELADO",
]
STATUS_LABELS = {
    "SOLICITACAO_CRIADA": "Solicitação criada",
    "EM_ANALISE_TI": "Em análise pela TI",
    "APROVADA_TI": "Aprovada pela TI",
    "AGUARDANDO_ADITIVO": "Aguardando aditivo",
    "ADITIVO_ENVIADO": "Aditivo enviado",
    "AGUARDANDO_FORNECEDOR": "Aguardando fornecedor",
    "RECEBIDO_TI": "Recebido pela TI",
    "PRONTO_ENTREGA": "Pronto para entrega",
    "ENTREGUE": "Entregue",
    "CONCLUIDO": "Concluído",
    "CANCELADO": "Cancelado",
}


def build_milvus_subject(hiring_id: str) -> str:
    return f"Solicitação de equipamento | {hiring_id}"


def build_milvus_description(integration: dict[str, Any], request: dict[str, Any]) -> str:
    items = request.get("items") or []
    item_lines = "\n".join(
        f"- {x.get('equipment_type')}" + (f" x{x.get('quantity')}" if int(x.get('quantity') or 1) > 1 else "")
        for x in items
    ) or "- Não informado"
    collaborator = integration.get("collaborator") or "A contratar"
    start = integration.get("planned_start_date")
    start_text = start.strftime("%d/%m/%Y") if hasattr(start, "strftime") else (str(start) if start else "Não informada")
    return (
        f"ID contratação: {integration.get('hiring_id')}\n"
        f"Colaborador: {collaborator}\n"
        f"Cargo: {integration.get('role') or '-'}\n"
        f"Gestor: {integration.get('manager') or '-'}\n"
        f"Centro de custo: {integration.get('cost_center') or '-'}\n"
        f"Previsão de início: {start_text}\n\n"
        f"Equipamentos solicitados:\n{item_lines}\n\n"
        f"Local de entrega: {request.get('delivery_location') or '-'}\n"
        f"Softwares/observações: {request.get('software_notes') or '-'}"
    )
