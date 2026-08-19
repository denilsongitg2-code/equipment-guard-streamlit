from __future__ import annotations

import hmac
import json
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Configuração: prioriza Streamlit Secrets e usa variáveis de ambiente como fallback.
import os

def config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value).strip()
    except Exception:
        pass
    return str(os.getenv(name, default) or default).strip()

import database as db
from services.excel_service import read_aditivo
from services.import_service import import_aditivo
from services.milvus_service import get_milvus
from services.schedule_service import next_send_date

st.set_page_config(page_title="Equipment Guard", page_icon="💻", layout="wide")


def require_login() -> None:
    expected = config_value("APP_PASSWORD")
    if not expected:
        st.error("APP_PASSWORD não configurado nos Secrets. Por segurança, o aplicativo foi bloqueado.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("🔐 Equipment Guard")
    st.caption("Acesso restrito — controle de aditivos e prevenção de locação duplicada")
    with st.form("login_form"):
        password = st.text_input("Senha de acesso", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Senha inválida.")
    st.stop()


require_login()
db.init_db()

STATUS_LABELS = {
    "PENDENTE_CONFERENCIA": "Pendente de conferência",
    "EM_CONFERENCIA": "Em conferência",
    "LIBERADO_ENVIO": "Liberado para envio",
    "ENVIADO": "Enviado",
    "BLOQUEADO": "Bloqueado",
}


def milvus_gateway():
    # Não usa cache: alterações nos Secrets passam a valer imediatamente após reiniciar o app.
    api_key = config_value("MILVUS_API_KEY") or config_value("MILVUS_TOKEN")
    api_url = config_value("MILVUS_API_URL", "https://apiintegracao.milvus.com.br/api/chamado/listagem")
    auth_prefix = config_value("MILVUS_AUTH_PREFIX", "")
    if not api_key:
        return None
    return get_milvus(api_key=api_key, api_url=api_url, auth_prefix=auth_prefix)


def status_badge(value: str) -> str:
    return STATUS_LABELS.get(value, value or "-")


def dashboard():
    st.title("Dashboard de conferência de aditivos")
    rows = pd.DataFrame(db.dashboard_rows())
    today = date.today()
    send_date = next_send_date(today)
    st.caption(f"Envios programados às quartas e sextas. Próxima data de envio: **{send_date.strftime('%d/%m/%Y')}**.")

    if rows.empty:
        st.info("Ainda não há aditivos importados.")
        return

    rows["imported_at"] = pd.to_datetime(rows["imported_at"], errors="coerce")
    current = rows[(rows["imported_at"].dt.year == today.year) & (rows["imported_at"].dt.month == today.month)]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equipamentos no mês", len(current))
    c2.metric("Aprovados", int((current["analysis_status"] == "APROVADO").sum()))
    c3.metric("Revisar", int(current["analysis_status"].isin(["REVISAR", "PENDENTE_MILVUS"]).sum()))
    c4.metric("Bloqueados", int((current["analysis_status"] == "BLOQUEADO").sum()))
    c5.metric("Aditivos", current["addition_number"].nunique())

    a, b = st.columns([1.2, 1])
    with a:
        st.subheader("Equipamentos por tipo")
        chart = current.groupby("equipment_type").size().sort_values(ascending=False)
        if not chart.empty:
            st.bar_chart(chart)
    with b:
        st.subheader("Status de análise")
        status = current.groupby("analysis_status").size().sort_values(ascending=False)
        if not status.empty:
            st.bar_chart(status)

    st.subheader("Fila para conferência / envio")
    aditivos = pd.DataFrame(db.list_aditivos())
    if not aditivos.empty:
        aditivos["Status"] = aditivos["workflow_status"].map(status_badge)
        cols = ["addition_number", "Status", "planned_send_date", "imported_at", "source_filename"]
        st.dataframe(aditivos[cols], width="stretch", hide_index=True)

    st.subheader("Alertas de duplicidade")
    alerts = current[current["analysis_status"].isin(["BLOQUEADO", "REVISAR", "PENDENTE_MILVUS"])]
    if alerts.empty:
        st.success("Nenhum alerta no mês selecionado.")
    else:
        st.dataframe(alerts[["addition_number", "ticket_number", "collaborator", "role", "cost_center", "equipment_type", "analysis_status"]], width="stretch", hide_index=True)


def import_page():
    st.title("Importar aditivo Excel")
    st.write("O leitor identifica automaticamente a linha do cabeçalho, inclusive quando existe um texto acima da tabela, como no aditivo 518.")
    file = st.file_uploader("Selecione o aditivo", type=["xlsx", "xlsm"])
    if not file:
        return
    try:
        df, header = read_aditivo(file)
    except Exception as exc:
        st.error(str(exc))
        return
    st.success(f"Cabeçalho localizado na linha {header + 1}. {len(df)} linhas encontradas.")
    st.dataframe(df, width="stretch", hide_index=True)

    milvus = milvus_gateway()
    if milvus:
        st.info("Milvus conectado. Na importação serão consultados os chamados e analisados chamados abertos semelhantes.")
    else:
        st.warning("Milvus não conectado. Os itens serão marcados como PENDENTE_MILVUS e não deverão ser liberados automaticamente.")

    if st.button("Importar e analisar", type="primary"):
        with st.spinner("Importando e analisando..."):
            result = import_aditivo(df, file.name, milvus)
        st.success("Importação concluída.")
        st.json(result)


def aditivo_summary(number: str):
    aditivo = db.get_aditivo(number)
    items = pd.DataFrame(db.list_items(number))
    if not aditivo or items.empty:
        st.warning("Aditivo não encontrado.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aditivo", number)
    c2.metric("Status", status_badge(aditivo["workflow_status"]))
    c3.metric("Itens", len(items))
    c4.metric("Alertas", int(items["analysis_status"].isin(["BLOQUEADO", "REVISAR", "PENDENTE_MILVUS"]).sum()))

    view_cols = [
        "id", "ticket_number", "collaborator", "role", "equipment_type", "model", "cost_center",
        "ticket_status", "analysis_status", "duplicate_ticket", "duplicate_score", "analysis_reason"
    ]
    st.dataframe(items[view_cols], width="stretch", hide_index=True)

    st.subheader("Informações dos chamados")
    for _, item in items.iterrows():
        with st.expander(f"Chamado {item.get('ticket_number') or '-'} — {item.get('collaborator') or item.get('role') or '-'}"):
            st.write(f"**Status do chamado:** {item.get('ticket_status') or 'não informado'}")
            st.write(f"**Assunto:** {item.get('ticket_subject') or 'não informado'}")
            st.write(f"**Descrição:** {item.get('ticket_description') or 'não informada'}")
            st.write(f"**Análise:** {item.get('analysis_reason') or '-'}")
            evidence = item.get("evidence_json")
            if evidence:
                try:
                    ev = json.loads(evidence)
                    if ev:
                        st.caption("Evidências / chamados semelhantes")
                        st.dataframe(pd.DataFrame(ev), width="stretch", hide_index=True)
                except Exception:
                    pass


def search_page():
    st.title("Consultar status por aditivo")
    number = st.text_input("Número do aditivo", placeholder="Ex.: 518")
    if number:
        aditivo_summary(number.strip())


def conference_page():
    st.title("Conferência e envio")
    aditivos = db.list_aditivos()
    if not aditivos:
        st.info("Nenhum aditivo importado.")
        return
    options = [x["addition_number"] for x in aditivos]
    number = st.selectbox("Aditivo", options)
    aditivo_summary(number)
    items = pd.DataFrame(db.list_items(number))
    aditivo = db.get_aditivo(number)

    st.subheader("Ajuste manual após conferência")
    item_id = st.selectbox("Item", items["id"].tolist(), format_func=lambda x: f"Item {x} — chamado {items.loc[items['id']==x, 'ticket_number'].iloc[0]}")
    new_status = st.selectbox("Status do item", ["APROVADO", "REVISAR", "BLOQUEADO", "PENDENTE_MILVUS"])
    note = st.text_input("Observação da conferência")
    if st.button("Salvar status do item"):
        db.update_item_analysis(int(item_id), new_status, note)
        st.success("Item atualizado.")
        st.rerun()

    st.subheader("Fluxo do aditivo")
    current = aditivo["workflow_status"]
    st.write(f"Status atual: **{status_badge(current)}**")
    a, b, c = st.columns(3)
    if a.button("Marcar em conferência"):
        db.set_aditivo_status(number, "EM_CONFERENCIA")
        st.rerun()

    has_block = bool(items["analysis_status"].isin(["BLOQUEADO", "REVISAR", "PENDENTE_MILVUS"]).any())
    if b.button("Liberar para envio", disabled=has_block):
        db.set_aditivo_status(number, "LIBERADO_ENVIO")
        st.rerun()
    if has_block:
        b.caption("Resolva os alertas antes de liberar.")

    if c.button("Marcar como enviado", disabled=current not in ["LIBERADO_ENVIO", "ENVIADO"]):
        db.set_aditivo_status(number, "ENVIADO")
        st.rerun()


def milvus_page():
    st.title("Diagnóstico da API Milvus ITSM")

    api_key = config_value("MILVUS_API_KEY") or config_value("MILVUS_TOKEN")
    api_url = config_value("MILVUS_API_URL", "https://apiintegracao.milvus.com.br/api/chamado/listagem")
    auth_prefix = config_value("MILVUS_AUTH_PREFIX", "")

    c1, c2, c3 = st.columns(3)
    c1.metric("Token encontrado", "SIM" if api_key else "NÃO")
    c2.metric("Tamanho do token", len(api_key) if api_key else 0)
    c3.metric("URL configurada", "SIM" if api_url else "NÃO")
    st.caption(f"Endpoint: {api_url or '-'}")
    st.caption(f"Prefixo de autenticação: {auth_prefix or 'sem prefixo'}")

    if not api_key:
        st.error("MILVUS_API_KEY não foi encontrada nos Secrets do Streamlit.")
        st.code(
            'APP_PASSWORD = "SUA_SENHA"\n'
            'MILVUS_API_KEY = "SEU_TOKEN_REAL"\n'
            'MILVUS_API_URL = "https://apiintegracao.milvus.com.br/api/chamado/listagem"\n'
            'MILVUS_AUTH_PREFIX = ""',
            language="toml",
        )
        return

    try:
        service = milvus_gateway()
    except Exception as exc:
        st.error(f"A configuração foi encontrada, mas o cliente não pôde ser criado: {type(exc).__name__}: {exc}")
        return

    if not service:
        st.error("O token foi encontrado, mas o cliente Milvus não foi criado.")
        return

    st.success("Configuração da API carregada. Agora teste a comunicação.")

    if st.button("Testar conexão com a API", type="primary"):
        try:
            service.healthcheck()
            st.success("API Milvus respondeu corretamente.")
        except Exception as exc:
            st.error(f"Falha ao consultar a API: {type(exc).__name__}: {exc}")

    number = st.text_input("Testar número de chamado", placeholder="Ex.: 70221")
    if number and st.button("Buscar chamado"):
        try:
            result = service.get_ticket(number)
            if result:
                safe = {k: v for k, v in result.items() if k != "raw"}
                st.json(safe)
            else:
                st.warning("Chamado não encontrado.")
        except Exception as exc:
            st.error(f"Erro na consulta: {type(exc).__name__}: {exc}")


page = st.sidebar.radio("Menu", ["Dashboard", "Importar aditivo", "Conferência", "Consultar aditivo", "Milvus"])
st.sidebar.caption("Equipment Guard — API Milvus ITSM")
if st.sidebar.button("Sair"):
    st.session_state["authenticated"] = False
    st.rerun()

if page == "Dashboard":
    dashboard()
elif page == "Importar aditivo":
    import_page()
elif page == "Conferência":
    conference_page()
elif page == "Consultar aditivo":
    search_page()
else:
    milvus_page()
