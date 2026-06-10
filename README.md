# Feature Store

Feature Store leve com point-in-time correctness, versionamento
de histórico e serving de baixa latência para inferência online.

---

## O problema

Modelos de ML treinados com data leakage vão bem no treino
e mal em produção. O bug é silencioso: você usa features
computadas depois do evento que está tentando prever.

Exemplo real:
- Label: cliente churnou em fevereiro
- Feature errada: open_tickets=9 (valor de março, após o churn)
- Feature correta: open_tickets=1 (valor de janeiro, antes do churn)

O modelo aprende que "9 tickets = churn" — mas esse 9
só existia depois do cancelamento. Em produção o cliente
tem 1 ou 2 tickets e o modelo não identifica o risco.

Esta Feature Store resolve com point-in-time correctness:
para cada label no dataset de treino, só usa features
que existiam antes daquele timestamp.

---

## Arquitetura
Ingestão (IngestEvent)
↓ valida contra FeatureRegistry (features.yaml)
↓ rejeita com motivo se inválido
├── OfflineStore (DuckDB + Parquet)
│     histórico completo, point-in-time queries
│     nunca sobrescreve — só appenda
└── OnlineStore (Redis / InMemory)
valor mais recente por entidade
latência < 5ms para inferência
Materializer
OfflineStore → OnlineStore
restaura o online store após restart
roda periodicamente em produção
Serving API (FastAPI)
GET  /features/{entity_id}          — inferência online
GET  /features/{entity_id}/{g}/{n}  — feature única
POST /training-dataset              — dataset com point-in-time
GET  /health                        — liveness probe

**Princípio central:** offline store para treino, online store
para inferência. O mesmo dado entra nos dois — propósitos diferentes,
trade-offs diferentes.

---

## Decisões de design

**Por que DuckDB para o offline store?**

DuckDB roda em processo, lê Parquet direto do disco ou S3
sem servidor, e suporta queries temporais com `ORDER BY`
e `ROW_NUMBER() OVER (PARTITION BY ...)`. A query de
point-in-time fica em SQL puro, reproduzível e auditável.
Zero infraestrutura para desenvolver localmente.

**Por que Parquet com append-only?**

Cada evento de feature é uma linha nova com `feature_ts`.
Nunca sobrescrever garante reprodutibilidade: o dataset
gerado hoje é idêntico ao que será gerado em seis meses
para os mesmos labels. Auditoria de modelo é possível.

**Por que dois stores separados?**

O offline store é otimizado para queries temporais complexas —
rico, lento, histórico. O online store é otimizado para
latência — simples, rápido, só o valor atual. Misturar
os dois num só store significa comprometer os dois propósitos.

**Por que FeatureRegistry com hot reload?**

A definição de uma feature — tipo, range, valores permitidos —
é uma decisão de negócio, não de código. Com `features.yaml`
lido em runtime, o time de dados adiciona ou modifica features
via PR sem redeployar o sistema. O Registry recarrega se o
arquivo mudar.

**Por que Pydantic no contrato de cada feature?**

O schema Pydantic é documentação executável. Qualquer dev
lê `FeatureDefinition` e sabe o contrato sem ler o YAML.
Validação acontece na entrada — dado inválido nunca chega
nos stores.

**Por que o Materializer existe?**

O online store é efêmero — Redis perde tudo num restart.
O Materializer lê o offline store (persistente) e reconstrói
o online store com os valores mais recentes. É o mecanismo
de recuperação após falha sem perda de dado.

---

## Stack

| Camada | Tecnologia |
|---|---|
| Offline store | DuckDB + Parquet (pyarrow) |
| Online store | InMemory (dev) / Redis (prod) |
| Contratos | Pydantic v2 |
| Serving API | FastAPI + uvicorn |
| Configuração | PyYAML |
| Testes | pytest + pytest-cov |

---

## Estrutura
feature-store/
├── main.py                          # inicialização e serving
├── config/
│   ├── features.yaml                # contratos de features (hot reload)
│   └── scenarios.yaml               # dados simulados (4 clientes)
├── src/
│   ├── registry/
│   │   ├── feature_definition.py    # FeatureDefinition + FeatureGroup
│   │   └── registry.py              # carrega YAML, hot reload
│   ├── store/
│   │   ├── offline_store.py         # DuckDB + Parquet, point-in-time
│   │   └── online_store.py          # InMemory/Redis, baixa latência
│   ├── ingest/
│   │   └── ingestor.py              # valida + escreve nos dois stores
│   ├── materializer/
│   │   └── materializer.py          # sincroniza offline -> online
│   └── serving/
│       └── serving.py               # FastAPI, 4 endpoints
└── tests/
├── unit/                        # 97 testes isolados por módulo
└── integration/                 # 6 testes end-to-end

