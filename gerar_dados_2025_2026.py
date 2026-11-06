"""
Gera chamados ficticios de 01/01/2025 ate 02/11/2026 e grava direto no SQL Server
(dw.fato_chamados e, se faltar, dw.dim_calendario).

COMO USAR (no Prompt de Comando, dentro da pasta do projeto):
    pip install pyodbc
    python gerar_dados_2025_2026.py              -> so mostra a previa (nao grava nada)
    python gerar_dados_2025_2026.py --executar   -> grava no banco

Conexao: usa autenticacao do Windows por padrao. Para mudar, use variaveis de ambiente
(nunca escreva senha no codigo):
    SUPORTE_SQL_SERVER   (padrao: pc-lucas\\sqldev)
    SUPORTE_SQL_DATABASE (padrao: db_suporte_bi)
    SUPORTE_SQL_USER / SUPORTE_SQL_PASSWORD  (so se usar login do SQL Server)

Regras usadas:
- Analistas e clientes: os que ja existem no banco (nada e sorteado de novo).
- id_ticket: continua a partir do maior id que ja existe.
- Volume: 100 mil chamados por ano (~274 por dia). 2026 vai ate 02/11/2026.
- Status realista pela idade do chamado: os antigos ficam quase todos fechados;
  abertos / em andamento se concentram nos ultimos 2 meses.
- Nenhum fechamento depois de 02/11/2026.
- Tudo numa unica transacao: se der qualquer erro, nada e gravado.
"""

import csv
import os
import random
import sys
import unicodedata
from datetime import date, datetime, timedelta

# ------------------------------------------------------------------
# Parametros
# ------------------------------------------------------------------
INICIO = datetime(2025, 1, 1)
# "agora": nenhum chamado abre ou fecha depois deste momento (no maximo ate 02/11/2026)
DATA_REFERENCIA = min(datetime.now().replace(microsecond=0), datetime(2026, 11, 2, 23, 59, 59))
CHAMADOS_POR_ANO = 100_000
CALENDARIO_ATE = date(2026, 12, 31)                    # calendario cobre o ano todo
SEMENTE = 2025                                         # mesma semente = mesmos dados
CSV_SAIDA = "fato_chamados_2025_2026.csv"              # copia do que foi gerado

# Mesmas regras do gerar_dados.py original
categorias = ["Login", "Erro Sistema", "Performance", "Integração", "Financeiro"]
peso_categoria = [0.25, 0.30, 0.20, 0.15, 0.10]
prioridades = ["Baixa", "Média", "Alta", "Crítica"]
peso_prioridade = [0.4, 0.3, 0.2, 0.1]
performance = {"Júnior": (24, 72), "Pleno": (8, 48), "Sênior": (2, 24)}
sla_resposta = {"Baixa": 8, "Média": 4, "Alta": 2, "Crítica": 1}
sla_resolucao = {"Baixa": 72, "Média": 48, "Alta": 24, "Crítica": 8}

# Status pela idade (dias ate a data de referencia): (Fechado, Em andamento, Aberto)
STATUS_POR_IDADE = [
    (7, (0.45, 0.35, 0.20)),
    (30, (0.75, 0.18, 0.07)),
    (60, (0.92, 0.06, 0.02)),
    (180, (0.985, 0.012, 0.003)),
    (10**9, (0.998, 0.0015, 0.0005)),
]
STATUS = ["Fechado", "Em andamento", "Aberto"]


def sem_acento(txt):
    txt = unicodedata.normalize("NFKD", str(txt))
    return "".join(c for c in txt if not unicodedata.combining(c)).strip().lower()


# ------------------------------------------------------------------
# Geracao (nao depende do banco)
# ------------------------------------------------------------------
def pesos_status(idade_dias):
    for limite, pesos in STATUS_POR_IDADE:
        if idade_dias <= limite:
            return pesos
    return STATUS_POR_IDADE[-1][1]


