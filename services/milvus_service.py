from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.preprocessing import normalize

ANALYSIS_DIM = int(os.getenv("MILVUS_ANALYSIS_DIM", "384"))
OPEN_DEFAULT = "aberto,em aberto,open,novo,new,pendente,em andamento,in progress,aguardando"


class MilvusGateway:
    """Consulta a coleção fonte por número de chamado e mantém uma coleção vetorial própria para análise semântica."""

    def __init__(self):
        from pymilvus import MilvusClient

        self.uri = os.getenv("MILVUS_URI", "").strip()
        if not self.uri:
            raise RuntimeError("MILVUS_URI não configurado")
        token = os.getenv("MILVUS_TOKEN", "").strip()
        kwargs: dict[str, Any] = {"uri": self.uri}
        if token:
            kwargs["token"] = token
        self.client = MilvusClient(**kwargs)

        self.source_collection = os.getenv("MILVUS_SOURCE_COLLECTION", "chamados")
        self.analysis_collection = os.getenv("MILVUS_ANALYSIS_COLLECTION", "af_chamados_analise")
        self.ticket_field = os.getenv("MILVUS_TICKET_FIELD", "ticket_number")
        self.status_field = os.getenv("MILVUS_STATUS_FIELD", "status")
        self.text_field = os.getenv("MILVUS_TEXT_FIELD", "description")
        self.subject_field = os.getenv("MILVUS_SUBJECT_FIELD", "subject")
        self.collaborator_field = os.getenv("MILVUS_COLLABORATOR_FIELD", "collaborator")
        self.role_field = os.getenv("MILVUS_ROLE_FIELD", "role")
        self.cost_center_field = os.getenv("MILVUS_COST_CENTER_FIELD", "cost_center")
        self.open_statuses = [x.strip().lower() for x in os.getenv("MILVUS_OPEN_STATUSES", OPEN_DEFAULT).split(",") if x.strip()]
        self.open_filter = os.getenv("MILVUS_OPEN_FILTER", "").strip()
        self.sync_limit = int(os.getenv("MILVUS_SYNC_LIMIT", "2000"))
        self.vectorizer = HashingVectorizer(
            n_features=ANALYSIS_DIM, alternate_sign=False, norm=None,
            analyzer="word", ngram_range=(1, 2), lowercase=True,
        )
        self.vector_enabled = True
        self._open_cache: list[dict[str, Any]] = []
        try:
            self._ensure_analysis_collection()
        except Exception:
            self.vector_enabled = False

    def _ensure_analysis_collection(self) -> None:
        if not self.client.has_collection(collection_name=self.analysis_collection):
            self.client.create_collection(
                collection_name=self.analysis_collection,
                dimension=ANALYSIS_DIM,
                metric_type="COSINE",
                enable_dynamic_field=True,
            )

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _embed(self, texts: list[str]) -> list[list[float]]:
        matrix = normalize(self.vectorizer.transform(texts), norm="l2", axis=1)
        return np.asarray(matrix.toarray(), dtype=np.float32).tolist()

    def _canonical(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticket_number": str(raw.get(self.ticket_field) or raw.get("ticket_number") or raw.get("chamado") or ""),
            "status": raw.get(self.status_field) or raw.get("status"),
            "collaborator": raw.get(self.collaborator_field) or raw.get("collaborator") or raw.get("colaborador"),
            "role": raw.get(self.role_field) or raw.get("role") or raw.get("cargo"),
            "cost_center": raw.get(self.cost_center_field) or raw.get("cost_center") or raw.get("centro_custo"),
            "subject": raw.get(self.subject_field) or raw.get("subject") or raw.get("assunto"),
            "description": raw.get(self.text_field) or raw.get("description") or raw.get("descricao") or raw.get("text"),
            "raw": raw,
        }

    @staticmethod
    def ticket_text(ticket: dict[str, Any]) -> str:
        return " | ".join(filter(None, [
            f"Chamado {ticket.get('ticket_number', '')}",
            f"Status {ticket.get('status', '')}",
            f"Colaborador {ticket.get('collaborator', '')}",
            f"Cargo {ticket.get('role', '')}",
            f"Centro de custo {ticket.get('cost_center', '')}",
            f"Assunto {ticket.get('subject', '')}",
            f"Descrição {ticket.get('description', '')}",
        ]))

    def get_ticket(self, ticket_number: str) -> dict[str, Any] | None:
        ticket_number = str(ticket_number).strip()
        if not ticket_number:
            return None
        expr = f'{self.ticket_field} == "{self._escape(ticket_number)}"'
        try:
            rows = self.client.query(
                collection_name=self.source_collection, filter=expr, output_fields=["*"], limit=5
            )
        except Exception:
            if not ticket_number.isdigit():
                raise
            rows = self.client.query(
                collection_name=self.source_collection, filter=f"{self.ticket_field} == {int(ticket_number)}",
                output_fields=["*"], limit=5
            )
        return self._canonical(rows[0]) if rows else None

    def get_open_tickets(self) -> list[dict[str, Any]]:
        if self.open_filter:
            expr = self.open_filter
        else:
            variants = []
            for status in self.open_statuses:
                for value in (status, status.upper(), status.title()):
                    if value not in variants:
                        variants.append(value)
            quoted = ", ".join(f'"{self._escape(s)}"' for s in variants)
            expr = f'{self.status_field} in [{quoted}]'
        rows = self.client.query(
            collection_name=self.source_collection,
            filter=expr,
            output_fields=["*"],
            limit=self.sync_limit,
        )
        return [self._canonical(x) for x in rows]

    def sync_open_tickets(self) -> int:
        tickets = self.get_open_tickets()
        self._open_cache = tickets
        entities = []
        for t in tickets:
            number = str(t.get("ticket_number") or "").strip()
            if not number:
                continue
            text = self.ticket_text(t)
            stable_id = int(hashlib.sha256(number.encode("utf-8")).hexdigest()[:12], 16) % 2_000_000_000
            entities.append({
                "id": stable_id,
                "vector": self._embed([text])[0],
                "ticket_number": number,
                "status": str(t.get("status") or ""),
                "collaborator": str(t.get("collaborator") or ""),
                "role": str(t.get("role") or ""),
                "cost_center": str(t.get("cost_center") or ""),
                "subject": str(t.get("subject") or ""),
                "description": str(t.get("description") or ""),
                "text": text[:12000],
            })
        if entities and self.vector_enabled:
            try:
                self.client.upsert(collection_name=self.analysis_collection, data=entities)
            except Exception:
                self.vector_enabled = False
        return len(entities)

    def search_similar(self, ticket: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        query = self.ticket_text(ticket)
        current = str(ticket.get("ticket_number") or "")
        if self.vector_enabled:
            res = self.client.search(
                collection_name=self.analysis_collection,
                data=self._embed([query]),
                limit=max(10, limit + 3),
                output_fields=["ticket_number", "status", "collaborator", "role", "cost_center", "subject", "description", "text"],
            )
            output = []
            for hit in (res[0] if res else []):
                entity = hit.get("entity") or {}
                if str(entity.get("ticket_number") or "") == current:
                    continue
                output.append({
                    "ticket_number": entity.get("ticket_number"),
                    "status": entity.get("status"),
                    "collaborator": entity.get("collaborator"),
                    "role": entity.get("role"),
                    "cost_center": entity.get("cost_center"),
                    "subject": entity.get("subject"),
                    "description": entity.get("description"),
                    "score": float(hit.get("distance", 0) or 0),
                })
                if len(output) >= limit:
                    break
            return output

        candidates = [x for x in self._open_cache if str(x.get("ticket_number") or "") != current]
        if not candidates:
            return []
        texts = [self.ticket_text(x) for x in candidates]
        qv = np.asarray(self._embed([query])[0], dtype=np.float32)
        cvs = np.asarray(self._embed(texts), dtype=np.float32)
        scores = cvs @ qv
        order = np.argsort(scores)[::-1][:limit]
        output = []
        for idx in order:
            c = candidates[int(idx)]
            output.append({**{k: c.get(k) for k in ("ticket_number", "status", "collaborator", "role", "cost_center", "subject", "description")}, "score": float(scores[int(idx)])})
        return output

    def connection_info(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "source_collection": self.source_collection,
            "analysis_collection": self.analysis_collection,
            "vector_search": self.vector_enabled,
        }


def get_milvus() -> MilvusGateway | None:
    try:
        return MilvusGateway()
    except Exception:
        return None
