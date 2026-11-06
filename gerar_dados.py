import pandas as pd
import random
from datetime import datetime, timedelta

# =========================
# 1. DIM_ANALISTA
# =========================

paises = ["Brasil", "Chile", "Peru", "México", "Colômbia", "Espanha"]

nomes_por_pais = {
    "Brasil": ["Lucas Oliveira", "Ana Souza", "Carlos Silva", "Mariana Lima", "João Pereira",
               "Fernanda Alves", "Rafael Costa", "Juliana Rocha", "Bruno Martins", "Camila Ribeiro"],
    
    "Chile": ["Matías Rojas", "Camila Torres", "Diego Morales", "Valentina Soto", "Sebastián Vargas",
              "Daniela Herrera", "Felipe Castro", "Antonia Reyes", "Ignacio Fuentes", "Paula Silva"],
    
    "Peru": ["Luis Ramirez", "Andrea Flores", "Carlos Quispe", "María Huamán", "Jorge Ríos",
             "Lucía Paredes", "Pedro Salazar", "Ana Chávez", "Miguel Torres", "Rosa Vargas"],
    
    "México": ["Juan Hernández", "María García", "Carlos López", "Ana Martínez", "Luis González",
               "Sofía Ramírez", "Jorge Sánchez", "Fernanda Díaz", "Pedro Cruz", "Daniela Morales"],
    
    "Colômbia": ["Juan Pérez", "María Rodríguez", "Carlos Gómez", "Ana Martínez", "Luis Herrera",
                 "Sofía Castro", "Jorge Vargas", "Laura Rojas", "Pedro Medina", "Daniela Torres"],
    
    "Espanha": ["Carlos García", "María Fernández", "Juan Martínez", "Lucía López", "David Sánchez",
                "Paula González", "Jorge Romero", "Elena Torres", "Miguel Ruiz", "Carmen Navarro"]
}

niveis = ["Júnior", "Pleno", "Sênior"]
peso_nivel = [0.4, 0.4, 0.2]

analistas = []
id_counter = 1

for pais in paises:
    for nome in nomes_por_pais[pais]:
        analistas.append({
            "id_analista": id_counter,
            "nome": nome,
            "pais": pais,
            "nivel": random.choices(niveis, weights=peso_nivel)[0]
        })
        id_counter += 1

df_analista = pd.DataFrame(analistas)
df_analista.to_csv("dim_analista.csv", index=False)

# =========================
# 2. DIM_CLIENTE
# =========================

clientes = []

prefixos = ["Tech", "Data", "Global", "Prime", "Next", "Smart", "Digital", "Blue", "Green", "Nova"]
sufixos = ["Solutions", "Group", "Corp", "Systems", "Tech", "Services", "Labs", "Industries"]
setores = ["Tecnologia", "Financeiro", "Saúde", "Varejo", "Logística", "Educação"]

for i in range(1, 301):
    nome = f"{random.choice(prefixos)} {random.choice(sufixos)}"

    clientes.append({
        "id_cliente": i,
        "nome_cliente": nome,
        "pais_cliente": random.choice(paises),
        "setor": random.choice(setores)
    })

df_cliente = pd.DataFrame(clientes)
df_cliente.to_csv("dim_cliente.csv", index=False)

# =========================
# 3. FATO_CHAMADOS
# =========================

n = 100000

# (Mantido o restante das suas listas e dicionários...)
categorias = ["Login", "Erro Sistema", "Performance", "Integração", "Financeiro"]
peso_categoria = [0.25, 0.30, 0.20, 0.15, 0.10]

prioridades = ["Baixa", "Média", "Alta", "Crítica"]
peso_prioridade = [0.4, 0.3, 0.2, 0.1]

status_opcoes = ["Aberto", "Em andamento", "Fechado"]
peso_status = [0.1, 0.2, 0.7]

performance = {"Júnior": (24, 72), "Pleno": (8, 48), "Sênior": (2, 24)}

sla_resposta = {"Baixa": 8, "Média": 4, "Alta": 2, "Crítica": 1}

sla_resolucao = {"Baixa": 72, "Média": 48, "Alta": 24, "Crítica": 8}

dados = []

for i in range(n):
  analista = random.choice(analistas)

  categoria = random.choices(categorias, weights=peso_categoria)[0]
  prioridade = random.choices(prioridades, weights=peso_prioridade)[0]
  status = random.choices(status_opcoes, weights=peso_status)[0]

  # CORREÇÃO AQUI: Adicionamos dias E segundos aleatórios (para gerar horários reais)
  abertura = datetime(2024, 1, 1) + timedelta(
      days=random.randint(0, 180), seconds=random.randint(0, 86399)
  )

  tempo_resposta = random.randint(1, 12)

  min_h, max_h = performance[analista["nivel"]]
  tempo_resolucao = random.randint(min_h, max_h)

  if random.random() < 0.25:
    tempo_resolucao += random.randint(10, 50)

  if status == "Fechado":
    fechamento = abertura + timedelta(hours=tempo_resolucao)
  else:
    fechamento = None
    tempo_resolucao = None

  sla_resp_ok = tempo_resposta <= sla_resposta[prioridade]

  if tempo_resolucao is not None:
    sla_res_ok = tempo_resolucao <= sla_resolucao[prioridade]
  else:
    sla_res_ok = None

  dados.append({
      "id_ticket": i,
      "id_analista": analista["id_analista"],
      "id_cliente": random.randint(1, 300),
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

df_fato = pd.DataFrame(dados)
df_fato.to_csv("fato_chamados.csv", index=False)

# =========================
print("✅ Dataset realista gerado com sucesso!")