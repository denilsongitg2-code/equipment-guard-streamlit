from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.analysis_service import candidate_score


def test_candidate_score_rewards_context():
    item = {'collaborator':'Maria Silva','role':'Engenheiro Civil','cost_center':'Obra-607'}
    candidate = {'score':0.9,'collaborator':'Maria Silva','role':'Engenheiro Civil','cost_center':'Obra-607'}
    assert candidate_score(item, candidate) > 0.85
