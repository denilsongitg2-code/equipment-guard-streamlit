from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.milvus_service import MilvusGateway


def make_gateway(monkeypatch):
    monkeypatch.setenv("MILVUS_API_KEY", "token-teste")
    monkeypatch.setenv("MILVUS_API_URL", "https://api.example.test/api/chamado/listagem")
    return MilvusGateway()


def test_exact_hiring_id_is_critical(monkeypatch):
    gateway = make_gateway(monkeypatch)
    gateway._open_cache = [{
        "ticket_number": "900",
        "status": "A fazer",
        "subject": "Solicitação de equipamento | CONT-2026-000157",
        "description": "ID contratação: CONT-2026-000157\nEquipamentos: Notebook",
        "collaborator": "",
        "role": "Engenheiro Civil",
        "cost_center": "Obra 607",
        "sector": "Obra 607",
    }]
    integration = {"hiring_id": "CONT-2026-000157", "collaborator": None, "role": "Engenheiro Civil", "cost_center": "607"}
    request = {"hiring_id": "CONT-2026-000157", "items": [{"equipment_type": "Notebook"}]}
    row = gateway.search_request_context(integration, request, limit=1)[0]
    assert row["risk"] == "CRITICO"
    assert row["score"] == 1.0


def test_generic_equipment_subject_is_low_without_identity(monkeypatch):
    gateway = make_gateway(monkeypatch)
    gateway._open_cache = [{
        "ticket_number": "901",
        "status": "Pausado",
        "subject": "Solicitação de Equipamentos",
        "description": "Solicito notebook para outro colaborador",
        "collaborator": "Outra Pessoa",
        "role": "Aprendiz Administrativo",
        "cost_center": "01.01.0006",
        "sector": "01.01.0006",
    }]
    integration = {"hiring_id": "CONT-2026-000157", "collaborator": "Denilson Teste", "role": "Coordenador de TI", "cost_center": "712"}
    request = {"hiring_id": "CONT-2026-000157", "items": [{"equipment_type": "Notebook"}]}
    row = gateway.search_request_context(integration, request, limit=1)[0]
    assert row["risk"] == "BAIXO"


def test_replacement_is_flagged_for_same_position(monkeypatch):
    gateway = make_gateway(monkeypatch)
    gateway._open_cache = [{
        "ticket_number": "902",
        "status": "Pausado",
        "subject": "Computador com Defeito",
        "description": "Notebook com travamentos. Sugiro trocar o notebook.",
        "collaborator": "Pessoa X",
        "role": "Engenheiro Civil",
        "cost_center": "01.02.0607",
        "sector": "01.02.0607",
    }]
    integration = {"hiring_id": "CONT-2026-000200", "collaborator": None, "role": "Engenheiro Civil", "cost_center": "Obra 607"}
    request = {"hiring_id": "CONT-2026-000200", "items": [{"equipment_type": "Notebook"}]}
    row = gateway.search_request_context(integration, request, limit=1)[0]
    assert row["possible_replacement"] is True
    assert row["replacement_reason"] in {"troca", "equipamento com defeito", "travamento/lentidão"}