def gerar_chamados(analistas, ids_clientes, primeiro_id, rng):
    """analistas: lista de (id_analista, nivel). Retorna lista de dicts."""
    dias_total = (DATA_REFERENCIA.date() - INICIO.date()).days + 1
    por_dia = CHAMADOS_POR_ANO / 365
    n = round(dias_total * por_dia)

    dados = []
    for k in range(n):
        id_analista, nivel = rng.choice(analistas)
        categoria = rng.choices(categorias, weights=peso_categoria)[0]
        prioridade = rng.choices(prioridades, weights=peso_prioridade)[0]

        abertura = INICIO + timedelta(days=rng.randint(0, dias_total - 1),
                                      seconds=rng.randint(0, 86399))
        if abertura > DATA_REFERENCIA:
            abertura = DATA_REFERENCIA - timedelta(seconds=rng.randint(60, 3600))

        idade = (DATA_REFERENCIA - abertura).days
        status = rng.choices(STATUS, weights=pesos_status(idade))[0]

        tempo_resposta = rng.randint(1, 12)
        min_h, max_h = performance[nivel]
        tempo_resolucao = rng.randint(min_h, max_h)
        if rng.random() < 0.25:
            tempo_resolucao += rng.randint(10, 50)

        fechamento = None
        if status == "Fechado":
            fechamento = abertura + timedelta(hours=tempo_resolucao)
            if fechamento > DATA_REFERENCIA:      # ainda nao deu tempo de fechar
                status = "Em andamento"
                fechamento = None
        if fechamento is None:
            tempo_resolucao = None

        sla_resp_ok = tempo_resposta <= sla_resposta[prioridade]
        sla_res_ok = None if tempo_resolucao is None else tempo_resolucao <= sla_resolucao[prioridade]

        dados.append({
            "id_ticket": primeiro_id + k,
            "id_analista": id_analista,
            "id_cliente": rng.choice(ids_clientes),
            "categoria": categoria,
            "prioridade": prioridade,
            "status": status,
            "data_abertura": abertura,
            "data_fechamento": fechamento,
            "tempo_resposta": tempo_resposta,
            "tempo_resolucao": tempo_resolucao,
            "sla_resposta_ok": sla_resp_ok,
            "sla_resolucao_ok": sla_res_ok,
        })
    dados.sort(key=lambda r: r["data_abertura"])
    for k, r in enumerate(dados):                  # ids em ordem cronologica
        r["id_ticket"] = primeiro_id + k
    return dados


def criar_id_data(exemplos):
    """Descobre como o banco monta id_data a partir de (id_data, data) existentes."""
    if all(i == int(d.strftime("%Y%m%d")) for i, d in exemplos):
        return lambda d: int(d.strftime("%Y%m%d"))
    deslocamentos = {i - d.toordinal() for i, d in exemplos}
    if len(deslocamentos) == 1:
        off = deslocamentos.pop()
        return lambda d: d.toordinal() + off
    raise RuntimeError("Nao consegui entender o formato de id_data do calendario.")


