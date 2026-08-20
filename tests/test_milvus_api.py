from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.milvus_service import MilvusGateway


def make_gateway(monkeypatch):
    monkeypatch.setenv("MILVUS_API_KEY", "token-teste")
    monkeypatch.setenv("MILVUS_API_URL", "https://api.example.test/api/chamado/listagem")
    return MilvusGateway()


def test_get_ticket_parses_milvus_itsm_fields(monkeypatch):
    gateway = make_gateway(monkeypatch)
    payload = {
        "meta": {"paginate": {"last_page": 1}},
        "lista": [{
            "codigo": 70221,
            "status": "A fazer",
            "assunto": "Solicitação de notebook",
            "descricao": "Notebook para Maria Silva\nENGENHEIRO CIVIL / 01.02.0607-PATRIA DATACENTER",
            "contato": "Maria Silva",
            "setor": "01.02.0607-PATRIA DATACENTER",
        }],
    }
    monkeypatch.setattr(gateway, "_fetch_page", lambda *a, **k: payload)
    ticket = gateway.get_ticket("70221")
    assert ticket is not None
    assert ticket["ticket_number"] == "70221"
    assert ticket["status"] == "A fazer"
    assert ticket["collaborator"] == "Maria Silva"
    assert ticket["role"] == "ENGENHEIRO CIVIL"
    assert ticket["cost_center"] == "01.02.0607"


def test_closed_tickets_are_not_considered_open(monkeypatch):
    gateway = make_gateway(monkeypatch)
    payload = {
        "meta": {"paginate": {"last_page": 1}},
        "lista": [
            {"codigo": 1, "status": "Finalizado", "assunto": "Notebook"},
            {"codigo": 2, "status": "Pausado", "assunto": "Notebook"},
            {"codigo": 3, "status": "A fazer", "assunto": "Notebook"},
        ],
    }
    monkeypatch.setattr(gateway, "_fetch_page", lambda *a, **k: payload)
    rows = gateway.get_open_tickets()
    assert {x["ticket_number"] for x in rows} == {"2", "3"}


def test_semantic_search_prefers_same_equipment_request(monkeypatch):
    gateway = make_gateway(monkeypatch)
    gateway._open_cache = [
        {
            "ticket_number": "101", "status": "A fazer", "subject": "Notebook para novo colaborador",
            "description": "Solicitação de notebook Dell para Maria Silva", "collaborator": "Maria Silva",
            "role": "Engenheiro Civil", "cost_center": "01.02.0607", "sector": "01.02.0607",
        },
        {
            "ticket_number": "102", "status": "Pausado", "subject": "Acesso ao OneDrive",
            "description": "Usuário sem sincronização no OneDrive", "collaborator": "João",
            "role": "Analista", "cost_center": "01.01.0006", "sector": "01.01.0006",
        },
    ]
    current = {
        "ticket_number": "100", "status": "A fazer", "subject": "Locação de notebook",
        "description": "Solicito notebook para a colaboradora Maria Silva, Engenheiro Civil",
        "collaborator": "Maria Silva", "role": "Engenheiro Civil", "cost_center": "01.02.0607",
    }
    result = gateway.search_similar(current, limit=2)
    assert result[0]["ticket_number"] == "101"
    assert result[0]["score"] > result[1]["score"]
