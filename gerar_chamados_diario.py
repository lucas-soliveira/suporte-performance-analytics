"""
Carga DIARIA simulada da plataforma de chamados (fluxo 1 do Power Automate).

Simula o que a plataforma externa de chamados faria no dia a dia e grava o resultado
em dw.fato_chamados:
  1) cria os chamados NOVOS desde a ultima abertura que ja esta no banco ate "agora";
  2) evolui os chamados em aberto: Aberto -> Em andamento -> Fechado
     (so atualiza status, data_fechamento, tempo_resolucao e SLA de resolucao).

O Power BI continua somente leitura: este script representa a plataforma de origem.

COMO USAR (no Prompt de Comando, dentro da pasta do projeto):
    python gerar_chamados_diario.py              -> so mostra a previa (nao grava)
    python gerar_chamados_diario.py --executar   -> grava no banco

Conexao: igual ao gerar_dados_2025_2026.py (autenticacao do Windows; senha so por
variavel de ambiente SUPORTE_SQL_USER / SUPORTE_SQL_PASSWORD, nunca no codigo).
Precisa do gerar_dados_2025_2026.py na mesma pasta (reaproveita as regras e a conexao).

Saida: a ultima linha comeca com "RESULTADO;" para o fluxo ler, e cada execucao
real e registrada em logs/carga_diaria.log.
Tudo numa unica transacao: se der erro, nada e gravado.
"""

import os
import random
import sys
from datetime import date, datetime, timedelta

import gerar_dados_2025_2026 as base

CHAMADOS_POR_DIA = base.CHAMADOS_POR_ANO / 365          # ~274 por dia

# Chance diaria de um chamado em aberto mudar de situacao, pela idade (em dias).
# (idade maxima, chance de fechar no dia, chance de Aberto -> Em andamento)
EVOLUCAO = [
    (7, 0.30, 0.35),
    (30, 0.08, 0.15),
    (60, 0.03, 0.05),
    (10**9, 0.003, 0.01),     # backlog antigo quase nao se mexe (nao zera o passivo)
]

# Chamados novos: quase todos nascem Aberto ou Em andamento; alguns de baixa
# prioridade ja nascem resolvidos (resolucao rapida, dentro do dia).
STATUS_NOVO = (0.10, 0.35, 0.55)   # Fechado, Em andamento, Aberto


def chance(idade_dias):
    for limite, fecha, andamento in EVOLUCAO:
        if idade_dias <= limite:
            return fecha, andamento
    return EVOLUCAO[-1][1], EVOLUCAO[-1][2]


