"""Banco de dados e regras do Estacionamento 5 Estrelas.

Funciona com PostgreSQL (Supabase, na nuvem) e com SQLite (para testes no
computador). Todos os valores em dinheiro são guardados em CENTAVOS (inteiros),
para não haver erro de arredondamento.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MODALIDADES = ["Rotativa", "Pernoite", "Diária"]
PAGAMENTOS = ["Dinheiro", "PIX", "Cartão"]
CATEGORIAS = ["Internet", "Celular", "Manutenção", "Contador", "Salário", "Impostos",
              "Luz", "Água", "Aluguel", "Outros"]
VEICULOS = ["Carro", "Moto"]
PLANOS = ["Todos os dias", "2 vezes por semana", "Personalizado"]
INICIO = "2026-09"  # primeira competência da base

TABELAS = """
CREATE TABLE IF NOT EXISTS receitas (
  id TEXT PRIMARY KEY, data TEXT NOT NULL, modalidade TEXT NOT NULL,
  pagamento TEXT NOT NULL, valor INTEGER NOT NULL, criado_em TEXT);
CREATE TABLE IF NOT EXISTS mensalistas (
  id TEXT PRIMARY KEY, nome TEXT NOT NULL, veiculo TEXT, plano TEXT,
  valor INTEGER NOT NULL, inicio TEXT, obs TEXT, ativo INTEGER NOT NULL DEFAULT 1,
  modelo TEXT DEFAULT '', placa TEXT DEFAULT '',
  criado_em TEXT);
CREATE TABLE IF NOT EXISTS pagamentos (
  mensalista_id TEXT NOT NULL, competencia TEXT NOT NULL, valor INTEGER NOT NULL,
  data TEXT, pagamento TEXT, nome TEXT, criado_em TEXT, ferias INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (mensalista_id, competencia));
CREATE TABLE IF NOT EXISTS despesas (
  id TEXT PRIMARY KEY, data TEXT NOT NULL, categoria TEXT NOT NULL,
  descricao TEXT, valor INTEGER NOT NULL, criado_em TEXT);
CREATE TABLE IF NOT EXISTS fechamentos (
  competencia TEXT PRIMARY KEY, dinheiro INTEGER NOT NULL DEFAULT 0,
  pix INTEGER NOT NULL DEFAULT 0, cartao INTEGER NOT NULL DEFAULT 0,
  mensalistas INTEGER NOT NULL DEFAULT 0, criado_em TEXT);
