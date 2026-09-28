"""Estacionamento 5 Estrelas — sistema financeiro (Streamlit).

Rodar no computador:  streamlit run app.py
Publicado no Streamlit Community Cloud, com os dados no Supabase (PostgreSQL).
"""
from datetime import date, datetime
from pathlib import Path
import hmac
import json

import altair as alt
import pandas as pd
import streamlit as st

from dados import (CATEGORIAS, DIAS, INICIO, MESES, MODALIDADES, PAGAMENTOS, PLANOS, VEICULOS,
                   Banco, br, brl, descricao_veiculo, placa_fmt, centavos, comp_valida, competencias, converter_backup,
                   dia_semana, hoje, mes, rotulo, rotulo_curto, ultimo_dia)
from relatorio import gerar_excel

PASTA = Path(__file__).parent
LOGO = PASTA / "logo.png"
AZUL, DOURADO, VERDE, BRONZE, ARDOSIA, VERMELHO = "#073449", "#d6aa24", "#397c7b", "#bd783d", "#7186a1", "#a4473b"

st.set_page_config(page_title="Estacionamento 5 Estrelas", page_icon=str(LOGO) if LOGO.exists() else None,
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
[data-testid="stMetricValue"]{font-size:1.45rem}
[data-testid="stMetricLabel"] p{font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
.block-container{padding-top:1.4rem}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ acesso
def segredo(nome, padrao=None):
    try:
        return st.secrets[nome]
    except Exception:
        return padrao


def login():
    senha = segredo("senha")
    if not senha or st.session_state.get("logado"):
        return
    c = st.columns([1, 2, 1])[1]
    with c:
        if LOGO.exists():
            st.image(str(LOGO), width=110)
        st.subheader("Estacionamento 5 Estrelas")
        with st.form("login"):
            s = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", type="primary", use_container_width=True):
                if hmac.compare_digest(s.encode(), str(senha).encode()):
                    st.session_state.logado = True
                    st.rerun()
                st.error("Senha incorreta.")
    st.stop()


login()


@st.cache_resource(show_spinner="Conectando ao banco de dados…")
def banco() -> Banco:
    return Banco(segredo("database_url") or str(PASTA / "local.sqlite3"))


try:
    db = banco()
    T = db.tudo()
except Exception as e:  # sem conexão: mostra orientação em vez de erro técnico
    st.error("Não foi possível conectar ao banco de dados. Verifique a internet e o endereço do banco "
             "(database_url) nas configurações do app. Se o banco do Supabase estiver pausado, reative-o no painel do Supabase.")
    st.caption(f"Detalhe técnico: {type(e).__name__}")
    st.stop()


# -------------------------------------------------------------- utilidades
def aviso(msg):  # mostra a mensagem depois do st.rerun()
    st.session_state.msg = msg


if st.session_state.get("msg"):
    st.toast(st.session_state.pop("msg"))


def acao(fn, msg):
    try:
        fn()
    except ValueError as e:
        st.error(str(e))
        return
    except Exception as e:
        st.error(f"Não foi possível salvar agora. Tente de novo. ({type(e).__name__})")
        return
    aviso(msg)
    st.rerun()


def lista_comps():
    fim = max([hoje()[:7], *competencias(T)])
    a, m = map(int, INICIO.split("-"))
    fa, fm = map(int, fim.split("-"))
    fm += 1
    if fm == 13:
        fa, fm = fa + 1, 1
    out = []
    while (a, m) <= (fa, fm):
        out.append(f"{a}-{m:02d}")
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return out


def escolher_comp(label, key):
    comps = lista_comps()
    atual = max(hoje()[:7], INICIO)
    return st.selectbox(label, comps, index=comps.index(atual) if atual in comps else 0,
                        format_func=rotulo, key=key)


def data_padrao():
    return max(date.fromisoformat(hoje()), date.fromisoformat(INICIO + "-01"))


MIN_DATA = date.fromisoformat(INICIO + "-01")
MAX_DATA = date(2100, 12, 31)


def tabela_selecionavel(df: pd.DataFrame, key: str, altura=None):
    ev = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun",
                      selection_mode="multi-row", key=key, height=altura)
    return list(ev.selection.rows) if ev and ev.selection else []


def excluir_popover(label, n, fn, msg, key):
    if not n:
        st.caption("Marque linhas na tabela para excluir.")
        return
    with st.popover(f"{label} ({n})"):
        st.write(f"Excluir {n} {'item' if n == 1 else 'itens'}? Isso não pode ser desfeito.")
        if st.button("Sim, excluir", type="primary", key=key):
            acao(fn, msg)


# ------------------------------------------------------------------ topo
c1, c2 = st.columns([1, 11], vertical_alignment="center")
with c1:
    if LOGO.exists():
        st.image(str(LOGO), width=64)
with c2:
    st.markdown("<div style='font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;color:#8a6a0c;font-weight:800'>Gestão financeira</div>"
                "<div style='font-size:1.6rem;font-weight:800;line-height:1.15'>Estacionamento 5 Estrelas</div>", unsafe_allow_html=True)

aba_geral, aba_rec, aba_men, aba_desp, aba_fech = st.tabs(["Visão geral", "Receitas", "Mensalistas", "Despesas", "Fechamento e dados"])


# ============================================================ VISÃO GERAL
with aba_geral:
    comps = competencias(T)
    anos = sorted({int(c[:4]) for c in comps} | {int(max(hoje(), INICIO)[:4])})
    f1, f2, f3 = st.columns([1, 1, 2])
    ano = f1.selectbox("Ano", ["Todos", *anos], index=1 + anos.index(int(max(hoje(), INICIO)[:4])), key="g_ano")
    mes_idx = int(max(hoje()[:7], INICIO)[5:])
    mes_sel = f2.selectbox("Mês", ["Todos", *MESES], index=mes_idx, key="g_mes")
    linhas = [mes(T, c) for c in comps
              if (ano == "Todos" or c[:4] == str(ano)) and (mes_sel == "Todos" or int(c[5:]) == MESES.index(mes_sel) + 1)]
    f3.caption("")
    f3.markdown(f"<div style='padding-top:2rem;color:#5d7180'>{(linhas[0]['rotulo'] + (' a ' + linhas[-1]['rotulo'] if len(linhas) > 1 else '')) if linhas else 'Nenhum lançamento neste período'}</div>",
                unsafe_allow_html=True)

    S = lambda k: sum(x[k] for x in linhas)
    rec, desp, res, mensal = S("receita"), S("despesas"), S("resultado"), S("mensal")
    din, pix, car = S("dinheiro"), S("pix"), S("cartao")
    din_t, pix_t, car_t = din + S("m_dinheiro"), pix + S("m_pix"), car + S("m_cartao")
    ativos = [x for x in linhas if x["receita"] > 0]

    k = st.columns(3)
    k[0].metric("Receita no período", brl(rec), help="Tudo o que entrou: avulsos (dinheiro, PIX, cartão) + mensalidades.")
    k[1].metric("Resultado", brl(res), help="Receita menos despesas lançadas.")
    k[2].metric("Despesas", brl(desp))
    k = st.columns(3)
    k[0].metric("Mensalistas", brl(mensal))
    k[1].metric("Em dinheiro", brl(din_t), help="Avulsos e mensalidades pagas em dinheiro.")
    k[2].metric("PIX e cartão", brl(pix_t + car_t), help=f"PIX {brl(pix_t)} · Cartão {brl(car_t)}")

    if not linhas:
        st.info("Ainda não há lançamentos neste período. Comece pela aba Receitas.")
    else:
        reais = lambda c: c / 100
        g1, g2 = st.columns([2, 1])
        with g1:
            nomes_ind = {"receita": "Receita total", "resultado": "Resultado", "despesas": "Despesas",
                         "dinheiro": "Dinheiro (avulsos)", "pix": "PIX (avulsos)", "cartao": "Cartão (avulsos)", "mensal": "Mensalistas"}
            ind = st.selectbox("Evolução financeira", list(nomes_ind), format_func=nomes_ind.get, key="g_ind")
            df = pd.DataFrame({"Mês": [rotulo_curto(x["comp"]) for x in linhas], "ordem": range(len(linhas)),
                               "Valor": [reais(x[ind]) for x in linhas]})
            st.altair_chart(alt.Chart(df).mark_area(line={"color": DOURADO}, color=alt.Gradient(
                gradient="linear", stops=[alt.GradientStop(color="#d6aa2455", offset=0), alt.GradientStop(color="#d6aa2405", offset=1)],
                x1=1, x2=1, y1=0, y2=1), point={"color": DOURADO}).encode(
                x=alt.X("Mês:N", sort=alt.SortField("ordem"), title=None),
                y=alt.Y("Valor:Q", title=None, axis=alt.Axis(format=",.0f")),
                tooltip=["Mês", alt.Tooltip("Valor:Q", format=",.2f")]).properties(height=260), use_container_width=True)
        with g2:
            st.markdown("**Mix de receita**")
            df = pd.DataFrame({"Tipo": ["Avulsos", "Mensalistas"], "Valor": [reais(din + pix + car), reais(mensal)]})
            st.altair_chart(alt.Chart(df).mark_arc(innerRadius=60).encode(
                theta="Valor:Q", color=alt.Color("Tipo:N", scale=alt.Scale(range=[DOURADO, VERDE]), legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Tipo", alt.Tooltip("Valor:Q", format=",.2f")]).properties(height=280), use_container_width=True)

        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Formas de recebimento**")
            df = pd.DataFrame({"Forma": ["Dinheiro", "PIX", "Cartão", "Mensalistas"], "Valor": [reais(din), reais(pix), reais(car), reais(mensal)]})
            st.altair_chart(alt.Chart(df).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("Forma:N", sort=None, title=None), y=alt.Y("Valor:Q", title=None),
                color=alt.Color("Forma:N", scale=alt.Scale(domain=["Dinheiro", "PIX", "Cartão", "Mensalistas"], range=[BRONZE, ARDOSIA, DOURADO, VERDE]), legend=None),
                tooltip=["Forma", alt.Tooltip("Valor:Q", format=",.2f")]).properties(height=250), use_container_width=True)
        with g2:
            st.markdown("**Receita por dia da semana**")
            por_dia = {d: 0 for d in DIAS}
            for x in linhas:
                for e in x["ent"]:
                    por_dia[dia_semana(e["data"])] += e["valor"]
                for p in x["pays"]:
                    if p.get("data"):
                        por_dia[dia_semana(p["data"])] += p["valor"]
            df = pd.DataFrame({"Dia": [d[:3] for d in DIAS], "Valor": [reais(por_dia[d]) for d in DIAS]})
            st.altair_chart(alt.Chart(df).mark_bar(color=ARDOSIA, cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
                x=alt.X("Dia:N", sort=None, title=None), y=alt.Y("Valor:Q", title=None),
                tooltip=["Dia", alt.Tooltip("Valor:Q", format=",.2f")]).properties(height=250), use_container_width=True)

        g1, g2 = st.columns(2)
        cats = {}
        for x in linhas:
            for c, v in x["cats"].items():
                cats[c] = cats.get(c, 0) + v
        with g1:
            st.markdown("**Despesas por categoria**")
            if cats:
                df = pd.DataFrame({"Categoria": list(cats), "Valor": [reais(v) for v in cats.values()]})
                st.altair_chart(alt.Chart(df).mark_bar(color=BRONZE, cornerRadiusTopRight=6, cornerRadiusBottomRight=6).encode(
                    y=alt.Y("Categoria:N", sort="-x", title=None), x=alt.X("Valor:Q", title=None),
                    tooltip=["Categoria", alt.Tooltip("Valor:Q", format=",.2f")]).properties(height=250), use_container_width=True)
            else:
                st.caption("Nenhuma despesa lançada no período.")
        with g2:
            st.markdown("**Receitas, despesas e resultado**")
            df = pd.DataFrame([{"Mês": rotulo_curto(x["comp"]), "ordem": i, "Tipo": tp, "Valor": reais(x[kk])}
                               for i, x in enumerate(linhas) for tp, kk in (("Receitas", "receita"), ("Despesas", "despesas"), ("Resultado", "resultado"))])
            st.altair_chart(alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("Mês:N", sort=alt.SortField("ordem"), title=None), xOffset=alt.XOffset("Tipo:N", sort=["Receitas", "Despesas", "Resultado"]),
                y=alt.Y("Valor:Q", title=None),
                color=alt.Color("Tipo:N", scale=alt.Scale(domain=["Receitas", "Despesas", "Resultado"], range=[VERDE, BRONZE, AZUL]), legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Mês", "Tipo", alt.Tooltip("Valor:Q", format=",.2f")]).properties(height=250), use_container_width=True)

        st.markdown("**Leitura do período**")
        itens = []
        if ativos:
            melhor = max(ativos, key=lambda x: x["receita"])
            itens.append(f"**Melhor mês:** {melhor['rotulo']}, com {brl(melhor['receita'])} de receita.")
        if len(ativos) > 1 and ativos[-2]["receita"]:
            g = ativos[-1]["receita"] / ativos[-2]["receita"] - 1
            pct_txt = f"{abs(g) * 100:.1f}".replace(".", ",")
            itens.append(f"**Ritmo recente:** {ativos[-1]['rotulo']} ficou {pct_txt}% {'acima' if g >= 0 else 'abaixo'} de {ativos[-2]['rotulo']}.")
        av = din + pix + car
        if av:
            itens.append(f"**Pagamento avulso:** PIX {pix / av * 100:.0f}% · dinheiro {din / av * 100:.0f}% · cartão {car / av * 100:.0f}%.")
        if rec:
            itens.append(f"**Mensalistas:** {mensal / rec * 100:.0f}% da receita do período.")
        dia_forte = max(DIAS, key=lambda d: por_dia[d])
        if por_dia[dia_forte]:
            itens.append(f"**Dia mais forte:** {dia_forte}, com {brl(por_dia[dia_forte])} somados.")
        itens.append(f"**Despesas:** {brl(desp)}; maior categoria: {max(cats, key=cats.get)} ({brl(max(cats.values()))})." if cats
                     else "**Despesas:** nenhuma lançada. O resultado só vira lucro real depois de lançar os custos.")
        st.markdown("\n".join(f"- {i}" for i in itens))


# ================================================================ RECEITAS
with aba_rec:
    esq, dir_ = st.columns([2, 3], gap="large")
    with esq:
        st.subheader("Lançar receita")
        data_r = st.date_input("Data", value=data_padrao(), min_value=MIN_DATA, max_value=MAX_DATA, format="DD/MM/YYYY", key="r_data")
        comp_r = data_r.isoformat()[:7]
        modalidade = st.radio("Modalidade", [*MODALIDADES, "Mensal"], horizontal=True, key="r_mod")
        sub, ferias_r = None, False
        if modalidade == "Mensal":
            pagos = {p["mensalista_id"] for p in T["pagamentos"] if p["competencia"] == comp_r}
            ativos_m = [m for m in T["mensalistas"] if m["ativo"] and m["id"] not in pagos]
            if not ativos_m:
                st.info(f"Nenhum mensalista ativo pendente em {rotulo(comp_r)}. Cadastre na aba Mensalistas.")
            else:
                sub = st.selectbox("Mensalista que está pagando", ativos_m, key="r_sub",
                                   format_func=lambda m: f"{m['nome']} · {descricao_veiculo(m)} · {brl(m['valor'])}")
                st.caption(f"O pagamento quita a competência {rotulo(comp_r)}.")
                ferias_r = st.checkbox("Férias: cobrar metade da mensalidade", key="r_ferias")
        with st.form("f_receita", clear_on_submit=True):
            pagamento = st.radio("Forma de pagamento", PAGAMENTOS, horizontal=True)
            valor = st.number_input("Valor (R$)", min_value=0.0, step=1.0, format="%.2f",
                                    value=(((sub["valor"] + 1) // 2 if ferias_r else sub["valor"]) / 100) if sub else 0.0,
                                    key=f"r_valor_{sub['id'] if sub else 'avulso'}_{int(ferias_r)}")
            enviar = st.form_submit_button("Adicionar receita", type="primary", use_container_width=True,
                                           disabled=modalidade == "Mensal" and not sub)
        if enviar:
            v = centavos(f"{valor:.2f}")
            if modalidade == "Mensal":
                acao(lambda: db.pagar(sub, comp_r, data_r.isoformat(), pagamento, v, ferias=ferias_r),
                     f"{'Férias' if ferias_r else 'Mensalidade'} de {sub['nome']} registrada.")
            else:
                acao(lambda: db.add_receita(data_r.isoformat(), modalidade, pagamento, v), f"{modalidade} de {brl(v)} registrada.")

    with dir_:
        d = mes(T, comp_r)
        st.subheader(f"Receitas de {d['rotulo']}")
        dia_total = sum(e["valor"] for e in d["ent"] if e["data"] == data_r.isoformat()) + \
            sum(p["valor"] for p in d["pays"] if p.get("data") == data_r.isoformat())
        m = st.columns(4)
        for i, md in enumerate(MODALIDADES):
            m[i].metric(md, brl(d["mods"][md]))
        m[3].metric("Mensal", brl(sum(p["valor"] for p in d["pays"])))
        m = st.columns(4)
        por_forma = lambda f: sum(e["valor"] for e in d["ent"] if e["pagamento"] == f) + sum(p["valor"] for p in d["pays"] if p.get("pagamento") == f)
        for i, f in enumerate(PAGAMENTOS):
            m[i].metric(f, brl(por_forma(f)))
        m[3].metric("Total do mês", brl(sum(e["valor"] for e in d["ent"]) + sum(p["valor"] for p in d["pays"])))

        so_dia = st.toggle(f"Mostrar só o dia {br(data_r.isoformat())} ({brl(dia_total)})", value=False, key="r_sodia")
        itens = [{"tipo": "r", "id": e["id"], "Data": e["data"], "Modalidade": e["modalidade"], "Mensalista": "",
                  "Pagamento": e["pagamento"], "valor": e["valor"]} for e in d["ent"]] + \
                [{"tipo": "p", "id": p["mensalista_id"], "Data": p.get("data") or "", "Modalidade": "Mensal", "Mensalista": (p.get("nome") or "") + (" (férias)" if p.get("ferias") else ""),
                  "Pagamento": p.get("pagamento") or "", "valor": p["valor"]} for p in d["pays"]]
        if so_dia:
            itens = [x for x in itens if x["Data"] == data_r.isoformat()]
        itens.sort(key=lambda x: x["Data"], reverse=True)
        if not itens:
            st.info("Nenhuma receita lançada ainda.")
        else:
            df = pd.DataFrame([{"Data": br(x["Data"]), "Modalidade": x["Modalidade"], "Mensalista": x["Mensalista"],
                                "Pagamento": x["Pagamento"], "Valor": brl(x["valor"])} for x in itens])
            sel = tabela_selecionavel(df, "t_rec", altura=min(38 + 35 * len(df), 460))
            escolhidos = [itens[i] for i in sel]

            def apagar():
                for x in escolhidos:
                    if x["tipo"] == "r":
                        db.del_receita(x["id"])
                    else:
                        db.desfazer_pagamento(x["id"], comp_r)
            excluir_popover("Excluir selecionadas", len(escolhidos), apagar, "Lançamentos excluídos.", "del_rec")


# ============================================================= MENSALISTAS
with aba_men:
    todos = T["mensalistas"]
    por_id = {m["id"]: m for m in todos}
    esq, dir_ = st.columns([2, 3], gap="large")
    with esq:
        opcoes = [None, *[m["id"] for m in todos]]
        edit_id = st.selectbox("Cadastro", opcoes, key="m_edit",
                               format_func=lambda i: "Novo mensalista" if i is None else f"Editar: {por_id[i]['nome']}")
        m0 = por_id.get(edit_id) or {}
        with st.form(f"f_mens_{edit_id or 'novo'}", clear_on_submit=edit_id is None):
            nome = st.text_input("Nome", value=m0.get("nome", ""), placeholder="Ex.: João Silva")
            a, b = st.columns(2)
            veiculo = a.selectbox("Veículo", VEICULOS, index=VEICULOS.index(m0["veiculo"]) if m0.get("veiculo") in VEICULOS else 0)
            plano = b.selectbox("Plano", PLANOS, index=PLANOS.index(m0["plano"]) if m0.get("plano") in PLANOS else 0)
            a, b = st.columns(2)
            modelo = a.text_input("Modelo do veículo", value=m0.get("modelo") or "", placeholder="Ex.: Onix prata")
            placa = b.text_input("Placa", value=placa_fmt(m0.get("placa")), placeholder="Ex.: ABC1D23", max_chars=8)
            a, b = st.columns(2)
            valor_m = a.number_input("Valor mensal (R$)", min_value=0.0, step=10.0, format="%.2f", value=m0.get("valor", 0) / 100)
            inicio = b.date_input("Início do plano", value=date.fromisoformat(m0["inicio"]) if m0.get("inicio") else data_padrao(),
                                  min_value=MIN_DATA, max_value=MAX_DATA, format="DD/MM/YYYY")
            obs = st.text_input("Observação", value=m0.get("obs") or "", placeholder="Ex.: segunda e quarta")
            if st.form_submit_button("Salvar alterações" if edit_id else "Cadastrar mensalista", type="primary", use_container_width=True):
                dados_m = {"nome": nome, "veiculo": veiculo, "modelo": modelo, "placa": placa, "plano": plano, "valor": centavos(f"{valor_m:.2f}"),
                           "inicio": inicio.isoformat(), "obs": obs.strip()}
                acao(lambda: db.salvar_mensalista(dados_m, edit_id), "Cadastro atualizado." if edit_id else "Mensalista cadastrado.")

    with dir_:
        comp_m = escolher_comp("Competência", "m_comp")
        pagos = {p["mensalista_id"]: p for p in T["pagamentos"] if p["competencia"] == comp_m}
        vigentes = [m for m in todos if m["ativo"] and (m.get("inicio") or INICIO)[:7] <= comp_m]
        pend = [m for m in vigentes if m["id"] not in pagos]
        k = st.columns(4)
        k[0].metric("Ativos", len(vigentes))
        k[1].metric("Previsto", brl(sum(pagos[m["id"]]["valor"] if m["id"] in pagos and pagos[m["id"]].get("ferias") else m["valor"] for m in vigentes)),
                    help="Mensalistas em férias entram com meia mensalidade.")
        k[2].metric("Recebido", brl(sum(p["valor"] for p in pagos.values())))
        k[3].metric("Pendente", brl(sum(m["valor"] for m in pend)), help=f"{len(pend)} cliente(s)")
        if not todos:
            st.info("Nenhum mensalista cadastrado ainda. Use o formulário ao lado.")
        else:
            def status(m):
                if not m["ativo"]:
                    return "Inativo"
                if (m.get("inicio") or INICIO)[:7] > comp_m:
                    return f"Começa {br(m['inicio'])}"
                p = pagos.get(m["id"])
                return (f"Pago{' (férias)' if p.get('ferias') else ''} em {br(p.get('data'))} ({p.get('pagamento')})") if p else "Pendente"
            df = pd.DataFrame([{"Mensalista": m["nome"], "Veículo": m["veiculo"], "Modelo": m.get("modelo") or "", "Placa": placa_fmt(m.get("placa")), "Plano": m["plano"],
                                "Valor": brl(m["valor"]), "Status": status(m), "Obs.": m.get("obs") or ""} for m in todos])
            sel = tabela_selecionavel(df, f"t_men_{comp_m}")
            esc = [todos[i] for i in sel]
            if esc:
                st.markdown(f"**{len(esc)} selecionado(s):** " + ", ".join(m["nome"] for m in esc))
                a, a2 = st.columns(2)
                forma = a.selectbox("Forma de pagamento", PAGAMENTOS, index=1, key="m_forma")
                tipo = a2.selectbox("Cobrança", ["Mensalidade cheia", "Férias (metade do valor)"], key="m_tipo")
                ferias_m = tipo.startswith("Férias")
                b, c, d_ = st.columns(3)
                pagaveis = [m for m in esc if m["ativo"] and m["id"] not in pagos]
                if b.button("Marcar pago", disabled=not pagaveis, use_container_width=True):
                    dt = hoje() if hoje()[:7] == comp_m else comp_m + "-01"
                    acao(lambda: [db.pagar(m, comp_m, dt, forma, ferias=ferias_m) for m in pagaveis],
                         f"{len(pagaveis)} pagamento(s) de {rotulo(comp_m)} registrado(s){' como férias' if ferias_m else ''}.")
                pagos_sel = [m for m in esc if m["id"] in pagos]
                if c.button("Desmarcar pago", disabled=not pagos_sel, use_container_width=True):
                    acao(lambda: [db.desfazer_pagamento(m["id"], comp_m) for m in pagos_sel], "Pagamento(s) desmarcado(s).")
                if d_.button("Ativar / inativar", use_container_width=True):
                    acao(lambda: [db.ativar_mensalista(m["id"], not m["ativo"]) for m in esc], "Situação atualizada.")
                excluir_popover("Excluir cadastro", len(esc), lambda: [db.del_mensalista(m["id"]) for m in esc],
                                "Cadastro excluído. Pagamentos anteriores continuam no histórico.", "del_men")
            else:
                st.caption("Marque mensalistas na tabela para registrar pagamento, inativar ou excluir.")


# ================================================================ DESPESAS
with aba_desp:
    esq, dir_ = st.columns([2, 3], gap="large")
    with esq:
        st.subheader("Lançar despesa")
        with st.form("f_desp", clear_on_submit=True):
            data_d = st.date_input("Data", value=data_padrao(), min_value=MIN_DATA, max_value=MAX_DATA, format="DD/MM/YYYY")
            cat = st.selectbox("Categoria", CATEGORIAS)
            desc = st.text_input("Descrição (opcional)", placeholder="Ex.: troca de lâmpadas")
            valor_d = st.number_input("Valor (R$)", min_value=0.0, step=1.0, format="%.2f")
            if st.form_submit_button("Adicionar despesa", type="primary", use_container_width=True):
                v = centavos(f"{valor_d:.2f}")
                acao(lambda: db.add_despesa(data_d.isoformat(), cat, desc.strip(), v), f"Despesa de {brl(v)} lançada.")
    with dir_:
        comp_d = escolher_comp("Competência", "d_comp")
        d = mes(T, comp_d)
        st.subheader(f"Despesas de {d['rotulo']}")
        cats = sorted(d["cats"].items(), key=lambda x: -x[1])
        cols = st.columns(4)
        for i, (c, v) in enumerate(cats[:3]):
            cols[i].metric(c, brl(v))
        cols[3].metric("Total do mês", brl(d["despesas"]))
        linhas_d = sorted(d["exp"], key=lambda e: e["data"], reverse=True)
        if not linhas_d:
            st.info("Nenhuma despesa nesta competência.")
        else:
            df = pd.DataFrame([{"Data": br(e["data"]), "Categoria": e["categoria"], "Descrição": e.get("descricao") or "",
                                "Valor": brl(e["valor"])} for e in linhas_d])
            sel = tabela_selecionavel(df, f"t_desp_{comp_d}")
            esc = [linhas_d[i] for i in sel]
            excluir_popover("Excluir selecionadas", len(esc), lambda: [db.del_despesa(e["id"]) for e in esc], "Despesa(s) excluída(s).", "del_desp")


# ====================================================== FECHAMENTO E DADOS
with aba_fech:
    st.subheader("Fechamento do mês")
    st.caption("Os totais vêm dos lançamentos. Os campos manuais só valem para meses sem lançamentos (por exemplo, meses anotados em papel).")
    comp_f = escolher_comp("Competência", "f_comp")
    d = mes(T, comp_f)
    k = st.columns(3)
    k[0].metric("Receita", brl(d["receita"]))
    k[1].metric("Despesas", brl(d["despesas"]))
    k[2].metric(f"Resultado de {MESES[int(comp_f[5:]) - 1]}", brl(d["resultado"]))
    k = st.columns(4)
    k[0].metric("Dinheiro (avulsos)", brl(d["dinheiro"]))
    k[1].metric("PIX (avulsos)", brl(d["pix"]))
    k[2].metric("Cartão (avulsos)", brl(d["cartao"]))
    k[3].metric("Mensalistas", brl(d["mensal"]))

    st.download_button("Baixar fechamento em Excel", data=gerar_excel(T, comp_f), type="primary",
                       file_name=f"Fechamento_{MESES[int(comp_f[5:]) - 1]}_{comp_f[:4]}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.expander("Valores manuais do fechamento"):
        f = d["manual"] or {}
        if d["tem_rec"] and d["tem_pag"]:
            st.caption("Este mês já tem receitas e mensalidades lançadas; os totais vêm dos lançamentos.")
        with st.form(f"f_fech_{comp_f}"):
            a, b = st.columns(2)
            mc = a.number_input("Dinheiro", min_value=0.0, format="%.2f", value=f.get("dinheiro", 0) / 100, disabled=d["tem_rec"])
            mp = b.number_input("PIX", min_value=0.0, format="%.2f", value=f.get("pix", 0) / 100, disabled=d["tem_rec"])
            mk = a.number_input("Cartão", min_value=0.0, format="%.2f", value=f.get("cartao", 0) / 100, disabled=d["tem_rec"])
            mm = b.number_input("Mensalistas", min_value=0.0, format="%.2f", value=f.get("mensalistas", 0) / 100, disabled=d["tem_pag"])
            if st.form_submit_button("Salvar fechamento", disabled=d["tem_rec"] and d["tem_pag"]):
                acao(lambda: db.salvar_fechamento(comp_f, *(centavos(f"{v:.2f}") for v in (mc, mp, mk, mm))),
                     f"Fechamento de {rotulo(comp_f)} salvo.")

    st.divider()
    st.subheader("Dados")
    a, b = st.columns(2, gap="large")
    with a:
        st.markdown("**Trazer dados de outro app**")
        st.caption("Aceita a cópia de segurança do app no Claude, o arquivo \"Exportar para Python\" do dashboard antigo "
                   "e a cópia de segurança deste sistema. Importar o mesmo arquivo de novo não duplica nada.")
        arq = st.file_uploader("Arquivo JSON", type=["json"], key="imp")
        if arq is not None:
            try:
                raw = json.loads(arq.getvalue().decode("utf-8"))
                prev = converter_backup(raw)
                st.info(f"Encontrado: {len(prev['receitas'])} receitas, {len(prev['pagamentos'])} mensalidades pagas, "
                        f"{len(prev['mensalistas'])} mensalistas, {len(prev['despesas'])} despesas e {len(prev['fechamentos'])} fechamentos manuais.")
                if st.button("Importar dados", type="primary"):
                    acao(lambda: db.importar(raw), "Dados importados.")
            except (ValueError, UnicodeDecodeError) as e:
                st.error(str(e) if isinstance(e, ValueError) and "reconhecido" in str(e) else "Arquivo inválido.")
    with b:
        st.markdown("**Cópia de segurança**")
        st.caption("Baixa todos os dados em um arquivo. Guarde uma cópia todo mês.")
        st.download_button("Baixar cópia de segurança", data=db.backup(), file_name=f"5estrelas-backup-{hoje()}.json",
                           mime="application/json")
        if segredo("senha"):
            if st.button("Sair"):
                st.session_state.logado = False
                st.rerun()
