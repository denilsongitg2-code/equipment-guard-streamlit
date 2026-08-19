from io import BytesIO
from pathlib import Path
import sys

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.excel_service import identity_for, read_aditivo


def sample_workbook() -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.append(["Segue o aditivo 999:"])
    ws.append(["Aditivo", "Chamado", "Colaborador", "Cargo", "Tipo", "Modelo", "Processador", "Memoria", "HD", "Tela", "Office", "Windows", "PLACA DE VIDEO", "Local de entrega", "Email Contato", "Centro de Custos para Faturamento", "CNPJ"])
    ws.append([999, 123, "Coordenador Planejamento", "Coordenador Planejamento", "Notebook", "Modelo X", "i7", "16GB", "512GB", "-", "Sem Office", "Windows", "-", "Local", "ti@empresa.com", "Obra-607", "00.000.000/0001-00"])
    bio = BytesIO(); wb.save(bio); bio.seek(0)
    return bio


def test_reads_header_after_title():
    df, header = read_aditivo(sample_workbook())
    assert header == 1
    assert len(df) == 1
    assert int(df.iloc[0]["addition_number"]) == 999


def test_reads_real_file_when_available():
    p = Path('/mnt/data/adtivo 518.xlsx')
    if not p.exists():
        return
    df, header = read_aditivo(p)
    assert header == 1
    assert len(df) == 5
    assert set(df['addition_number'].astype(int)) == {518}
    assert list(df['ticket_number'].astype(int)).count(70221) == 2


def test_position_identity():
    key, is_position = identity_for('Coordenador Planejamento', 'Coordenador Planejamento', 'Obra-607')
    assert is_position is True
    assert key.startswith('cargo:coordenador planejamento')