"""


# ----------------------------------------------------------------- utilidades
def hoje() -> str:
    return datetime.now(FUSO).date().isoformat()


def agora() -> str:
    return datetime.now(FUSO).isoformat(timespec="seconds")


def novo_id() -> str:
    return uuid.uuid4().hex


def centavos(valor) -> int:
    """Converte 12,50 / '12.50' / 12.5 em 1250. Recusa negativos e mais de 2 casas."""
    try:
        d = Decimal(str(valor).strip().replace("R$", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError("Valor inválido.")
    if not d.is_finite() or d < 0:
        raise ValueError("O valor não pode ser negativo.")
    c = d * 100
    if c != c.to_integral_value():
        raise ValueError("Use no máximo duas casas decimais.")
    return int(c)


def brl(c: int | float) -> str:
    s = f"{(c or 0) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + s


def br(d: str | None) -> str:
    return "/".join(d.split("-")[::-1]) if d else "—"


def rotulo(comp: str) -> str:
    a, m = comp.split("-")
    return f"{MESES[int(m) - 1]} {a}"


def rotulo_curto(comp: str) -> str:
    a, m = comp.split("-")
    return f"{MESES[int(m) - 1][:3]}/{a[2:]}"


def dia_semana(d: str) -> str:
    return DIAS[date.fromisoformat(d).weekday()]


def data_valida(d: str | None) -> bool:
    try:
        x = date.fromisoformat(str(d))
    except (TypeError, ValueError):
        return False
    return x.isoformat()[:7] >= INICIO and x.year <= 2100


def comp_valida(c: str | None) -> bool:
    return bool(c) and len(c) == 7 and data_valida(c + "-01")


def normalizar_placa(p) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(p or "").upper())


def placa_valida(p: str) -> bool:
    """Vazio (opcional), padrão antigo ABC1234 ou Mercosul ABC1D23."""
    return not p or bool(re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", p))


def placa_fmt(p) -> str:
    p = normalizar_placa(p)
    return f"{p[:3]}-{p[3:]}" if re.fullmatch(r"[A-Z]{3}[0-9]{4}", p) else p


def descricao_veiculo(m: dict) -> str:
    return " · ".join(x for x in (m.get("veiculo"), m.get("modelo"), placa_fmt(m.get("placa"))) if x)


def ultimo_dia(comp: str) -> str:
    a, m = map(int, comp.split("-"))
    return f"{comp}-{monthrange(a, m)[1]:02d}"


# --------------------------------------------------------------------- banco
class Banco:
    """Conexão simples. `url` começando com postgres usa psycopg2; senão SQLite."""

    def __init__(self, url: str):
        self.url = url
        self.pg = url.startswith(("postgres://", "postgresql://"))
        self._con = None
        self.criar_tabelas()

    # conexão com reconexão automática (o Supabase fecha conexões paradas)
    def _conectar(self):
        if self.pg:
            import psycopg2
            con = psycopg2.connect(self.url, connect_timeout=15)
            con.autocommit = False
            return con
        con = sqlite3.connect(self.url, check_same_thread=False)
        return con

    def con(self):
        if self._con is None or (self.pg and self._con.closed):
            self._con = self._conectar()
        return self._con

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.pg else sql

    def _run(self, sql, params=(), fetch=False, many=False):
        for tentativa in (1, 2):
            con = self.con()
            try:
                cur = con.cursor()
                if many:
                    cur.executemany(self._sql(sql), params)
                else:
                    cur.execute(self._sql(sql), params)
                rows = None
                if fetch:
                    cols = [c[0] for c in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                con.commit()
                return rows
            except Exception as e:  # conexão caiu: tenta uma vez de novo
                try:
                    con.rollback()
                except Exception:
                    pass
                caiu = self.pg and (getattr(con, "closed", 0) or type(e).__name__ in ("OperationalError", "InterfaceError"))
                if caiu and tentativa == 1:
                    self._con = None
                    continue
                raise

    def q(self, sql, params=()):
        return self._run(sql, params, fetch=True)

    def x(self, sql, params=()):
        self._run(sql, params)

    def xm(self, sql, lista):
        if lista:
            self._run(sql, lista, many=True)

    def criar_tabelas(self):
        for cmd in TABELAS.split(";"):
            if cmd.strip():
                self.x(cmd)
        # bancos criados antes destas opções ganham as colunas novas
        self._coluna("pagamentos", "ferias", "INTEGER NOT NULL DEFAULT 0")
        self._coluna("mensalistas", "modelo", "TEXT DEFAULT ''")
        self._coluna("mensalistas", "placa", "TEXT DEFAULT ''")

    def _coluna(self, tabela, coluna, tipo):
        if self.pg:
            self.x(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {coluna} {tipo}")
            return
        cur = self.con().execute(f"PRAGMA table_info({tabela})")
        if coluna not in [r[1] for r in cur.fetchall()]:
            self.x(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")

    # ------------------------------------------------------------ lançamentos
    def add_receita(self, data, modalidade, pagamento, valor_c):
        if not data_valida(data):
            raise ValueError("Use uma data a partir de 01/09/2026.")
        if modalidade not in MODALIDADES or pagamento not in PAGAMENTOS:
            raise ValueError("Modalidade ou forma de pagamento inválida.")
        if valor_c <= 0:
            raise ValueError("Informe o valor recebido.")
        self.x("INSERT INTO receitas (id,data,modalidade,pagamento,valor,criado_em) VALUES (?,?,?,?,?,?)",
               (novo_id(), data, modalidade, pagamento, valor_c, agora()))

    def del_receita(self, id_):
        self.x("DELETE FROM receitas WHERE id=?", (id_,))

    def salvar_mensalista(self, dados: dict, id_=None):
        if not dados.get("nome", "").strip():
            raise ValueError("Informe o nome do mensalista.")
        if dados.get("valor", 0) <= 0:
            raise ValueError("Informe o valor mensal.")
        if not data_valida(dados.get("inicio")):
            raise ValueError("A data de início deve ser a partir de 01/09/2026.")
        placa = normalizar_placa(dados.get("placa"))
        if not placa_valida(placa):
            raise ValueError("Placa inválida. Use o formato ABC1234 ou ABC1D23.")
        modelo = (dados.get("modelo") or "").strip()
        if id_:
            self.x("UPDATE mensalistas SET nome=?,veiculo=?,modelo=?,placa=?,plano=?,valor=?,inicio=?,obs=? WHERE id=?",
                   (dados["nome"].strip(), dados["veiculo"], modelo, placa, dados["plano"], dados["valor"],
                    dados["inicio"], dados.get("obs", ""), id_))
        else:
            self.x("INSERT INTO mensalistas (id,nome,veiculo,modelo,placa,plano,valor,inicio,obs,ativo,criado_em) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                   (novo_id(), dados["nome"].strip(), dados["veiculo"], modelo, placa, dados["plano"], dados["valor"],
                    dados["inicio"], dados.get("obs", ""), agora()))

    def ativar_mensalista(self, id_, ativo: bool):
        self.x("UPDATE mensalistas SET ativo=? WHERE id=?", (1 if ativo else 0, id_))

    def del_mensalista(self, id_):
        # pagamentos continuam no histórico (guardam o nome)
        self.x("DELETE FROM mensalistas WHERE id=?", (id_,))

    def pagar(self, mensalista: dict, competencia, data, pagamento, valor_c=None, ferias=False):
        """Registra a mensalidade. Em férias, cobra metade do valor combinado."""
        if not comp_valida(competencia):
            raise ValueError("Competência inválida.")
        if pagamento not in PAGAMENTOS:
            raise ValueError("Forma de pagamento inválida.")
        if valor_c is not None and valor_c <= 0:
            raise ValueError("Informe o valor da mensalidade.")
        ja = self.q("SELECT 1 FROM pagamentos WHERE mensalista_id=? AND competencia=?",
                    (mensalista["id"], competencia))
        if ja:
            raise ValueError(f"{mensalista['nome']} já pagou {rotulo(competencia)}.")
        if valor_c is None:
            valor_c = (mensalista["valor"] + 1) // 2 if ferias else mensalista["valor"]
        self.x("INSERT INTO pagamentos (mensalista_id,competencia,valor,data,pagamento,nome,criado_em,ferias) VALUES (?,?,?,?,?,?,?,?)",
               (mensalista["id"], competencia, valor_c, data, pagamento, mensalista["nome"], agora(), 1 if ferias else 0))

    def desfazer_pagamento(self, mensalista_id, competencia):
        self.x("DELETE FROM pagamentos WHERE mensalista_id=? AND competencia=?", (mensalista_id, competencia))

    def add_despesa(self, data, categoria, descricao, valor_c):
        if not data_valida(data):
            raise ValueError("Use uma data a partir de 01/09/2026.")
        if valor_c <= 0:
            raise ValueError("Informe o valor da despesa.")
        self.x("INSERT INTO despesas (id,data,categoria,descricao,valor,criado_em) VALUES (?,?,?,?,?,?)",
               (novo_id(), data, categoria, descricao or "", valor_c, agora()))

    def del_despesa(self, id_):
        self.x("DELETE FROM despesas WHERE id=?", (id_,))

    def salvar_fechamento(self, comp, dinheiro, pix, cartao, mensal):
        self.x("DELETE FROM fechamentos WHERE competencia=?", (comp,))
        self.x("INSERT INTO fechamentos (competencia,dinheiro,pix,cartao,mensalistas,criado_em) VALUES (?,?,?,?,?,?)",
               (comp, dinheiro, pix, cartao, mensal, agora()))

    # --------------------------------------------------------------- leituras
    def mensalistas(self):
        return self.q("SELECT * FROM mensalistas ORDER BY ativo DESC, nome")

    def tudo(self):
        """Carrega todas as tabelas de uma vez (a base é pequena)."""
        return {
            "receitas": self.q("SELECT * FROM receitas ORDER BY data, criado_em"),
            "pagamentos": self.q("SELECT * FROM pagamentos ORDER BY competencia, data"),
            "despesas": self.q("SELECT * FROM despesas ORDER BY data, criado_em"),
            "fechamentos": self.q("SELECT * FROM fechamentos ORDER BY competencia"),
            "mensalistas": self.mensalistas(),
        }

    # ------------------------------------------------------------ importação
    def importar(self, raw: dict) -> dict:
        """Importa backup do app no Claude, do dashboard antigo ou deste app.
        Pode ser repetido sem duplicar nada."""
        dados = converter_backup(raw)
        ins = {
            "receitas": "INSERT INTO receitas (id,data,modalidade,pagamento,valor,criado_em) VALUES (?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING",
            "mensalistas": "INSERT INTO mensalistas (id,nome,veiculo,modelo,placa,plano,valor,inicio,obs,ativo,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING",
            "pagamentos": "INSERT INTO pagamentos (mensalista_id,competencia,valor,data,pagamento,nome,criado_em,ferias) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT (mensalista_id,competencia) DO NOTHING",
            "despesas": "INSERT INTO despesas (id,data,categoria,descricao,valor,criado_em) VALUES (?,?,?,?,?,?) ON CONFLICT (id) DO NOTHING",
            "fechamentos": "INSERT INTO fechamentos (competencia,dinheiro,pix,cartao,mensalistas,criado_em) VALUES (?,?,?,?,?,?) ON CONFLICT (competencia) DO NOTHING",
        }
        cols = {
            "receitas": ["id", "data", "modalidade", "pagamento", "valor", "criado_em"],
            "mensalistas": ["id", "nome", "veiculo", "modelo", "placa", "plano", "valor", "inicio", "obs", "ativo", "criado_em"],
            "pagamentos": ["mensalista_id", "competencia", "valor", "data", "pagamento", "nome", "criado_em", "ferias"],
            "despesas": ["id", "data", "categoria", "descricao", "valor", "criado_em"],
            "fechamentos": ["competencia", "dinheiro", "pix", "cartao", "mensalistas", "criado_em"],
        }
        for t in ins:
            self.xm(ins[t], [tuple(r.get(c) for c in cols[t]) for r in dados[t]])
        return {t: len(v) for t, v in dados.items()}

    def backup(self) -> str:
        return json.dumps({"format": "5estrelas-python-v1", "exportedAt": agora(), **self.tudo()},
                          ensure_ascii=False, indent=2, default=str)


# ----------------------------------------------------------- conversão backup
def _c(v) -> int:
    """Reais (float) do formato antigo -> centavos."""
    try:
        return int(round(float(v or 0) * 100))
    except (TypeError, ValueError):
        return 0


def converter_backup(raw: dict) -> dict:
    out = {"receitas": [], "mensalistas": [], "pagamentos": [], "despesas": [], "fechamentos": []}
    fmt = raw.get("format")

    if fmt == "5estrelas-python-v1":
        for t in out:
            out[t] = [r for r in raw.get(t, []) if isinstance(r, dict)]
        for p in out["pagamentos"]:
            p["ferias"] = 1 if p.get("ferias") else 0
        for m in out["mensalistas"]:
            m["modelo"], m["placa"] = m.get("modelo") or "", normalizar_placa(m.get("placa"))
        return out

    if fmt == "5estrelas-app-v1":  # cópia de segurança do app no Claude
        for comp, doc in (raw.get("receitas") or {}).items():
            for i, e in ((doc or {}).get("entries") or {}).items():
                if not e or e.get("deleted") or not data_valida(e.get("date")):
                    continue
                out["receitas"].append({"id": i, "data": e["date"], "modalidade": e.get("service") if e.get("service") in MODALIDADES else "Rotativa",
                                        "pagamento": e.get("payment") if e.get("payment") in PAGAMENTOS else "Dinheiro",
                                        "valor": _c(e.get("amount")), "criado_em": None})
        for i, s in (raw.get("mensalistas") or {}).items():
            out["mensalistas"].append({"id": i, "nome": s.get("name") or "Mensalista", "veiculo": s.get("vehicle") or "Carro",
                                       "modelo": s.get("model") or "", "placa": normalizar_placa(s.get("plate")),
                                       "plano": s.get("plan") or "Todos os dias", "valor": _c(s.get("value")),
                                       "inicio": s.get("startDate") if data_valida(s.get("startDate")) else INICIO + "-01",
                                       "obs": s.get("notes") or "", "ativo": 0 if s.get("active") is False else 1, "criado_em": None})
        for comp, doc in (raw.get("pagamentos") or {}).items():
            if not comp_valida(comp):
                continue
            for sid, p in ((doc or {}).get("pays") or {}).items():
                if not p or p.get("deleted"):
                    continue
                out["pagamentos"].append({"mensalista_id": sid, "competencia": comp, "valor": _c(p.get("value")),
                                          "data": p.get("date") if data_valida(p.get("date")) else comp + "-01",
                                          "pagamento": p.get("payment") or "Não informado", "nome": p.get("name") or "Mensalista", "criado_em": None,
                                          "ferias": 1 if p.get("ferias") else 0})
        for comp, doc in (raw.get("despesas") or {}).items():
            for i, e in ((doc or {}).get("entries") or {}).items():
                if not e or e.get("deleted") or not data_valida(e.get("date")):
                    continue
                out["despesas"].append({"id": i, "data": e["date"], "categoria": e.get("category") or "Outros",
                                        "descricao": e.get("desc") or "", "valor": _c(e.get("amount")), "criado_em": None})
        for comp, f in (raw.get("fechamentos") or {}).items():
            if comp_valida(comp) and f:
                out["fechamentos"].append({"competencia": comp, "dinheiro": _c(f.get("cash")), "pix": _c(f.get("pix")),
                                           "cartao": _c(f.get("card")), "mensalistas": _c(f.get("monthly")), "criado_em": None})
        return out

    st = raw.get("storage")  # dashboard HTML antigo ("Exportar para Python")
    if isinstance(st, dict):
        P = "estacionamento5estrelas_"
        g = lambda n: st.get(P + n + "_v1") if isinstance(st.get(P + n + "_v1"), list) else []
        for x in g("novo_set2026_diarios"):
            if "amount" in x:
                itens = [x]
            else:
                itens = [{**x, "id": f"{x.get('id')}_{i}", "payment": p, "amount": x.get(f)}
                         for i, (p, f) in enumerate([("Dinheiro", "cash"), ("PIX", "pix"), ("Cartão", "card")]) if x.get(f)]
            for e in itens:
                if data_valida(e.get("date")) and _c(e.get("amount")) > 0:
                    out["receitas"].append({"id": f"old{e.get('id')}", "data": e["date"],
                                            "modalidade": e.get("service") if e.get("service") in MODALIDADES else "Rotativa",
                                            "pagamento": e.get("payment") if e.get("payment") in PAGAMENTOS else "Dinheiro",
                                            "valor": _c(e.get("amount")), "criado_em": None})
        subs = g("novo_set2026_mensalistas")
        for s in subs:
            if s.get("name"):
                out["mensalistas"].append({"id": f"old{s.get('id')}", "nome": str(s["name"]), "veiculo": s.get("vehicle") or "Carro", "modelo": "", "placa": "",
                                           "plano": s.get("plan") or "Todos os dias", "valor": _c(s.get("value")),
                                           "inicio": s.get("startDate") if data_valida(s.get("startDate")) else INICIO + "-01",
                                           "obs": s.get("notes") or "", "ativo": 0 if s.get("active") is False else 1, "criado_em": None})
        nomes = {str(s.get("id")): s.get("name") for s in subs}
        for p in g("novo_set2026_mensalistas_pagamentos"):
            try:
                comp = f"{int(p.get('year'))}-{int(p.get('month')):02d}"
            except (TypeError, ValueError):
                continue
            if comp_valida(comp):
                out["pagamentos"].append({"mensalista_id": f"old{p.get('subId')}", "competencia": comp, "valor": _c(p.get("value")),
                                          "data": p.get("date") if data_valida(p.get("date")) else comp + "-01",
                                          "pagamento": p.get("payment") or "Não informado",
                                          "nome": p.get("name") or nomes.get(str(p.get("subId"))) or "Mensalista", "criado_em": None, "ferias": 0})
        for x in g("set2026_despesas"):
            if data_valida(x.get("date")) and _c(x.get("amount")) > 0:
                out["despesas"].append({"id": f"old{x.get('id')}", "data": x["date"], "categoria": str(x.get("category") or "Outros"),
                                        "descricao": "", "valor": _c(x.get("amount")), "criado_em": None})
        vistos = {}
        for x in g("set2026_importacao") + g("novo_set2026_fechamentos"):
            try:
                comp = f"{int(x.get('year'))}-{int(x.get('month')):02d}"
            except (TypeError, ValueError):
                continue
            if comp_valida(comp):
                vistos[comp] = {"competencia": comp, "dinheiro": _c(x.get("cash")), "pix": _c(x.get("pix")),
                                "cartao": _c(x.get("card")), "mensalistas": _c(x.get("monthly")), "criado_em": None}
        out["fechamentos"] = list(vistos.values())
        return out

    raise ValueError("Arquivo não reconhecido. Use a cópia de segurança do app ou o JSON do dashboard antigo.")


# -------------------------------------------------------------- fechamento
def competencias(t: dict) -> list[str]:
    ks = {r["data"][:7] for r in t["receitas"]} | {p["competencia"] for p in t["pagamentos"]} \
        | {d["data"][:7] for d in t["despesas"]} | {f["competencia"] for f in t["fechamentos"]}
    return sorted(k for k in ks if comp_valida(k))


def mes(t: dict, comp: str) -> dict:
    """Totais de uma competência. Mesma regra do app anterior: valores manuais
    do fechamento só valem quando o mês não tem lançamentos daquele tipo."""
    ent = [r for r in t["receitas"] if r["data"][:7] == comp]
    pays = [p for p in t["pagamentos"] if p["competencia"] == comp]
    exp = [d for d in t["despesas"] if d["data"][:7] == comp]
    f = next((x for x in t["fechamentos"] if x["competencia"] == comp), None)
    tem_rec, tem_pag = bool(ent), bool(pays)
    por = lambda p: sum(r["valor"] for r in ent if r["pagamento"] == p)
    dinheiro = por("Dinheiro") if tem_rec else (f or {}).get("dinheiro", 0)
    pix = por("PIX") if tem_rec else (f or {}).get("pix", 0)
    cartao = por("Cartão") if tem_rec else (f or {}).get("cartao", 0)
    mensal = sum(p["valor"] for p in pays) if tem_pag else (f or {}).get("mensalistas", 0)
    mp = lambda p: sum(x["valor"] for x in pays if x["pagamento"] == p)
    cats: dict[str, int] = {}
    for d in exp:
        cats[d["categoria"]] = cats.get(d["categoria"], 0) + d["valor"]
    mods = {m: sum(r["valor"] for r in ent if r["modalidade"] == m) for m in MODALIDADES}
    receita = dinheiro + pix + cartao + mensal
    despesas = sum(d["valor"] for d in exp)
    return {"comp": comp, "rotulo": rotulo(comp), "ent": ent, "pays": pays, "exp": exp, "manual": f,
            "tem_rec": tem_rec, "tem_pag": tem_pag, "dinheiro": dinheiro, "pix": pix, "cartao": cartao,
            "mensal": mensal, "m_dinheiro": mp("Dinheiro"), "m_pix": mp("PIX"), "m_cartao": mp("Cartão"),
            "cats": cats, "mods": mods, "receita": receita, "despesas": despesas, "resultado": receita - despesas}
