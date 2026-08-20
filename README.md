# Equipment Guard — Portal RH + TI

Aplicativo Streamlit para controlar solicitações de equipamentos desde a contratação, reduzir duplicidades e acompanhar aditivos e SLA.

## Fluxo principal

1. RH cadastra a contratação diretamente no **Mapa de Integração**.
2. O sistema gera um **ID de contratação** (`CONT-AAAA-000001`).
3. RH abre uma **Solicitação de equipamento** vinculada ao ID.
4. O sistema bloqueia equipamento duplicado para a mesma contratação.
5. TI acompanha a fila, consulta chamados semelhantes no Milvus ITSM e atualiza o status.
6. Quando o aditivo é enviado, inicia o SLA de **15 dias úteis** (segunda a sexta; feriados serão adicionados em fase posterior).
7. RH consulta o andamento sem precisar solicitar atualização por e-mail/chat.

## Campos do Mapa de Integração

O cadastro foi estruturado a partir do modelo 2026: Nome, Cargo, Gestor, Centro de Custo, Telefone, E-mail, Previsão de Início, Confirmação de Início, Data de Integração, Presença, Kit Integração, Cadastro SIE, Trilha SIE, Cadastro Feedz, Integração Feedz, Situação Wellz, Situação TI e Situação E-mail.

O **nome pode ficar vazio**. Cargo e Centro de Custo são obrigatórios.

## Perfis

- **RH**: Mapa de integração, Solicitar equipamento, Consultar status.
- **TI**: Dashboard, Solicitações RH, importação/conferência de aditivos legados e diagnóstico Milvus.

Por compatibilidade, `APP_PASSWORD` funciona para os dois perfis. Opcionalmente configure `RH_PASSWORD` e `TI_PASSWORD` nos Secrets.

## Secrets do Streamlit

```toml
APP_PASSWORD = "senha-geral"
# RH_PASSWORD = "senha-rh"
# TI_PASSWORD = "senha-ti"
MILVUS_API_KEY = "TOKEN"
MILVUS_API_URL = "https://apiintegracao.milvus.com.br/api/chamado/listagem"
MILVUS_AUTH_PREFIX = ""
```

## Banco

Sem `DATABASE_URL`, o sistema usa SQLite local. Para produção, usar PostgreSQL, pois o armazenamento local do Streamlit Community Cloud não deve ser tratado como histórico permanente.

## Milvus

A versão atual usa a API de **consulta** do Milvus ITSM. A tela TI consegue buscar chamados abertos semanticamente semelhantes ao texto padronizado da solicitação.

A criação/atualização/finalização automática do chamado Milvus será habilitada somente após validar os endpoints de escrita disponíveis na conta.

## Testes

```bash
pytest -q
```
