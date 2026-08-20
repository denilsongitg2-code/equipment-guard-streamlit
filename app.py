from __future__ import annotations

import hmac
import json
import os
import re
from datetime import date, datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value).strip()
    except Exception:
        pass
    return str(os.getenv(name, default) or default).strip()


# Segredos que os módulos não-Streamlit leem via ambiente.
for _key in (
    "DATABASE_URL", "MILVUS_TIMEOUT", "MILVUS_PAGE_SIZE", "MILVUS_MAX_PAGES",
    "MILVUS_LOOKBACK_DAYS", "MILVUS_CLOSED_STATUSES", "DUPLICATE_BLOCK_THRESHOLD",
    "DUPLICATE_REVIEW_THRESHOLD",
):
    _value = config_value(_key)
    if _value:
        os.environ[_key] = _value

import database as db
from services.excel_service import read_aditivo
from services.import_service import import_aditivo
from services.milvus_service import get_milvus
from services.rh_service import (
    EQUIPMENT_TYPES,
    REQUEST_STATUSES,
    STATUS_LABELS as RH_STATUS_LABELS,
    build_milvus_description,
    build_milvus_subject,
)
from services.schedule_service import add_business_days, business_days_remaining, next_send_date

st.set_page_config(page_title="Equipment Guard", page_icon="💻", layout="wide")

ADITIVO_STATUS_LABELS = {
    "PENDENTE_CONFERENCIA": "Pendente de conferência",
    "EM_CONFERENCIA": "Em conferência",
    "LIBERADO_ENVIO": "Liberado para envio",
    "ENVIADO": "Enviado",
    "BLOQUEADO": "Bloqueado",
}
MAP_STATUS_OPTIONS = ["PENDENTE", "OK", "CRIAR", "N/A"]


