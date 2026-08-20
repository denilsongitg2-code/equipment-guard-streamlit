from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.rh_service import build_milvus_subject, build_milvus_description


def test_subject_uses_standard_nomenclature_and_hiring_id():
    assert build_milvus_subject('CONT-2026-000001') == 'Solicitação de equipamento | CONT-2026-000001'


def test_description_contains_hiring_context():
    integration = {
        'hiring_id': 'CONT-2026-000001', 'collaborator': None, 'role': 'Engenheiro Civil',
        'manager': 'Gestor Teste', 'cost_center': '0607 - PÁTRIA DATACENTER', 'planned_start_date': None,
    }
    req = {'items': [{'equipment_type':'Notebook','quantity':1}], 'delivery_location':'Obra 607', 'software_notes':'Office'}
    text = build_milvus_description(integration, req)
    assert 'A contratar' in text
    assert 'Notebook' in text
    assert 'CONT-2026-000001' in text
