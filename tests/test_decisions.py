from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services.analysis_service as svc


BASE_ITEM = {
    'addition_number': '999',
    'ticket_number': '100',
    'identity_key': 'pessoa:maria silva',
    'collaborator': 'Maria Silva',
    'role': 'Engenheiro Civil',
    'cost_center': 'Obra-607',
    'equipment_type': 'Notebook',
}


class FakeMilvus:
    def get_ticket(self, number):
        return {
            'ticket_number': str(number), 'status': 'ABERTO', 'collaborator': 'Maria Silva',
            'role': 'Engenheiro Civil', 'cost_center': 'Obra-607', 'subject': 'Notebook',
            'description': 'Solicitação de notebook para colaboradora', 'raw': {}
        }

    def search_similar(self, ticket, limit=10):
        return [{
            'ticket_number': '101', 'status': 'ABERTO', 'collaborator': 'Maria Silva',
            'role': 'Engenheiro Civil', 'cost_center': 'Obra-607', 'subject': 'Notebook',
            'description': 'Solicitação de notebook para colaboradora', 'score': 0.98,
        }]


def test_without_milvus_never_auto_approves(monkeypatch):
    monkeypatch.setattr(svc.db, 'previous_approved_equipment', lambda *a, **k: [])
    monkeypatch.setattr(svc.db, 'same_ticket_identity', lambda *a, **k: [])
    result = svc.analyse_item(dict(BASE_ITEM), None)
    assert result['analysis_status'] == 'PENDENTE_MILVUS'


def test_high_similarity_blocks(monkeypatch):
    monkeypatch.setattr(svc.db, 'previous_approved_equipment', lambda *a, **k: [])
    monkeypatch.setattr(svc.db, 'same_ticket_identity', lambda *a, **k: [])
    monkeypatch.setattr(svc.db, 'upsert_ticket_cache', lambda *a, **k: None)
    result = svc.analyse_item(dict(BASE_ITEM), FakeMilvus())
    assert result['analysis_status'] == 'BLOQUEADO'
    assert result['duplicate_ticket'] == '101'
