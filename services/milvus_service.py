from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DEFAULT_API_URL = "https://apiintegracao.milvus.com.br/api/chamado/listagem"
DEFAULT_CLOSED = "finalizado,encerrado,resolvido,fechado,concluido,concluído,cancelado"


class MilvusAPIError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


def _extract_role(description: str | None) -> str | None:
    """Tenta capturar assinatura no padrão CARGO / CENTRO DE CUSTO."""
    if not description:
        return None
    lines = [re.sub(r"\s+", " ", x).strip(" -\t") for x in str(description).splitlines()]
    for line in lines:
        if "/" not in line:
            continue
        left, right = [x.strip() for x in line.split("/", 1)]
        if re.search(r"\b\d{2}[.\-]\d{2}[.\-]\d{4}\b", right) and 2 <= len(left) <= 120:
            return left
    return None


def _extract_cost_center(*values: Any) -> str | None:
    for value in values:
        if not value:
            continue
        text = str(value)
        match = re.search(r"\b\d{2}[.]\d{2}[.]\d{4}(?:[.]\d{3})?\b", text)
        if match:
            return match.group(0)
        match = re.search(r"\bobra\s*[- ]?\s*\d{2,4}\b", text, flags=re.I)
        if match:
            return match.group(0)
    return None


class MilvusGateway:
    """Cliente da API do Milvus ITSM + comparação local de chamados abertos."""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        auth_prefix: str | None = None,
    ) -> None:
        self.api_url = (api_url or os.getenv("MILVUS_API_URL") or DEFAULT_API_URL).strip() or DEFAULT_API_URL
        self.api_key = (api_key or os.getenv("MILVUS_API_KEY") or os.getenv("MILVUS_TOKEN") or "").strip()
        if not self.api_key:
            raise RuntimeError("MILVUS_API_KEY não configurado")

        if auth_prefix is None:
            auth_prefix = os.getenv("MILVUS_AUTH_PREFIX", "")
        self.auth_prefix = str(auth_prefix or "").strip()
        self.timeout = int(os.getenv("MILVUS_TIMEOUT", "45"))
        self.page_size = max(1, min(int(os.getenv("MILVUS_PAGE_SIZE", "1000")), 1000))
        self.max_pages = max(1, int(os.getenv("MILVUS_MAX_PAGES", "5")))
        self.lookback_days = max(0, int(os.getenv("MILVUS_LOOKBACK_DAYS", "0")))
        self.closed_statuses = {
            _norm(x) for x in os.getenv("MILVUS_CLOSED_STATUSES", DEFAULT_CLOSED).split(",") if x.strip()
        }
        self._open_cache: list[dict[str, Any]] = []

    def _headers(self) -> dict[str, str]:
        token = f"{self.auth_prefix} {self.api_key}".strip() if self.auth_prefix else self.api_key
        return {
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _fetch_page(self, filtro: dict[str, Any] | None = None, page: int = 1, total: int | None = None) -> dict[str, Any]:
        params = {
            "pagina": int(page),
            "total_registros": int(total or self.page_size),
        }
        payload = {"filtro_body": filtro or {}}
        try:
            response = requests.post(
                self.api_url,
                params=params,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise MilvusAPIError(f"Falha de comunicação com o Milvus: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500].strip()
            raise MilvusAPIError(f"HTTP {response.status_code} ao consultar Milvus: {detail or 'sem detalhe'}")
        try:
            data = response.json()
        except ValueError as exc:
            raise MilvusAPIError("A API do Milvus retornou resposta que não é JSON.") from exc
        if not isinstance(data, dict):
            raise MilvusAPIError("Formato inesperado na resposta da API do Milvus.")
        return data

    @staticmethod
    def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("lista", "data", "items", "chamados"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        return []

    @staticmethod
    def _last_page(data: dict[str, Any]) -> int | None:
        try:
            return int(data["meta"]["paginate"]["last_page"])
        except Exception:
            return None

    def _canonical(self, raw: dict[str, Any]) -> dict[str, Any]:
        description = raw.get("descricao") or raw.get("description") or ""
        subject = raw.get("assunto") or raw.get("subject") or ""
        collaborator = raw.get("contato") or raw.get("solicitante") or raw.get("colaborador") or ""
        role = raw.get("cargo") or _extract_role(description)
        cost_center = (
            raw.get("centro_custo")
            or raw.get("centro_de_custo")
            or _extract_cost_center(raw.get("setor"), description, subject)
        )
        return {
            "ticket_number": str(raw.get("codigo") or raw.get("ticket_number") or raw.get("chamado") or "").strip(),
            "status": raw.get("status"),
            "collaborator": collaborator,
            "role": role,
            "cost_center": cost_center,
            "subject": subject,
            "description": description,
            "contact_email": raw.get("email_conferencia") or raw.get("email"),
            "sector": raw.get("setor"),
            "created_at": raw.get("data_criacao"),
            "updated_at": raw.get("data_modificacao"),
            "workdesk": raw.get("mesa_trabalho"),
            "raw": raw,
        }

    @staticmethod
    def ticket_text(ticket: dict[str, Any]) -> str:
        return " | ".join(
            filter(
                None,
                [
                    str(ticket.get("subject") or ""),
                    str(ticket.get("description") or ""),
                    str(ticket.get("collaborator") or ""),
                    str(ticket.get("role") or ""),
                    str(ticket.get("cost_center") or ""),
                    str(ticket.get("sector") or ""),
                ],
            )
        )

    def _is_open(self, ticket: dict[str, Any]) -> bool:
        status = _norm(ticket.get("status"))
        if not status:
            return True
        return status not in self.closed_statuses

    def get_ticket(self, ticket_number: str) -> dict[str, Any] | None:
        number = str(ticket_number or "").strip()
        if not number:
            return None
        codigo: Any = int(number) if number.isdigit() else number
        data = self._fetch_page({"codigo": codigo}, page=1, total=50)
        rows = [self._canonical(x) for x in self._rows(data)]
        exact = next((x for x in rows if str(x.get("ticket_number")) == number), None)
        return exact or (rows[0] if rows else None)

    def get_open_tickets(self) -> list[dict[str, Any]]:
        filtro: dict[str, Any] = {}
        if self.lookback_days:
            start = datetime.now() - timedelta(days=self.lookback_days)
            filtro["data_hora_criacao_inicial"] = start.strftime("%Y-%m-%d 00:00:00")
            filtro["data_hora_criacao_final"] = datetime.now().strftime("%Y-%m-%d 23:59:59")

        output: list[dict[str, Any]] = []
        for page in range(1, self.max_pages + 1):
            data = self._fetch_page(filtro, page=page, total=self.page_size)
            rows = self._rows(data)
            if not rows:
                break
            output.extend(self._canonical(x) for x in rows)
            last_page = self._last_page(data)
            if last_page is not None and page >= last_page:
                break
            if len(rows) < self.page_size:
                break
        return [x for x in output if self._is_open(x)]

    def sync_open_tickets(self) -> int:
        self._open_cache = self.get_open_tickets()
        return len(self._open_cache)

    def search_similar(self, ticket: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        current = str(ticket.get("ticket_number") or "")
        candidates = [x for x in self._open_cache if str(x.get("ticket_number") or "") != current]
        if not candidates:
            candidates = [x for x in self.get_open_tickets() if str(x.get("ticket_number") or "") != current]
            self._open_cache = candidates + ([ticket] if self._is_open(ticket) else [])
        if not candidates:
            return []

        query_text = self.ticket_text(ticket)
        candidate_texts = [self.ticket_text(x) for x in candidates]
        corpus = [query_text] + candidate_texts
        try:
            vectorizer = TfidfVectorizer(
                strip_accents="unicode",
                lowercase=True,
                ngram_range=(1, 2),
                min_df=1,
                max_features=20000,
            )
            matrix = vectorizer.fit_transform(corpus)
            scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
        except ValueError:
            scores = [0.0] * len(candidates)

        order = sorted(range(len(candidates)), key=lambda i: float(scores[i]), reverse=True)[:limit]
        result: list[dict[str, Any]] = []
        for idx in order:
            c = candidates[idx]
            result.append({
                "ticket_number": c.get("ticket_number"),
                "status": c.get("status"),
                "collaborator": c.get("collaborator"),
                "role": c.get("role"),
                "cost_center": c.get("cost_center"),
                "subject": c.get("subject"),
                "description": c.get("description"),
                "contact_email": c.get("contact_email"),
                "sector": c.get("sector"),
                "created_at": c.get("created_at"),
                "score": float(scores[idx]),
            })
        return result

    def search_text(self, query_text: str, limit: int = 10) -> list[dict[str, Any]]:
        """Busca chamados abertos semelhantes a um texto livre (usado pelo Portal RH/TI)."""
        candidates = self._open_cache or self.get_open_tickets()
        self._open_cache = candidates
        if not candidates or not str(query_text or "").strip():
            return []
        corpus = [str(query_text)] + [self.ticket_text(x) for x in candidates]
        try:
            vectorizer = TfidfVectorizer(
                strip_accents="unicode", lowercase=True, ngram_range=(1, 2), min_df=1, max_features=20000
            )
            matrix = vectorizer.fit_transform(corpus)
            scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
        except ValueError:
            scores = [0.0] * len(candidates)
        order = sorted(range(len(candidates)), key=lambda i: float(scores[i]), reverse=True)[:limit]
        result = []
        for idx in order:
            c = candidates[idx]
            result.append({
                "ticket_number": c.get("ticket_number"),
                "status": c.get("status"),
                "collaborator": c.get("collaborator"),
                "role": c.get("role"),
                "cost_center": c.get("cost_center"),
                "subject": c.get("subject"),
                "description": c.get("description"),
                "created_at": c.get("created_at"),
                "score": float(scores[idx]),
            })
        return result

    def connection_info(self) -> dict[str, Any]:
        return {
            "api_url": self.api_url,
            "authentication": "MILVUS_API_KEY configurado",
            "page_size": self.page_size,
            "max_pages": self.max_pages,
            "lookback_days": self.lookback_days or "sem limite de data",
            "open_cache": len(self._open_cache),
        }

    def healthcheck(self) -> bool:
        self._fetch_page({}, page=1, total=1)
        return True


def get_milvus(
    api_key: str | None = None,
    api_url: str | None = None,
    auth_prefix: str | None = None,
) -> MilvusGateway | None:
    """Cria o cliente Milvus. Aceita configuração explícita para Streamlit Secrets."""
    key = (api_key or os.getenv("MILVUS_API_KEY") or os.getenv("MILVUS_TOKEN") or "").strip()
    if not key:
        return None
    return MilvusGateway(api_key=key, api_url=api_url, auth_prefix=auth_prefix)