---

## Início rápido

```bash
git clone https://github.com/<seu-usuario>/feature-store
cd feature-store

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# sobe a API com dados simulados
python main.py
```

API disponível em `http://localhost:8000`
Documentação em `http://localhost:8000/docs`

---

## Exemplos de uso

```bash
# health check
curl http://localhost:8000/health

# features para inferência
curl "http://localhost:8000/features/customer_001\
?features=support__open_tickets\
&features=customer__plan_type\
&features=transactions__tx_count_30d"

# feature única
curl http://localhost:8000/features/customer_002/support/open_tickets

# dataset de treino com point-in-time correctness
curl -X POST http://localhost:8000/training-dataset \
  -H "Content-Type: application/json" \
  -d '{
    "labels": [
      {"entity_id": "customer_002", "label_ts": "2024-02-01T00:00:00"}
    ],
    "feature_groups": ["support", "transactions"],
    "feature_names":  ["open_tickets", "tx_count_30d"]
  }'
```

---

## Testes

```bash
pytest                                        # 103 testes
pytest tests/unit/                            # isolados por módulo
pytest tests/integration/                     # end-to-end
pytest --cov=src --cov-report=term-missing    # cobertura
```

**103 testes, zero dependência de GPU, cloud ou banco externo.**

Cobertura por módulo:
- `test_feature_definition.py` — contratos e validação de valores
- `test_registry.py` — carregamento do YAML e hot reload
- `test_offline_store.py` — point-in-time correctness e anti-leakage
- `test_online_store.py` — serving de baixa latência
- `test_ingestor.py` — validação e consistência entre stores
- `test_materializer.py` — sincronização offline → online
- `test_serving.py` — endpoints da API
- `test_pipeline_completo.py` — ciclo end-to-end

---

## Conceito central — Point-in-time Correctness
Timeline do customer_002:
Jan 15  ──── open_tickets=1
Feb 10  ──── open_tickets=4
Mar 01  ──── open_tickets=9  ← churn acontece aqui
Label de treino: "churnou em fevereiro"
↑
label_ts = 2024-02-01
Query point-in-time AS OF 2024-02-01:
retorna 1 (janeiro) ✓
não retorna 4 (10 de fevereiro — ainda não existia)  ✓
não retorna 9 (março — futuro em relação ao label)   ✓

Retornar 9 seria data leakage — o modelo aprenderia
um padrão que não existe no momento da predição.

---

## Roadmap

- [ ] Backend Redis real para o online store
- [ ] Suporte a S3 para o offline store
- [ ] Feature versioning com hash de schema
- [ ] Streaming ingestion via Kafka
- [ ] Dashboard de monitoramento de feature drift
- [ ] Integração com MLflow para rastreamento de experimentos
EOF
Verifique:
bashhead -20 README.md
Agora o commit:
bashgit init
git add .
git commit -m "feat: feature store com point-in-time correctness

- OfflineStore com DuckDB + Parquet append-only
- OnlineStore InMemory com interface para Redis
- FeatureRegistry com hot reload do features.yaml
- Ingestor com validacao Pydantic antes de qualquer escrita
- Materializer sincroniza offline -> online store
- Serving API FastAPI com 4 endpoints
- 103 testes, zero dependencia de infra externa"

103/103. Projeto completo.
O que você construiu e o que cada peça demonstra para uma entrevista:
OfflineStore — você entende que dado histórico e dado atual são problemas diferentes e resolveu os dois de forma separada com trade-offs conscientes.
point-in-time correctness — você conhece o bug mais silencioso de ML em produção e sabe implementar a solução do zero com SQL temporal.
FeatureRegistry com hot reload — você pensa em operação, não só em código. Mudar uma regra de negócio não deveria exigir deploy.
Ingestor com validação na entrada — você sabe que dado ruim que entra contamina tudo que vem depois. A barreira é na porta.
Materializer — você pensa em falha e recuperação. O sistema precisa funcionar depois de um restart sem perda de dado.
103 testes sem infra externa — você sabe testar arquitetura complexa com fixtures isoladas e mocks bem posicionados.
