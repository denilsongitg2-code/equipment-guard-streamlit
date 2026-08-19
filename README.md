# Equipment Guard — Aditivos + Milvus

Aplicativo Streamlit para importar aditivos de locação de equipamentos, consultar os chamados no Milvus e sinalizar indícios de duplicidade antes do envio à locadora.

## Regras principais

- Importa a planilha real mesmo quando existe uma linha de texto antes do cabeçalho (ex.: `Segue o aditivo 518:`).
- Um aditivo pode ter várias linhas; o número do aditivo não é único por item.
- `Colaborador = Cargo` é tratado como vaga/posição ainda não contratada. A identidade passa a ser `Cargo + Centro de Custo`.
- O mesmo número de chamado em pessoas diferentes não é bloqueado automaticamente.
- `Chamado + mesma pessoa/posição + mesmo tipo` repetido é bloqueado.
- Antes de aprovar outro equipamento, verifica histórico aprovado/enviado para a mesma pessoa/posição.
- Consulta o chamado exato na coleção fonte do Milvus e guarda status/assunto/descrição.
- Sincroniza chamados abertos para uma coleção vetorial de análise e procura chamados de teor semelhante.
- Alto risco: `BLOQUEADO`; risco intermediário: `REVISAR`; sem Milvus: `PENDENTE_MILVUS`.
- Aditivos só podem ser liberados para envio quando todos os itens estiverem aprovados.
- Fluxo de envio considera quarta e sexta-feira.

## Estrutura

- `app.py`: telas Streamlit.
- `database.py`: banco SQLAlchemy (SQLite local e PostgreSQL em produção).
- `services/excel_service.py`: leitura e normalização do Excel.
- `services/milvus_service.py`: consulta da coleção fonte + pesquisa vetorial.
- `services/analysis_service.py`: regras de risco/duplicidade.
- `services/import_service.py`: processo de importação.
- `services/schedule_service.py`: próxima quarta/sexta.

## Rodar local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Sem `DATABASE_URL`, o banco local será `data/equipment_guard.db`.

## GitHub + Streamlit Community Cloud

1. Suba esta pasta para um repositório GitHub.
2. No Streamlit Community Cloud, crie o app apontando para `app.py`.
3. Em **Settings > Secrets**, copie as chaves de `.streamlit/secrets.toml.example` e preencha os dados reais.
4. Para produção, configure `DATABASE_URL` com PostgreSQL persistente. O disco local do Streamlit Cloud não deve ser tratado como armazenamento definitivo.
5. Ajuste os nomes dos campos `MILVUS_*_FIELD` ao schema real da coleção de chamados.

## Como a análise Milvus funciona

A coleção fonte (`MILVUS_SOURCE_COLLECTION`) é consultada pelo número do chamado usando filtro escalar. Os chamados abertos são copiados para uma coleção de análise (`MILVUS_ANALYSIS_COLLECTION`) com vetores gerados pelo próprio app. Isso evita depender do modelo de embedding usado originalmente na coleção fonte e mantém a comparação semântica consistente.

O risco combina semelhança do texto do chamado com semelhança de colaborador, cargo e centro de custo. Os limites podem ser ajustados por secrets.

## Status do aditivo

- `PENDENTE_CONFERENCIA`
- `EM_CONFERENCIA`
- `LIBERADO_ENVIO`
- `ENVIADO`

## Status do item

- `APROVADO`
- `REVISAR`
- `BLOQUEADO`
- `PENDENTE_MILVUS`