# ------------------------------------------------------------------
# Logica pura (sem banco) - facil de testar
# ------------------------------------------------------------------
def gerar_novos(analistas, ids_clientes, primeiro_id, desde, agora, rng):
    """Chamados abertos no intervalo (desde, agora]."""
    segundos = (agora - desde).total_seconds()
    if segundos <= 0:
        return []
    n = round(segundos / 86400 * CHAMADOS_POR_DIA)
    dados = []
    for _ in range(n):
        id_analista, nivel = rng.choice(analistas)
        categoria = rng.choices(base.categorias, weights=base.peso_categoria)[0]
        prioridade = rng.choices(base.prioridades, weights=base.peso_prioridade)[0]
        abertura = desde + timedelta(seconds=rng.randint(1, max(1, int(segundos))))
        status = rng.choices(base.STATUS, weights=STATUS_NOVO)[0]

        tempo_resposta = rng.randint(1, 12)
        fechamento = None
        tempo_resolucao = None
        if status == "Fechado":
            # resolucao rapida: so se cabe entre a abertura e "agora"
            horas = int((agora - abertura).total_seconds() // 3600)
            if horas >= 1 and rng.random() < 0.5:
                tempo_resolucao = rng.randint(1, horas)
                fechamento = abertura + timedelta(hours=tempo_resolucao)
            else:
                status = "Em andamento"
        sla_resp_ok = tempo_resposta <= base.sla_resposta[prioridade]
        sla_res_ok = None if tempo_resolucao is None \
            else tempo_resolucao <= base.sla_resolucao[prioridade]
        dados.append({
            "id_ticket": None, "id_analista": id_analista,
            "id_cliente": rng.choice(ids_clientes), "categoria": categoria,
            "prioridade": prioridade, "status": status, "data_abertura": abertura,
            "data_fechamento": fechamento, "tempo_resposta": tempo_resposta,
            "tempo_resolucao": tempo_resolucao, "sla_resposta_ok": sla_resp_ok,
            "sla_resolucao_ok": sla_res_ok,
        })
    dados.sort(key=lambda r: r["data_abertura"])
    for k, r in enumerate(dados):
        r["id_ticket"] = primeiro_id + k
    return dados


def evoluir_abertos(abertos, agora, rng):
    """abertos: lista de dicts com id_ticket, status ('Aberto'/'Em andamento'),
    prioridade (chave sem acento: baixa/media/alta/critica), data_abertura.
    Retorna lista de alteracoes: dicts com id_ticket, novo_status e, se fechou,
    data_fechamento, tempo_resolucao, sla_resolucao_ok."""
    mudancas = []
    for t in abertos:
        idade = max(0, (agora - t["data_abertura"]).days)
        p_fecha, p_and = chance(idade)
        if rng.random() < p_fecha:
            # fecha em algum momento das ultimas 24h, nunca antes da abertura
            fech = agora - timedelta(seconds=rng.randint(0, 86399))
            if fech <= t["data_abertura"]:
                fech = t["data_abertura"] + timedelta(hours=1)
            if fech > agora:
                continue
            horas = max(1, round((fech - t["data_abertura"]).total_seconds() / 3600))
            mudancas.append({
                "id_ticket": t["id_ticket"], "novo_status": "Fechado",
                "data_fechamento": fech, "tempo_resolucao": horas,
                "sla_resolucao_ok": horas <= t["sla_resolucao_horas"],
            })
        elif t["status"] == "Aberto" and rng.random() < p_and:
            mudancas.append({"id_ticket": t["id_ticket"], "novo_status": "Em andamento",
                             "data_fechamento": None, "tempo_resolucao": None,
                             "sla_resolucao_ok": None})
    return mudancas


# ------------------------------------------------------------------
# Banco
# ------------------------------------------------------------------
def main():
    executar = "--executar" in sys.argv
    agora = datetime.now().replace(microsecond=0)
    rng = random.Random()                       # sem semente: cada dia e diferente
    con = base.conectar()
    cur = con.cursor()

    col_fato = base.colunas_tabela(cur, "dw", "fato_chamados")
    col_cal = base.colunas_tabela(cur, "dw", "dim_calendario")
    if any(ident for nome, ident in col_fato if nome.lower() == "id_ticket"):
        raise RuntimeError("id_ticket e IDENTITY no banco; o script precisa de ajuste.")

    cur.execute("SELECT COUNT(*), MAX(id_ticket), MAX(data_abertura) FROM dw.fato_chamados")
    qtd, max_id, ultima = cur.fetchone()
    print(f"dw.fato_chamados hoje: {qtd:,} linhas | id max {max_id} | ultima abertura {ultima}")
    if ultima is None:
        raise RuntimeError("Tabela vazia: rode antes o gerar_dados_2025_2026.py.")
    if ultima > agora:
        raise RuntimeError(f"A ultima abertura ({ultima}) esta no futuro. Nada foi gravado.")

    cur.execute("SELECT id_analista, nivel FROM dw.dim_analista")
    analistas = []
    for ida, nivel in cur.fetchall():
        chave = next((k for k in base.performance
                      if base.sem_acento(k) == base.sem_acento(nivel)), None)
        if chave is None:
            raise RuntimeError(f"Nivel desconhecido no banco: {nivel}")
        analistas.append((ida, chave))
    cur.execute("SELECT id_cliente FROM dw.dim_cliente")
    ids_clientes = [r[0] for r in cur.fetchall()]

    mapa_cat = base.mapear_valores(cur, "categoria", base.categorias)
    mapa_pri = base.mapear_valores(cur, "prioridade", base.prioridades)
    mapa_sta = base.mapear_valores(cur, "status", base.STATUS)

    cur.execute("SELECT TOP 1 sla_resposta_ok FROM dw.fato_chamados WHERE sla_resposta_ok IS NOT NULL")
    sla_texto = isinstance(cur.fetchone()[0], str)
    conv_sla = (lambda b: None if b is None else ("True" if b else "False")) if sla_texto \
        else (lambda b: None if b is None else int(b))

    # --- calendario (garante datas ate o fim do ano) ---------------------
    nomes_cal = [n for n, _ in col_cal]
    cur.execute(f"SELECT {', '.join(nomes_cal)} FROM dw.dim_calendario")
    linhas_cal = [tuple(r) for r in cur.fetchall()]
    idx_id = [n.lower() for n in nomes_cal].index("id_data")
    idx_dt = [n.lower() for n in nomes_cal].index("data")
    como_data = lambda v: v.date() if isinstance(v, datetime) else v
    para_id = base.criar_id_data([(l[idx_id], como_data(l[idx_dt])) for l in linhas_cal[:500]])
    existentes = {como_data(l[idx_dt]) for l in linhas_cal}
    ate = date(agora.year + 1, 12, 31) if agora.month == 12 else date(agora.year, 12, 31)
    primeira = min(existentes)
    todas = [primeira + timedelta(days=i) for i in range((ate - primeira).days + 1)]
    faltando = [d for d in todas if d not in existentes]
    novas_cal = base.montar_calendario(faltando, linhas_cal, nomes_cal, para_id) if faltando else []

    # --- chamados novos ----------------------------------------------------
    novos = gerar_novos(analistas, ids_clientes, (max_id or 0) + 1, ultima, agora, rng)

    # --- chamados em aberto -> evolucao ----------------------------------
    cur.execute("SELECT id_ticket, status, prioridade, data_abertura FROM dw.fato_chamados "
                "WHERE status <> ?", mapa_sta["Fechado"])
    abertos = []
    for idt, st, pri, dab in cur.fetchall():
        chave_pri = next((p for p in base.prioridades
                          if base.sem_acento(p) == base.sem_acento(pri)), None)
        if chave_pri is None:
            continue
        abertos.append({
            "id_ticket": idt,
            "status": "Aberto" if base.sem_acento(st) == "aberto" else "Em andamento",
            "data_abertura": dab,
            "sla_resolucao_horas": base.sla_resolucao[chave_pri],
        })
    mudancas = evoluir_abertos(abertos, agora, rng)
    fechados = sum(1 for m in mudancas if m["novo_status"] == "Fechado")
    iniciados = len(mudancas) - fechados

    print(f"Novos chamados: {len(novos):,} | em aberto hoje: {len(abertos):,} -> "
          f"{fechados:,} fecham, {iniciados:,} passam a Em andamento | "
          f"calendario: {len(novas_cal)} datas novas")

    if not executar:
        print("\nPREVIA: nada foi gravado. Para gravar, rode de novo com --executar")
        con.close()
        return

    # --- gravar (uma transacao so) -----------------------------------------
    nomes_fato = [n for n, nao_grav in col_fato if not nao_grav]
    grav_cal = [n for n, nao_grav in col_cal if not nao_grav]
    linhas = []
    for r in novos:
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

    # so atualiza colunas que o SQL Server deixa gravar (colunas computadas,
    # como id_data_fechamento, o proprio banco recalcula)
    gravaveis = {n.lower() for n, nao_grav in col_fato if not nao_grav}
    campos_upd = [c for c in ("status", "data_fechamento", "tempo_resolucao",
                              "sla_resolucao_ok", "id_data_fechamento")
                  if c in gravaveis]
    if "status" not in campos_upd:
        raise RuntimeError("A coluna status nao pode ser atualizada. Nada foi gravado.")
    upd = []
    for m in mudancas:
        fech = m["data_fechamento"]
        valores = {
            "status": mapa_sta[m["novo_status"]],
            "data_fechamento": fech,
            "tempo_resolucao": m["tempo_resolucao"],
            "sla_resolucao_ok": conv_sla(m["sla_resolucao_ok"]),
            "id_data_fechamento": para_id(fech.date()) if fech else None,
        }
        upd.append(tuple(valores[c] for c in campos_upd) + (m["id_ticket"],))

    try:
        cur.fast_executemany = True
        if novas_cal:
            cur.executemany(
                f"INSERT INTO dw.dim_calendario ({', '.join(grav_cal)}) "
                f"VALUES ({', '.join('?' * len(grav_cal))})",
                [tuple(l[n] for n in grav_cal) for l in novas_cal])
        if linhas:
            cur.executemany(
                f"INSERT INTO dw.fato_chamados ({', '.join(nomes_fato)}) "
                f"VALUES ({', '.join('?' * len(nomes_fato))})", linhas)
        if upd:
            cur.executemany(
                f"UPDATE dw.fato_chamados SET {', '.join(c + ' = ?' for c in campos_upd)} "
                "WHERE id_ticket = ?", upd)
        con.commit()
    except Exception:
        con.rollback()
        print("ERRO: nada foi gravado (rollback).")
        raise

    cur.execute("SELECT COUNT(*), MAX(data_abertura) FROM dw.fato_chamados")
    total, ult = cur.fetchone()
    con.close()

    resultado = (f"RESULTADO;ok;novos={len(novos)};fechados={fechados};"
                 f"em_andamento={iniciados};total={total};ultima_abertura={ult}")
    os.makedirs("logs", exist_ok=True)
    with open(os.path.join("logs", "carga_diaria.log"), "a", encoding="utf-8") as f:
        f.write(f"{agora:%Y-%m-%d %H:%M:%S};{resultado}\n")
    print(f"\nOK! {total:,} linhas no banco (ultima abertura: {ult}).")
    print(resultado)


if __name__ == "__main__":
    main()