def montar_calendario(datas_faltando, linhas_existentes, colunas, para_id):
    """Cria as linhas novas do calendario copiando os textos (nome do mes etc.)
    das linhas que ja existem, para manter o mesmo idioma e formato."""
    ex = [dict(zip(colunas, l)) for l in linhas_existentes]
    def d_(r):
        v = r["data"]
        return v.date() if isinstance(v, datetime) else v

    por_mes = {d_(r).month: r for r in ex}
    por_dow = {d_(r).weekday(): r for r in ex}
    por_tri = {(d_(r).month - 1) // 3 + 1: r for r in ex}
    if len(por_mes) < 12 or len(por_dow) < 7:
        raise RuntimeError("O calendario atual nao tem todos os meses/dias da semana "
                           "para copiar o formato.")

    novas = []
    for d in datas_faltando:
        m, dw, t = por_mes[d.month], por_dow[d.weekday()], por_tri[(d.month - 1) // 3 + 1]
        ano_ex = d_(m).year
        linha = {}
        for c in colunas:
            cl = c.lower()
            if cl == "id_data":
                v = para_id(d)
            elif cl == "data":
                v = d
            elif cl == "ano":
                v = d.year
            elif cl == "mes":
                v = d.month
            elif cl == "nome_mes":
                v = m[c]
            elif cl == "mes_ano":
                txt = str(m[c])
                if str(ano_ex) in txt:
                    v = txt.replace(str(ano_ex), str(d.year))
                elif txt.endswith(str(ano_ex)[2:]):
                    v = txt[:-2] + str(d.year)[2:]
                else:
                    raise RuntimeError(f"Formato de mes_ano que eu nao entendi: {txt}")
            elif cl == "trimestre":
                v = t[c]
            elif cl == "nome_trimestre":
                v = t[c]
            elif cl in ("dia_semana", "nome_dia_semana", "fim_de_semana"):
                v = dw[c]
            elif cl == "dia":
                v = d.day
            else:
                raise RuntimeError(f"Coluna do calendario que eu nao conheco: {c}. "
                                   "Nada foi gravado.")
            linha[c] = v
        novas.append(linha)
    return novas


# ------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------
def conectar():
    import pyodbc
    servidor = os.environ.get("SUPORTE_SQL_SERVER", r"pc-lucas\sqldev")
    banco = os.environ.get("SUPORTE_SQL_DATABASE", "db_suporte_bi")
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    preferidos = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    driver = next((d for d in preferidos if d in drivers), drivers[-1] if drivers else None)
    if not driver:
        raise RuntimeError("Nenhum driver ODBC do SQL Server encontrado.")
    partes = [f"DRIVER={{{driver}}}", f"SERVER={servidor}", f"DATABASE={banco}",
              "TrustServerCertificate=yes"]
    if os.environ.get("SUPORTE_SQL_USER"):
        partes += [f"UID={os.environ['SUPORTE_SQL_USER']}",
                   f"PWD={os.environ.get('SUPORTE_SQL_PASSWORD', '')}"]
    else:
        partes.append("Trusted_Connection=yes")
    print(f"Conectando em {servidor} / {banco} (driver: {driver})")
    return pyodbc.connect(";".join(partes), autocommit=False)


def colunas_tabela(cur, schema, tabela):
    """Retorna (nome, nao_gravavel). Colunas IDENTITY ou computadas o proprio
    SQL Server preenche, entao o script nao envia valor para elas."""
    cur.execute("""SELECT c.name, c.is_identity, c.is_computed FROM sys.columns c
                   JOIN sys.tables t ON t.object_id = c.object_id
                   JOIN sys.schemas s ON s.schema_id = t.schema_id
                   WHERE s.name = ? AND t.name = ? ORDER BY c.column_id""", schema, tabela)
    return [(r[0], bool(r[1]) or bool(r[2])) for r in cur.fetchall()]


def mapear_valores(cur, coluna, valores_gerados):
    """Usa exatamente a grafia que ja esta no banco (ex.: 'Crítica' x 'CRÍTICA')."""
    cur.execute(f"SELECT DISTINCT {coluna} FROM dw.fato_chamados WHERE {coluna} IS NOT NULL")
    no_banco = [r[0] for r in cur.fetchall()]
    mapa = {}
    for v in valores_gerados:
        achados = [b for b in no_banco if sem_acento(b) == sem_acento(v)]
        if not achados:
            raise RuntimeError(f"O valor '{v}' de {coluna} nao existe no banco "
                               f"(valores atuais: {no_banco}). Nada foi gravado.")
        mapa[v] = achados[0]
    return mapa


def main():
    executar = "--executar" in sys.argv
    rng = random.Random(SEMENTE)
    con = conectar()
    cur = con.cursor()

    # --- 1. Conferencias -------------------------------------------------
    col_fato = colunas_tabela(cur, "dw", "fato_chamados")
    col_cal = colunas_tabela(cur, "dw", "dim_calendario")
    if not col_fato or not col_cal:
        raise RuntimeError("Nao encontrei dw.fato_chamados ou dw.dim_calendario.")
    if any(ident for nome, ident in col_fato if nome.lower() == "id_ticket"):
        raise RuntimeError("id_ticket e IDENTITY no banco; o script precisa de ajuste.")

    cur.execute("SELECT COUNT(*), MAX(id_ticket), MIN(data_abertura), MAX(data_abertura) "
                "FROM dw.fato_chamados")
    qtd, max_id, dmin, dmax = cur.fetchone()
    print(f"dw.fato_chamados hoje: {qtd:,} linhas | id max {max_id} | {dmin} a {dmax}")

    cur.execute("SELECT COUNT(*) FROM dw.fato_chamados WHERE data_abertura >= ?", INICIO)
    if cur.fetchone()[0] > 0:
        raise RuntimeError("Ja existem chamados a partir de 2025 no banco. "
                           "Para nao duplicar, nada foi gravado.")

    cur.execute("SELECT id_analista, nivel FROM dw.dim_analista")
    analistas = []
    for ida, nivel in cur.fetchall():
        chave = next((k for k in performance if sem_acento(k) == sem_acento(nivel)), None)
        if chave is None:
            raise RuntimeError(f"Nivel desconhecido no banco: {nivel}")
        analistas.append((ida, chave))
    cur.execute("SELECT id_cliente FROM dw.dim_cliente")
    ids_clientes = [r[0] for r in cur.fetchall()]
    print(f"Analistas: {len(analistas)} | Clientes: {len(ids_clientes)}")

    mapa_cat = mapear_valores(cur, "categoria", categorias)
    mapa_pri = mapear_valores(cur, "prioridade", prioridades)
    mapa_sta = mapear_valores(cur, "status", STATUS)

    # formato do SLA no banco (bit/int 0-1 ou texto True/False)
    cur.execute("SELECT TOP 1 sla_resposta_ok FROM dw.fato_chamados WHERE sla_resposta_ok IS NOT NULL")
    exemplo_sla = cur.fetchone()[0]
    sla_texto = isinstance(exemplo_sla, str)
    conv_sla = (lambda b: None if b is None else ("True" if b else "False")) if sla_texto \
        else (lambda b: None if b is None else int(b))

    # --- 2. Calendario ---------------------------------------------------
    nomes_cal = [n for n, _ in col_cal]
    cur.execute(f"SELECT {', '.join(nomes_cal)} FROM dw.dim_calendario")
    linhas_cal = [tuple(r) for r in cur.fetchall()]
    idx_id = [n.lower() for n in nomes_cal].index("id_data")
    idx_dt = [n.lower() for n in nomes_cal].index("data")
    def como_data(v):
        return v.date() if isinstance(v, datetime) else v
    exemplos = [(l[idx_id], como_data(l[idx_dt])) for l in linhas_cal[:500]]
    para_id = criar_id_data(exemplos)
    datas_existentes = {como_data(l[idx_dt]) for l in linhas_cal}
    datas_necessarias = [INICIO.date() + timedelta(days=i)
                         for i in range((CALENDARIO_ATE - INICIO.date()).days + 1)]
    faltando = [d for d in datas_necessarias if d not in datas_existentes]
    novas_cal = montar_calendario(faltando, linhas_cal, nomes_cal, para_id) if faltando else []
    print(f"dw.dim_calendario: {len(linhas_cal):,} datas | faltam {len(faltando)} "
          f"datas entre 2025-01-01 e {CALENDARIO_ATE}")
    if novas_cal:
        print("  exemplo de linha nova do calendario:", novas_cal[0])

    # --- 3. Gerar chamados -----------------------------------------------
    dados = gerar_chamados(analistas, ids_clientes, (max_id or 0) + 1, rng)
    from collections import Counter
    por_ano = Counter(r["data_abertura"].year for r in dados)
    por_status = Counter(r["status"] for r in dados)
    print(f"Chamados novos: {len(dados):,} -> {dict(por_ano)}")
    print(f"Status: {dict(por_status)}")
    print(f"Ids: {dados[0]['id_ticket']} a {dados[-1]['id_ticket']}")
    print(f"Ultima abertura: {dados[-1]['data_abertura']} | ultimo fechamento: "
          f"{max(r['data_fechamento'] for r in dados if r['data_fechamento'])}")

    with open(CSV_SAIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dados[0].keys()))
        w.writeheader()
        w.writerows(dados)
    print(f"Copia salva em {CSV_SAIDA}")

    if not executar:
        print("\nPREVIA: nada foi gravado. Para gravar, rode de novo com --executar")
        con.close()
        return

    # --- 4. Gravar (uma transacao so) -------------------------------------
    nomes_fato = [n for n, nao_gravavel in col_fato if not nao_gravavel]
    grav_cal = [n for n, nao_gravavel in col_cal if not nao_gravavel]
    print(f"Colunas que o SQL Server calcula sozinho (nao enviadas): "
          f"{[n for n, x in col_fato + col_cal if x]}")
    linhas = []
    for r in dados:
        v = {
            "id_ticket": r["id_ticket"], "id_analista": r["id_analista"],
            "id_cliente": r["id_cliente"], "categoria": mapa_cat[r["categoria"]],
            "prioridade": mapa_pri[r["prioridade"]], "status": mapa_sta[r["status"]],
            "data_abertura": r["data_abertura"], "data_fechamento": r["data_fechamento"],
            "tempo_resposta": r["tempo_resposta"], "tempo_resolucao": r["tempo_resolucao"],
            "sla_resposta_ok": conv_sla(r["sla_resposta_ok"]),
            "sla_resolucao_ok": conv_sla(r["sla_resolucao_ok"]),
            "id_data_abertura": para_id(r["data_abertura"].date()),
            "id_data_fechamento": para_id(r["data_fechamento"].date()) if r["data_fechamento"] else None,
        }
        faltam = [n for n in nomes_fato if n.lower() not in v]
        if faltam:
            raise RuntimeError(f"Colunas do fato que eu nao sei preencher: {faltam}. Nada foi gravado.")
        linhas.append(tuple(v[n.lower()] for n in nomes_fato))

    try:
        cur.fast_executemany = True
        if novas_cal:
            cur.executemany(
                f"INSERT INTO dw.dim_calendario ({', '.join(grav_cal)}) "
                f"VALUES ({', '.join('?' * len(grav_cal))})",
                [tuple(l[n] for n in grav_cal) for l in novas_cal])
        lote = 20_000
        for i in range(0, len(linhas), lote):
            cur.executemany(
                f"INSERT INTO dw.fato_chamados ({', '.join(nomes_fato)}) "
                f"VALUES ({', '.join('?' * len(nomes_fato))})", linhas[i:i + lote])
            print(f"  gravadas {min(i + lote, len(linhas)):,} de {len(linhas):,}")
        con.commit()
    except Exception:
        con.rollback()
        print("ERRO: nada foi gravado (rollback).")
        raise

    cur.execute("SELECT COUNT(*), MAX(data_abertura) FROM dw.fato_chamados")
    total, ult = cur.fetchone()
    print(f"\nOK! dw.fato_chamados agora tem {total:,} linhas (ultima abertura: {ult}).")
    con.close()


if __name__ == "__main__":
    main()