def require_login() -> None:
    if st.session_state.get("authenticated") and st.session_state.get("profile"):
        return

    st.title("🔐 Equipment Guard")
    st.caption("Portal RH + Portal TI — solicitações de equipamentos e prevenção de duplicidade")
    with st.form("login_form"):
        profile = st.selectbox("Perfil", ["RH", "TI"])
        password = st.text_input("Senha de acesso", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        expected = config_value(f"{profile}_PASSWORD") or config_value("APP_PASSWORD")
        if not expected:
            st.error(f"Senha do perfil {profile} não configurada. Configure {profile}_PASSWORD ou APP_PASSWORD nos Secrets.")
        elif hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.session_state["profile"] = profile
            st.rerun()
        else:
            st.error("Senha inválida.")
    st.stop()


require_login()
db.init_db()


def milvus_gateway():
    api_key = config_value("MILVUS_API_KEY") or config_value("MILVUS_TOKEN")
    api_url = config_value("MILVUS_API_URL", "https://apiintegracao.milvus.com.br/api/chamado/listagem")
    auth_prefix = config_value("MILVUS_AUTH_PREFIX", "")
    if not api_key:
        return None
    return get_milvus(api_key=api_key, api_url=api_url, auth_prefix=auth_prefix)


def aditivo_status_label(value: str) -> str:
    return ADITIVO_STATUS_LABELS.get(value, value or "-")


def rh_status_label(value: str) -> str:
    return RH_STATUS_LABELS.get(value, value or "-")


def fmt_date(value) -> str:
    if value is None or value == "":
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    try:
        return pd.to_datetime(value).strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def sla_label(due) -> str:
    if not due:
        return "Ainda não iniciado"
    if isinstance(due, datetime):
        due = due.date()
    remaining = business_days_remaining(date.today(), due)
    if remaining < 0:
        return f"🔴 Vencido há {abs(remaining)} dia(s) útil(eis)"
    if remaining <= 3:
        return f"🟡 Faltam {remaining} dia(s) útil(eis)"
    return f"🟢 Dentro do SLA — {remaining} dia(s) útil(eis)"


# =========================== PORTAL RH ===========================

def rh_map_page():
    st.title("Mapa de Integração")
    st.caption("Cadastro direto no banco. O Excel deixa de ser a fonte principal e passa a ser apenas referência histórica.")

    with st.form("integration_map_form", clear_on_submit=True):
        st.subheader("Dados da contratação")
        a, b, c = st.columns(3)
        collaborator = a.text_input("Nome do colaborador", help="Pode ficar vazio quando a pessoa ainda não foi contratada.")
        role = b.text_input("Cargo *")
        manager = c.text_input("Gestor")

        a, b, c = st.columns(3)
        cost_center = a.text_input("Centro de custo / Obra *")
        phone = b.text_input("Telefone")
        email = c.text_input("E-mail")

        a, b, c = st.columns(3)
        planned_start = a.date_input("Previsão de início", value=date.today())
        has_confirmed = b.checkbox("Início confirmado")
        confirmed_start = b.date_input("Confirmação de início", value=planned_start, disabled=not has_confirmed)
        has_integration = c.checkbox("Integração realizada")
        integration_date = c.date_input("Data da integração", value=planned_start, disabled=not has_integration)

        st.subheader("Acompanhamento do mapa")
        c1, c2, c3 = st.columns(3)
        presence = c1.selectbox("Presença", MAP_STATUS_OPTIONS)
        kit = c2.selectbox("Kit integração", MAP_STATUS_OPTIONS)
        sie_reg = c3.selectbox("Cadastro SIE", MAP_STATUS_OPTIONS)
        c1, c2, c3 = st.columns(3)
        sie_trail = c1.selectbox("Trilha SIE", MAP_STATUS_OPTIONS)
        feedz_reg = c2.selectbox("Cadastro FEEDZ", MAP_STATUS_OPTIONS)
        feedz_int = c3.selectbox("Integração FEEDZ", MAP_STATUS_OPTIONS)
        c1, c2, c3 = st.columns(3)
        wellz = c1.selectbox("Situação WELLZ", MAP_STATUS_OPTIONS)
        ti_status = c2.selectbox("Situação TI", MAP_STATUS_OPTIONS)
        email_status = c3.selectbox("Situação E-mail", MAP_STATUS_OPTIONS)
        notes = st.text_area("Observações")
        submitted = st.form_submit_button("Cadastrar no Mapa de Integração", type="primary")

    if submitted:
        if not role.strip() or not cost_center.strip():
            st.error("Cargo e Centro de custo / Obra são obrigatórios.")
        else:
            payload = {
                "collaborator": collaborator.strip() or None,
                "role": role.strip(),
                "manager": manager.strip() or None,
                "cost_center": cost_center.strip(),
                "phone": phone.strip() or None,
                "email": email.strip() or None,
                "planned_start_date": planned_start,
                "confirmed_start_date": confirmed_start if has_confirmed else None,
                "integration_date": integration_date if has_integration else None,
                "presence_status": presence,
                "integration_kit_status": kit,
                "sie_registration_status": sie_reg,
                "sie_trail_status": sie_trail,
                "feedz_registration_status": feedz_reg,
                "feedz_integration_status": feedz_int,
                "wellz_status": wellz,
                "ti_status": ti_status,
                "email_status": email_status,
                "notes": notes.strip() or None,
            }
            duplicates = db.find_integration_duplicates(payload)
            if duplicates:
                st.error("Cadastro não realizado: foi encontrado um possível registro duplicado no Mapa de Integração.")
                view = pd.DataFrame(duplicates)
                st.dataframe(view[["hiring_id", "collaborator", "role", "cost_center", "planned_start_date", "email"]], hide_index=True, width="stretch")
            else:
                hiring_id = db.create_integration_record(payload)
                st.success(f"Cadastro criado. ID de contratação: **{hiring_id}**")
                st.info("Use este ID em todas as solicitações de equipamento desta contratação.")

    st.divider()
    st.subheader("Registros recentes")
    rows = pd.DataFrame(db.list_integration_records(limit=100))
    if rows.empty:
        st.info("Nenhum registro cadastrado ainda.")
    else:
        cols = ["hiring_id", "collaborator", "role", "manager", "cost_center", "planned_start_date", "ti_status", "email_status"]
        st.dataframe(rows[cols], hide_index=True, width="stretch")


def _integration_label(row: dict) -> str:
    person = row.get("collaborator") or "A contratar"
    return f"{row['hiring_id']} — {person} — {row.get('role') or '-'} — {row.get('cost_center') or '-'}"


def rh_request_page():
    st.title("Solicitação de equipamento")
    st.caption('Nomenclatura padrão do chamado: **"Solicitação de equipamento"**. O ID de contratação acompanha todo o processo.')
    integrations = db.list_integration_records(limit=1000, active_only=True)
    if not integrations:
        st.warning("Cadastre primeiro a contratação no Mapa de Integração.")
        return

    lookup = {x["hiring_id"]: x for x in integrations}
    hiring_id = st.selectbox("ID de contratação", list(lookup.keys()), format_func=lambda x: _integration_label(lookup[x]))
    integration = lookup[hiring_id]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ID contratação", hiring_id)
    c2.metric("Colaborador", integration.get("collaborator") or "A contratar")
    c3.metric("Cargo", integration.get("role") or "-")
    c4.metric("Previsão início", fmt_date(integration.get("planned_start_date")))

    with st.form("equipment_request_form", clear_on_submit=True):
        st.subheader("Equipamentos")
        cols = st.columns(3)
        selections = {}
        for idx, eq in enumerate(EQUIPMENT_TYPES):
            selections[eq] = cols[idx % 3].checkbox(eq)
        other = st.text_input("Outro periférico/equipamento")
        delivery = st.text_input("Local de entrega", value=integration.get("cost_center") or "")
        software = st.text_area("Softwares, acessos ou especificações necessárias")
        requested_by = st.text_input("Solicitante RH")
        notes = st.text_area("Observações internas")
        submitted = st.form_submit_button("Criar solicitação", type="primary")

    if submitted:
        items = [{"equipment_type": eq, "quantity": 1} for eq, checked in selections.items() if checked]
        if other.strip():
            items.append({"equipment_type": other.strip(), "quantity": 1, "details": "Outro"})
        try:
            code = db.create_equipment_request(
                hiring_id=hiring_id,
                equipment_items=items,
                requested_by=requested_by.strip() or None,
                delivery_location=delivery.strip() or None,
                software_notes=software.strip() or None,
                notes=notes.strip() or None,
            )
            req = db.get_equipment_request(code)
            st.success(f"Solicitação criada: **{code}**")
            st.code(build_milvus_subject(hiring_id), language=None)
            st.text_area("Descrição padronizada para o chamado Milvus", value=build_milvus_description(integration, req), height=260)
            st.caption("Nesta fase o chamado é registrado no Equipment Guard. A criação automática no Milvus será ligada após validarmos o endpoint de escrita da API.")
        except ValueError as exc:
            st.error(str(exc))


def rh_status_page():
    st.title("Consultar status")
    st.caption("Pesquise por ID de contratação, nome, cargo, centro de custo ou código da solicitação.")
    term = st.text_input("Buscar", placeholder="Ex.: CONT-2026-000157, Engenheiro Civil, Obra 607...").strip().lower()
    integrations = db.list_integration_records(limit=2000)
    requests = db.list_equipment_requests(limit=2000)

    if term:
        ids = set()
        for row in integrations:
            text = " | ".join(str(row.get(k) or "") for k in ("hiring_id", "collaborator", "role", "manager", "cost_center", "email")).lower()
            if term in text:
                ids.add(row["hiring_id"])
        for req in requests:
            text = " | ".join(str(req.get(k) or "") for k in ("request_code", "hiring_id", "collaborator", "role", "cost_center", "milvus_ticket", "addition_number")).lower()
            if term in text:
                ids.add(req["hiring_id"])
        integrations = [x for x in integrations if x["hiring_id"] in ids]

    if not integrations:
        st.info("Nenhum registro encontrado.")
        return

    for record in integrations[:50]:
        label = _integration_label(record)
        with st.expander(label):
            a, b, c, d = st.columns(4)
            a.write(f"**Gestor:** {record.get('manager') or '-'}")
            b.write(f"**Previsão início:** {fmt_date(record.get('planned_start_date'))}")
            c.write(f"**Situação TI:** {record.get('ti_status') or '-'}")
            d.write(f"**Situação E-mail:** {record.get('email_status') or '-'}")
            reqs = [x for x in requests if x["hiring_id"] == record["hiring_id"]]
            if not reqs:
                st.warning("Ainda não existe solicitação de equipamento para esta contratação.")
                continue
            view = []
            for req in reqs:
                full = db.get_equipment_request(req["request_code"])
                eqs = ", ".join(x["equipment_type"] for x in (full.get("items") or [])) if full else "-"
                view.append({
                    "Solicitação": req["request_code"],
                    "Equipamentos": eqs,
                    "Status": rh_status_label(req["status"]),
                    "Chamado Milvus": req.get("milvus_ticket") or "-",
                    "Aditivo": req.get("addition_number") or "-",
                    "Envio aditivo": fmt_date(req.get("addition_sent_at")),
                    "Prazo SLA": fmt_date(req.get("sla_due_date")),
                    "SLA": sla_label(req.get("sla_due_date")),
                })
            st.dataframe(pd.DataFrame(view), hide_index=True, width="stretch")


# =========================== PORTAL TI ===========================

def ti_requests_page():
    st.title("Solicitações RH → TI")
    rows = db.list_equipment_requests(limit=2000)
    if not rows:
        st.info("Nenhuma solicitação criada pelo RH.")
        return

    df = pd.DataFrame(rows)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Solicitações", len(df))
    c2.metric("Aguardando TI", int(df["status"].isin(["SOLICITACAO_CRIADA", "EM_ANALISE_TI"]).sum()))
    c3.metric("Aguardando aditivo", int((df["status"] == "AGUARDANDO_ADITIVO").sum()))
    c4.metric("Em SLA", int(df["sla_due_date"].notna().sum()))

    display = df.copy()
    display["Status"] = display["status"].map(rh_status_label)
    display["SLA"] = display["sla_due_date"].map(sla_label)
    st.dataframe(display[["request_code", "hiring_id", "collaborator", "role", "cost_center", "Status", "milvus_ticket", "addition_number", "SLA"]], hide_index=True, width="stretch")

    options = df["request_code"].tolist()
    code = st.selectbox("Abrir solicitação", options)
    req = db.get_equipment_request(code)
    integration = db.get_integration_record(req["hiring_id"])
    st.subheader(f"{code} — {integration.get('collaborator') or 'A contratar'}")
    st.write(f"**ID contratação:** {req['hiring_id']}  |  **Cargo:** {integration.get('role')}  |  **CC:** {integration.get('cost_center')}")
    st.write("**Equipamentos:** " + ", ".join(x["equipment_type"] for x in req.get("items", [])))
    if req.get("software_notes"):
        st.write(f"**Softwares/especificações:** {req['software_notes']}")

    milvus = milvus_gateway()
    if milvus and st.button("Verificar duplicidade / trocas no Milvus"):
        try:
            found = milvus.search_request_context(integration, req, limit=10)
            if found:
                view = pd.DataFrame(found)
                view["similaridade"] = view["score"].map(lambda x: f"{x:.0%}")
                view["Risco"] = view["risk"].map({
                    "CRITICO": "🔴 CRÍTICO",
                    "ALTO": "🟠 ALTO",
                    "REVISAR": "🟡 REVISAR",
                    "BAIXO": "🟢 BAIXO",
                }).fillna(view["risk"])
                view["Motivo"] = view["reason"]
                st.dataframe(
                    view[["ticket_number", "status", "subject", "collaborator", "role", "cost_center", "similaridade", "Risco", "Motivo"]],
                    hide_index=True,
                    width="stretch",
                )
                strong = view[view["risk"].isin(["CRITICO", "ALTO"])]
                review = view[view["risk"] == "REVISAR"]
                if not strong.empty:
                    st.warning("Há chamados com forte evidência de duplicidade. A TI deve conferir antes de aprovar.")
                elif not review.empty:
                    st.info("Há chamados para revisão, mas nenhuma evidência forte de duplicidade foi encontrada.")
                else:
                    st.success("Nenhuma evidência forte de duplicidade nos chamados abertos retornados.")
            else:
                st.success("Nenhum chamado aberto semelhante localizado.")

            replacements = milvus.find_replacement_tickets(integration, limit=10)
            if replacements:
                st.subheader("⚠️ Possíveis trocas / substituições em andamento")
                repl = pd.DataFrame(replacements)
                repl["Evidência"] = repl["replacement_reason"]
                st.dataframe(
                    repl[["ticket_number", "status", "subject", "collaborator", "role", "cost_center", "Evidência"]],
                    hide_index=True,
                    width="stretch",
                )
                st.warning("Existe chamado de possível troca ligado à mesma pessoa/posição. Tratar antes de uma nova compra/locação.")
        except Exception as exc:
            st.error(f"Falha na consulta ao Milvus: {exc}")

    st.subheader("Tratativa TI")
    current_idx = REQUEST_STATUSES.index(req["status"]) if req["status"] in REQUEST_STATUSES else 0
    new_status = st.selectbox("Status", REQUEST_STATUSES, index=current_idx, format_func=rh_status_label)
    c1, c2 = st.columns(2)
    milvus_ticket = c1.text_input("Chamado Milvus", value=req.get("milvus_ticket") or "")
    addition_number = c2.text_input("Aditivo", value=req.get("addition_number") or "")
    c1, c2 = st.columns(2)
    sent_date = c1.date_input(
        "Data de envio do aditivo",
        value=req.get("addition_sent_at"),
        help="Preencha somente quando o aditivo tiver sido efetivamente enviado ao fornecedor. É desta data que começa o SLA de 15 dias úteis.",
    )
    delivered_date = c2.date_input(
        "Data de entrega",
        value=req.get("delivered_at"),
        help="Preencha somente quando o equipamento tiver sido entregue ao colaborador.",
    )
    ti_notes = st.text_area("Observação TI", value=req.get("notes") or "")

    if st.button("Salvar tratativa", type="primary"):
        sent_statuses = {"ADITIVO_ENVIADO", "AGUARDANDO_FORNECEDOR", "RECEBIDO_TI", "PRONTO_ENTREGA", "ENTREGUE", "CONCLUIDO"}
        delivered_statuses = {"ENTREGUE", "CONCLUIDO"}

        validation_error = None
        if new_status in sent_statuses and not addition_number.strip():
            validation_error = "Informe o número do aditivo antes de marcar o item como enviado/aguardando fornecedor."
        elif new_status in sent_statuses and not sent_date:
            validation_error = "Informe a data real de envio do aditivo. O SLA de 15 dias úteis começa nessa data."
        elif new_status in delivered_statuses and not delivered_date:
            validation_error = "Informe a data de entrega antes de marcar a solicitação como Entregue/Concluída."
        elif sent_date and delivered_date and delivered_date < sent_date:
            validation_error = "A data de entrega não pode ser anterior à data de envio do aditivo."

        if validation_error:
            st.error(validation_error)
        else:
            changes = {
                "status": new_status,
                "milvus_ticket": milvus_ticket.strip() or None,
                "addition_number": addition_number.strip() or None,
                "notes": ti_notes.strip() or None,
            }
            if new_status in sent_statuses:
                changes["addition_sent_at"] = sent_date
                changes["sla_due_date"] = add_business_days(sent_date, 15)
            if new_status in delivered_statuses:
                changes["delivered_at"] = delivered_date
            db.update_equipment_request(code, **changes)
            st.success("Tratativa salva.")
            st.rerun()

    if req.get("sla_due_date"):
        st.info(f"SLA de entrega: **15 dias úteis** a partir do envio do aditivo. Prazo: **{fmt_date(req['sla_due_date'])}** — {sla_label(req['sla_due_date'])}")


# =========================== ADITIVOS / LEGADO ===========================

def ti_dashboard():
    st.title("Dashboard TI")
    requests = pd.DataFrame(db.list_equipment_requests(limit=2000))
    if not requests.empty:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Solicitações RH", len(requests))
        c2.metric("Novas", int((requests["status"] == "SOLICITACAO_CRIADA").sum()))
        c3.metric("Para aditivo", int((requests["status"] == "AGUARDANDO_ADITIVO").sum()))
        c4.metric("Aguardando fornecedor", int((requests["status"] == "AGUARDANDO_FORNECEDOR").sum()))
        overdue = 0
        for due in requests["sla_due_date"].dropna():
            d = due.date() if isinstance(due, datetime) else due
            overdue += int(d < date.today())
        c5.metric("SLA vencido", overdue)

        st.subheader("Fila RH")
        view = requests.copy()
        view["Status"] = view["status"].map(rh_status_label)
        view["SLA"] = view["sla_due_date"].map(sla_label)
        st.dataframe(view[["request_code", "hiring_id", "collaborator", "role", "cost_center", "Status", "addition_number", "SLA"]], hide_index=True, width="stretch")

    rows = pd.DataFrame(db.dashboard_rows())
    send_date = next_send_date(date.today())
    st.caption(f"Aditivos são enviados às quartas e sextas. Próxima janela: **{send_date.strftime('%d/%m/%Y')}**.")
    if rows.empty:
        return
    rows["imported_at"] = pd.to_datetime(rows["imported_at"], errors="coerce")
    current = rows[(rows["imported_at"].dt.year == date.today().year) & (rows["imported_at"].dt.month == date.today().month)]
    st.subheader("Aditivos importados / contingência")
    a, b, c, d = st.columns(4)
    a.metric("Equipamentos no mês", len(current))
    b.metric("Aprovados", int((current["analysis_status"] == "APROVADO").sum()))
    c.metric("Revisar", int(current["analysis_status"].isin(["REVISAR", "PENDENTE_MILVUS"]).sum()))
    d.metric("Bloqueados", int((current["analysis_status"] == "BLOQUEADO").sum()))


def _texto_valido(valor) -> str:
    if valor is None or pd.isna(valor):
        return ""
    texto = str(valor).strip()
    if texto.lower() in {"", "none", "nan", "nat"}:
        return ""
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return texto


def _aditivo_pelo_nome_arquivo(filename: str) -> str:
    match = re.search(r"(?i)(?:aditivo|adtivo)[\s_-]*(\d{1,8})", str(filename or ""))
    return match.group(1) if match else ""


def import_page():
    st.title("Importar aditivo Excel — contingência")
    st.info("O fluxo principal passa a nascer no Portal RH. Esta tela permanece para importar aditivos legados ou contingência.")
    file = st.file_uploader("Selecione o aditivo", type=["xlsx", "xlsm"])
    if not file:
        return
    try:
        df, header = read_aditivo(file)
    except Exception as exc:
        st.error(str(exc)); return
    existentes = sorted({_texto_valido(v) for v in df.get("addition_number", pd.Series(dtype=object)).tolist() if _texto_valido(v)})
    sugerido = _aditivo_pelo_nome_arquivo(file.name) or (existentes[0] if len(existentes) == 1 else "")
    st.success(f"Cabeçalho localizado na linha {header + 1}. {len(df)} linhas encontradas.")
    numero = st.text_input("Número do aditivo", value=sugerido, placeholder="Ex.: 535").strip()
    df_import = df.copy()
    if numero:
        df_import["addition_number"] = numero
    st.dataframe(df_import, width="stretch", hide_index=True)
    milvus = milvus_gateway()
    if milvus:
        st.info("Milvus conectado.")
    else:
        st.warning("Milvus não conectado; itens ficarão pendentes de conferência.")
    if st.button("Importar e analisar", type="primary", disabled=not bool(numero)):
        with st.spinner("Importando e analisando..."):
            result = import_aditivo(df_import, file.name, milvus)
        st.success("Importação concluída.")
        st.json(result)


def aditivo_summary(number: str):
    aditivo = db.get_aditivo(number)
    items = pd.DataFrame(db.list_items(number))
    if not aditivo or items.empty:
        st.warning("Aditivo não encontrado."); return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aditivo", number)
    c2.metric("Status", aditivo_status_label(aditivo["workflow_status"]))
    c3.metric("Itens", len(items))
    c4.metric("Alertas", int(items["analysis_status"].isin(["BLOQUEADO", "REVISAR", "PENDENTE_MILVUS"]).sum()))
    view_cols = ["id", "ticket_number", "collaborator", "role", "equipment_type", "model", "cost_center", "ticket_status", "analysis_status", "duplicate_ticket", "duplicate_score", "analysis_reason"]
    st.dataframe(items[view_cols], width="stretch", hide_index=True)
    st.subheader("Informações dos chamados")
    for _, item in items.iterrows():
        with st.expander(f"Chamado {item.get('ticket_number') or '-'} — {item.get('collaborator') or item.get('role') or '-'}"):
            st.write(f"**Status:** {item.get('ticket_status') or 'não informado'}")
            st.write(f"**Assunto:** {item.get('ticket_subject') or 'não informado'}")
            st.write(f"**Descrição:** {item.get('ticket_description') or 'não informada'}")
            st.write(f"**Análise:** {item.get('analysis_reason') or '-'}")
            evidence = item.get("evidence_json")
            if evidence:
                try:
                    ev = json.loads(evidence)
                    if ev:
                        st.dataframe(pd.DataFrame(ev), width="stretch", hide_index=True)
                except Exception:
                    pass


def search_aditivo_page():
    st.title("Consultar status por aditivo")
    number = st.text_input("Número do aditivo", placeholder="Ex.: 518")
    if number:
        aditivo_summary(number.strip())


def conference_page():
    st.title("Conferência de aditivo legado")
    aditivos = db.list_aditivos()
    if not aditivos:
        st.info("Nenhum aditivo importado."); return
    number = st.selectbox("Aditivo", [x["addition_number"] for x in aditivos])
    aditivo_summary(number)
    items = pd.DataFrame(db.list_items(number))
    aditivo = db.get_aditivo(number)
    item_id = st.selectbox("Item", items["id"].tolist(), format_func=lambda x: f"Item {x} — chamado {items.loc[items['id']==x, 'ticket_number'].iloc[0]}")
    new_status = st.selectbox("Status do item", ["APROVADO", "REVISAR", "BLOQUEADO", "PENDENTE_MILVUS"])
    note = st.text_input("Observação")
    if st.button("Salvar status do item"):
        db.update_item_analysis(int(item_id), new_status, note); st.rerun()
    current = aditivo["workflow_status"]
    a, b, c = st.columns(3)
    if a.button("Marcar em conferência"):
        db.set_aditivo_status(number, "EM_CONFERENCIA"); st.rerun()
    has_block = bool(items["analysis_status"].isin(["BLOQUEADO", "REVISAR", "PENDENTE_MILVUS"]).any())
    if b.button("Liberar para envio", disabled=has_block):
        db.set_aditivo_status(number, "LIBERADO_ENVIO"); st.rerun()
    if c.button("Marcar como enviado", disabled=current not in ["LIBERADO_ENVIO", "ENVIADO"]):
        db.set_aditivo_status(number, "ENVIADO"); st.rerun()


def milvus_page():
    st.title("Diagnóstico da API Milvus ITSM")
    api_key = config_value("MILVUS_API_KEY") or config_value("MILVUS_TOKEN")
    api_url = config_value("MILVUS_API_URL", "https://apiintegracao.milvus.com.br/api/chamado/listagem")
    auth_prefix = config_value("MILVUS_AUTH_PREFIX", "")
    c1, c2, c3 = st.columns(3)
    c1.metric("Token encontrado", "SIM" if api_key else "NÃO")
    c2.metric("Tamanho do token", len(api_key) if api_key else 0)
    c3.metric("URL configurada", "SIM" if api_url else "NÃO")
    if not api_key:
        st.error("MILVUS_API_KEY não encontrada nos Secrets."); return
    service = milvus_gateway()
    if st.button("Testar conexão com a API", type="primary"):
        try:
            service.healthcheck(); st.success("API Milvus respondeu corretamente.")
        except Exception as exc:
            st.error(f"Falha ao consultar a API: {type(exc).__name__}: {exc}")
    number = st.text_input("Testar número de chamado", placeholder="Ex.: 70221")
    if number and st.button("Buscar chamado"):
        try:
            result = service.get_ticket(number)
            st.json({k: v for k, v in result.items() if k != "raw"} if result else {})
        except Exception as exc:
            st.error(f"Erro na consulta: {exc}")


# =========================== NAVEGAÇÃO ===========================
profile = st.session_state.get("profile", "TI")
st.sidebar.title(f"Portal {profile}")
st.sidebar.caption("Equipment Guard — RH + TI + Milvus ITSM")

if profile == "RH":
    page = st.sidebar.radio("Menu", ["Mapa de integração", "Solicitar equipamento", "Consultar status"])
else:
    page = st.sidebar.radio("Menu", ["Dashboard TI", "Solicitações RH", "Importar aditivo", "Conferência aditivo", "Consultar aditivo", "Milvus"])

if st.sidebar.button("Sair / trocar perfil"):
    st.session_state["authenticated"] = False
    st.session_state["profile"] = None
    st.rerun()

if profile == "RH":
    if page == "Mapa de integração": rh_map_page()
    elif page == "Solicitar equipamento": rh_request_page()
    else: rh_status_page()
else:
    if page == "Dashboard TI": ti_dashboard()
    elif page == "Solicitações RH": ti_requests_page()
    elif page == "Importar aditivo": import_page()
    elif page == "Conferência aditivo": conference_page()
    elif page == "Consultar aditivo": search_aditivo_page()
    else: milvus_page()
