# PROJECT_MEMORY.md — Controle Financeiro com Agentes de IA

> Arquivo de memória persistente do projeto. Atualizado ao longo do desenvolvimento.
> Use este arquivo para retomar o contexto em novas sessões.
>
> **Última atualização:** 2026-05-13
> **Status atual:** MVP 2 em andamento — pendente: testes automatizados (DT-007) e retry OpenAI (DT-006)

---

## Visão Geral do Projeto

Sistema pessoal de controle financeiro e investimentos baseado em Agentes de IA.
O usuário registra gastos em linguagem natural e consulta seu histórico financeiro via chat.

**Origem:** Projeto de conclusão do curso DSA 4.0 (Data Science Academy) — módulo de Agentes de IA.
**Destino real:** Sistema de uso diário + portfólio público. Não é só exercício acadêmico.

---

## Objetivos

### Objetivo primário
Controle financeiro pessoal via linguagem natural, com registro inteligente e consultas analíticas.

### Objetivo secundário
Aprendizado prático de: LangGraph, MCP (Model Context Protocol), RAG, observabilidade com LangSmith,
multi-agentes, guardrails e arquitetura de sistemas de IA.

### Exemplos de interação esperada
```
Usuário: "Gastei 55 reais no almoço"
Agente:  "Registrei: R$ 55,00 · Alimentação · dinheiro · hoje ✓"

Usuário: "Quanto gastei com alimentação esse mês?"
Agente:  "Você gastou R$ 320,50 com Alimentação em maio (7 lançamentos)."

Usuário: "Qual categoria teve maior gasto?"
Agente:  "Transporte liderou com R$ 480,00, seguido de Alimentação com R$ 320,50."
```

---

## Stack Tecnológica

| Componente | Tecnologia | Versão instalada | Motivo da escolha |
|---|---|---|---|
| Linguagem | Python | 3.12 | Ecossistema de IA, já usado no curso |
| LLM | OpenAI GPT | gpt-4o-mini (default) | Custo/benefício para uso diário |
| Orquestrador | LangGraph | 1.2.0 | Curso, flexibilidade, robusto |
| Protocolo agente | MCP (FastMCP) | 3.2.4 | Padrão do curso, separação clara servidor/cliente |
| Adaptador MCP | langchain-mcp-adapters | 0.2.2 | Bridge LangGraph ↔ MCP |
| Validação | Pydantic v2 | 2.13.4 | Tipagem forte, ótima DX |
| Banco de dados | SQLite | built-in | Simples, arquivo local, zero infra |
| Configuração | pydantic-settings | 2.14.1 | Centraliza env vars com tipagem |
| Observabilidade | LangSmith | 0.8.3 | Auto-instrumentação LangGraph |
| Env vars | python-dotenv | 1.2.2 | Padrão do curso |

**Nota:** Versões planejadas no design (LangGraph 0.4.7, FastMCP 1.9.1) foram substituídas pelas mais recentes disponíveis. API compatível — único ajuste necessário foi `await client.get_tools()` (virou coroutine em langchain-mcp-adapters 0.2.2).

### Variáveis de ambiente necessárias (`.env`)
```env
# LLM
OPENAI_API_KEY=sk-...

# Observabilidade
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=financas-ia-mvp1

# Opcional — sobrescreve defaults do config.py
# OPENAI_MODEL=gpt-4o-mini
# DB_PATH=./financas.db
# MAX_EXPENSE_AMOUNT=100000
```

---

## Arquitetura Atual (MVP 2)

### Padrão arquitetural
```
┌─────────────────────────────────────────────────────────┐
│                      main.py (CLI)                      │
│   AsyncSqliteSaver (checkpoints.db) — sessão persiste   │
└────────────────────────┬────────────────────────────────┘
                         │ ainvoke() / Command(resume=...)
┌────────────────────────▼────────────────────────────────┐
│                  agent/graph.py                         │
│              LangGraph StateGraph                       │
│                                                         │
│  START → [agent_node]                                   │
│               │                                         │
│         should_call_tools                               │
│          ├──→ [guardrail_node] → END   (bulk delete)    │
│          ├──→ [confirm_node]           (destrutivo)     │
│          │       └─ interrupt() HITL                    │
│          │       └─ Command(goto=tool_node|END)         │
│          └──→ [tool_node] → [agent_node] → ...         │
└────────────────────────┬────────────────────────────────┘
                         │ stdio subprocess
┌────────────────────────▼────────────────────────────────┐
│               mcp_server/server.py                      │
│                 FastMCP (stdio)                         │
│                                                         │
│  record_expense | query_expenses | get_summary          │
│  list_categories | create_category                      │
│  list_payment_methods | create_payment_method           │
│  find_expense_candidates | delete_expense | update_expense │
└────────────────────────┬────────────────────────────────┘
                         │ sqlite3
┌────────────────────────▼────────────────────────────────┐
│                   financas.db (SQLite)                  │
│  expenses · categories · payment_methods · audit_log    │
└─────────────────────────────────────────────────────────┘
```

### Camadas e responsabilidades

| Camada | Arquivo | Responsabilidade |
|---|---|---|
| Entrada | `main.py` | Loop CLI, AsyncSqliteSaver, _invoke() com loop de interrupt |
| Orquestração | `agent/graph.py` | StateGraph, guardrail_node, confirm_node, trim_messages |
| Inteligência | `agent/prompts.py` | System prompt, instruções de extração, HITL rules |
| Protocolo | `mcp_server/server.py` | 10 tools MCP, validação, hash, soft delete, audit_log |
| Dados | `database/setup.py` | Schema SQLite, seed categorias e métodos |
| Modelos | `models/schemas.py` | Pydantic: ExpenseCreate (amount, date), ExpenseRecord |
| Config | `config.py` | Settings: OpenAI, db_path, checkpoints_path, max_context_messages |
| Migrations | `migrations/versions/` | Alembic — autoridade final sobre schema |
| Diagramas | `diagrams/` | PlantUML — arquitetura MVP 2 + fluxo excluir gasto |

**Regra de ouro:** O MCP Server é um banco de dados inteligente (sem lógica de negócio complexa). O LangGraph é o cérebro (toda lógica vive aqui). Não inverter essa relação.

---

## Estrutura de Diretórios

```
financas-ia/
│
├── .env                        # Chaves de API (não versionar)
├── .gitignore
├── requirements.txt
├── PROJECT_MEMORY.md           # Este arquivo
├── alembic.ini                 # Configuração Alembic
│
├── config.py                   # Settings centralizadas (pydantic-settings)
│
├── database/
│   ├── __init__.py
│   └── setup.py                # Schema SQLite + seed categorias e payment_methods
│
├── models/
│   ├── __init__.py
│   └── schemas.py              # Pydantic: ExpenseCreate (validação amount + date)
│
├── mcp_server/
│   ├── __init__.py
│   └── server.py               # FastMCP (stdio) — 10 tools
│
├── agent/
│   ├── __init__.py
│   ├── prompts.py              # System prompt (HITL rules, guardrails, categorias, métodos)
│   └── graph.py                # LangGraph — 4 nós: agent, tool, guardrail, confirm
│
├── migrations/
│   ├── env.py                  # Alembic env (usa config.py para db_path)
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_add_is_system_to_categories.py
│       └── 0003_add_payment_methods.py
│
├── diagrams/
│   ├── arquitetura_mvp2.puml   # 6 diagramas PlantUML — arquitetura geral MVP 2
│   └── atividades_excluir_gasto.puml  # Diagrama de atividades — caso de uso delete
│
└── main.py                     # Entry point CLI — AsyncSqliteSaver, _invoke() com interrupt loop
```

---

## Banco de Dados

### Schema (SQLite — estado atual após migrations 0001–0003)

```sql
CREATE TABLE categories (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    name        TEXT      NOT NULL UNIQUE,
    is_system   INTEGER   NOT NULL DEFAULT 0,  -- 1=sistema, 0=usuário
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE payment_methods (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    name        TEXT      NOT NULL UNIQUE,
    is_system   INTEGER   NOT NULL DEFAULT 0,  -- 1=sistema, 0=usuário
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE expenses (
    id           INTEGER   PRIMARY KEY AUTOINCREMENT,
    amount       REAL      NOT NULL CHECK(amount > 0 AND amount < 100000),
    description  TEXT      NOT NULL,
    category     TEXT      NOT NULL REFERENCES categories(name),
    method       TEXT      NOT NULL DEFAULT 'dinheiro',  -- validado via payment_methods
    expense_date DATE      NOT NULL DEFAULT CURRENT_DATE,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hash         TEXT      NOT NULL UNIQUE,
    deleted_at   TIMESTAMP DEFAULT NULL  -- soft delete
);

CREATE TABLE audit_log (
    id          INTEGER   PRIMARY KEY AUTOINCREMENT,
    operation   TEXT      NOT NULL CHECK(operation IN ('delete', 'update')),
    expense_id  INTEGER   NOT NULL,
    old_data    TEXT      NOT NULL,  -- JSON snapshot antes da operação
    new_data    TEXT      DEFAULT NULL,  -- JSON snapshot depois (só para update)
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Seeds
```
Categorias (is_system=1): Alimentação | Transporte | Moradia | Saúde | Lazer
                          Educação | Vestuário | Tecnologia | Serviços | Outros
Métodos (is_system=1):    dinheiro | crédito | débito | pix | transferência
```

### Decisões de design
- `category` e `method` são `TEXT` (não FK integer) → queries sem JOIN, mais legível
- `hash UNIQUE` → banco rejeita duplicata automaticamente, zero lógica extra
- `is_system=1` protege seeds — user não pode sobrescrever via agente
- `CHECK(method IN (...))` removido em 0003 — validação dinâmica via `payment_methods`
- `audit_log` nunca exposto como MCP tool — imutável, só para rastreabilidade
- Alembic é autoridade final sobre schema (main.py chama `upgrade head` no startup)

---

## Tools MCP

### `record_expense`
- **Operação:** INSERT com deduplicação via hash
- **Input:** amount, description, category, method, expense_date
- **Lógica interna:**
  - Pydantic valida todos os campos
  - Computa `hash = sha256(f"{amount:.2f}|{description_normalizada}|{date}")`
  - Hash da descrição: lowercase + strip + remove acentos + colapsa espaços
  - INSERT → retorna expense criado ou erro de duplicata
- **Output:** JSON com expense ou `{"error": "...", "tipo": "duplicata|invalido"}`

### `query_expenses`
- **Operação:** SELECT com filtros opcionais
- **Input:** start_date?, end_date?, category?, method?
- **Output:** lista de expenses

### `get_summary`
- **Operação:** SELECT + GROUP BY
- **Input:** start_date, end_date, group_by ('category'|'method'|'day'|'month')
- **Output:** dict com totais por dimensão + total geral

### `list_categories`
- **Operação:** SELECT all categories
- **Input:** nenhum
- **Output:** lista de strings com os nomes

### `list_payment_methods`
- **Operação:** SELECT all payment_methods
- **Input:** nenhum
- **Output:** lista de strings com os nomes

### `create_payment_method`
- **Operação:** INSERT em payment_methods (is_system=0)
- **Input:** name (str), confirmed (bool)
- **Lógica:** rejeita `confirmed=False`; normaliza lowercase; valida 2–30 chars, só letras/espaços/hífens; verifica duplicata case-insensitive
- **Output:** `{created: True, name}` ou `{error, tipo}`

### `find_expense_candidates`
- **Operação:** SELECT com lógica de "data mais recente"
- **Input:** keyword, expense_date? (YYYY-MM-DD, opcional)
- **Lógica interna:**
  - Filtragem em Python com unicodedata (NFD, remove acentos) — suporte correto a Unicode
  - Com `expense_date`: filtra por data exata informada
  - Sem `expense_date`: `MAX(expense_date)` entre os registros com o keyword
  - Só retorna registros `WHERE deleted_at IS NULL`
- **Output:** `{keyword, date_searched, total_found, records[]}`

### `delete_expense`
- **Operação:** Soft delete — `UPDATE SET deleted_at = CURRENT_TIMESTAMP`
- **Input:** expense_id (int), confirmed (bool)
- **Lógica:** rejeita `confirmed=False`; busca registro ativo; grava JSON snapshot em `audit_log`; retorna registro deletado
- **Output:** `{deleted: True, expense_id, record}` ou `{error, tipo}`

### `update_expense`
- **Operação:** UPDATE parcial com recálculo de hash
- **Input:** expense_id, confirmed, + campos opcionais (amount, description, category, method, expense_date)
- **Lógica:** rejeita `confirmed=False`; recalcula hash se amount/description/date mudar; registra before/after em `audit_log`; valida category e method contra tabelas dinâmicas
- **Output:** `{updated: True, expense_id, old, new}` ou `{error, tipo}`

### O que deliberadamente NÃO existe no servidor MCP
- `delete_by_category`, `delete_by_period`, `delete_all` — exclusão em massa impossível por design
- `bulk_import` — MVP 2+
- Lógica de classificação — pertence ao agente
- Leitura direta do `audit_log` — não exposto como tool

---

## Fluxo LangGraph

### Grafo (MVP 2)
```
START → agent_node
           │
     should_call_tools (condicional)
      ├── len(delete_expense) > 1  → guardrail_node → END
      ├── any tool in DESTRUCTIVE_TOOLS → confirm_node
      │       └── interrupt() HITL
      │           ├── confirmado → Command(update messages, goto=tool_node)
      │           └── cancelado → Command(stubs + cancel msg, goto=END)
      ├── tool_calls presentes (seguro) → tool_node → agent_node
      └── sem tool_calls → END
```

### Estado
```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```

### Nós
- **`agent_node`:** `trim_messages` (max 40, list-level lambda) + `[SystemMessage] + trimmed` → `ainvoke LLM`
- **`tool_node`:** `ToolNode(tools=tools)` — executa tools MCP
- **`guardrail_node`:** detecta múltiplos `delete_expense` em paralelo; injeta ToolMessage stubs + AIMessage de bloqueio
- **`confirm_node`:** `interrupt()` síncrono — pausa o grafo; aguarda `Command(resume=resposta)` do usuário; patcha AIMessage com `confirmed=True` se confirmado; `add_messages` reducer substitui a mensagem pelo mesmo `id`

### Checkpointer / Memória
- `AsyncSqliteSaver.from_conn_string(settings.checkpoints_path)` → `checkpoints.db`
- `thread_id = "default"` — sessão única, contexto persiste entre reinicializações
- `trim_messages`: `max_tokens=40`, `strategy="last"`, `token_counter=lambda msgs: len(msgs)` (list-level — IMPORTANTE: lambda por msg retorna todos)
- `include_system=False`, `start_on="human"` — SystemMessage re-injetado a cada turno

### MCP Transport
- **`stdio`** — servidor é subprocesso do cliente
- Configuração: `{"command": "python", "args": ["mcp_server/server.py"], "transport": "stdio"}`
- Zero setup extra — sem `uvicorn`, sem porta, sem segundo terminal

---

## Guardrails

### Arquitetura de defesa em profundidade (4 camadas)

```
Usuário
  │
  ▼
[Layer 1 — System Prompt]  ← instrução comportamental (mais fraco — LLM pode ignorar)
  │
  ▼
[Layer 2 — LangGraph guardrail_node]  ← intercepta tool_calls antes do tool_node (forte)
  │
  ▼
[Layer 3 — MCP Server]  ← validação técnica independente (última linha ativa)
  │
  ▼
[Layer 4 — SQLite soft delete + audit_log]  ← recuperação (defesa passiva)
```

### Layer 1 — System Prompt (instrução comportamental)
```
✓ Proibição explícita de exclusões em massa (com exemplos de frases bloqueadas)
✓ Proteção contra prompt injection (lista de padrões a recusar)
✓ HITL conversacional: 4 passos obrigatórios para delete/update
✓ Regra confirmed=True: só válida se confirmação estiver na mensagem ATUAL
✓ Para valores > R$ 1.000: mostrar resumo extraído e perguntar "Confirmar?"
```

### Layer 2 — LangGraph guardrail_node (interceptação arquitetural)
```
✓ Detecta múltiplos delete_expense em um único turno (parallel tool calls)
✓ Bloqueia ANTES de executar qualquer deleção
✓ Injeta ToolMessage stubs (mantém chain de mensagens consistente para turnos futuros)
✓ Retorna mensagem de segurança padrão ao usuário
✓ Rota: agent_node → guardrail_node → END (bypassa tool_node completamente)
```

### Layer 3 — MCP Server (validação técnica)
```
✓ delete_expense aceita APENAS expense_id: int (não aceita filtros, listas ou ranges)
✓ confirmed=False → rejeita imediatamente (sem toque no banco)
✓ Verifica existência do registro antes de operar
✓ Valida amount, expense_date, category, method independentemente do agente
✓ hash UNIQUE: banco rejeita duplicata (IntegrityError tratado)
```

### Layer 4 — SQLite soft delete + audit_log (recuperação)
```
✓ deleted_at TIMESTAMP NULL: dado nunca destruído fisicamente
✓ audit_log: snapshot before/after para toda mutação
✓ Recuperação manual possível via UPDATE SET deleted_at = NULL
✓ audit_log nunca exposto como MCP tool
```

### Layer 3 — confirm_node interrupt() HITL (MVP 2 — implementado)
```
✓ Toda operação destrutiva (delete_expense, update_expense) passa por confirm_node
✓ interrupt() pausa o grafo — estado salvo no AsyncSqliteSaver (checkpoints.db)
✓ Mostra ao usuário: ID, valor, descrição, categoria, método, data
✓ Só retoma via Command(resume=resposta)
✓ Confirmações válidas: "sim", "confirmo", "yes", "pode", "confirmar"
✓ Cancelamento: injeta stubs + mensagem "Operação cancelada."
✓ Patch de confirmed=True: AIMessage recriada com mesmo id → add_messages faz replace
```

### O que NÃO existe nos guardrails ainda
- Rate limiting → MVP 3+
- Teste automatizado de guardrails → DT-007 (próxima prioridade)

---

## Fluxo MCP (stdio)

```
main.py
  └─▶ MultiServerMCPClient({"financas": {"command": "python", ...}})
        └─▶ async with client.session("financas") as session:
              └─▶ tools = await load_mcp_tools(session)
                    └─▶ LangGraph bind_tools(tools)
                          └─▶ ToolNode executa tool
                                └─▶ MCP client serializa chamada → subprocess stdin
                                      └─▶ server.py recebe, executa, retorna via stdout
```

O `MultiServerMCPClient` gerencia o ciclo de vida do subprocesso. O servidor é iniciado automaticamente quando `client.session()` é aberto e encerrado quando o contexto fecha.

---

## Agentes

### MVP 2 — Agente Único ReAct (atual)
- **Nome:** Assistente Financeiro Pessoal
- **Modelo:** gpt-4o-mini (configurável via `OPENAI_MODEL`)
- **Tipo:** ReAct (Reasoning + Acting) via LangGraph
- **Tools disponíveis:** 10 tools MCP
- **Memória:** AsyncSqliteSaver (checkpoints.db) — persiste entre sessões
- **Guardrails:** guardrail_node (bulk delete) + confirm_node (interrupt HITL)

### Agentes futuros (MVP 3+)
- Agente Extrator de Entidades (especialista em parsing de linguagem natural)
- Agente Analista Financeiro (especialista em consultas e insights)
- Roteador (direciona para o agente correto)

---

## Estratégia de Observabilidade

### MVP 1 — LangSmith auto-tracing
Nenhum código de instrumentação necessário. Ativado via env vars.

**O que é capturado automaticamente:**
- Cada invocação do grafo (input/output completo)
- Execução de cada nó (agent_node, tool_node) com latência
- Chamadas LLM com tokens consumidos (prompt + completion)
- Tool calls com parâmetros e resultados
- Erros e exceções com stack trace

**Projeto LangSmith:** `financas-ia-mvp1`
**Como acessar:** https://smith.langchain.com → projeto `financas-ia-mvp1`

### Logging local
- `logging` padrão Python
- Nível INFO para operações normais
- Nível WARNING para tentativas de duplicata
- Nível ERROR para falhas de validação

### MVP 2+ — métricas customizadas
- Taxa de classificação incorreta (usuário corrige categoria)
- Distribuição de gastos por categoria ao longo do tempo
- Latência média de registro vs. consulta

---

## Estratégia de Memória

### MVP 1
- `MemorySaver` in-memory — contexto perdido ao reiniciar

### MVP 2 (implementado)
- `AsyncSqliteSaver` → `checkpoints.db` (arquivo separado de `financas.db`)
- `thread_id = "default"` fixo — única sessão, histórico acumulado entre execuções
- `trim_messages(max_tokens=40, strategy="last")` evita contexto crescente
  - `token_counter=lambda msgs: len(msgs)` — conta mensagens, não tokens
  - `start_on="human"` garante que o contexto sempre começa por mensagem humana
- Implementação: `main.py:71` — `async with AsyncSqliteSaver.from_conn_string(...) as checkpointer`

### MVP 3+ (planejado)
- Summarização periódica em vez de truncagem simples
- Memória semântica com embeddings (busca por contexto relevante)

---

## Decisões Arquiteturais

### DA-001: Agente único no MVP 1
- **Decisão:** Um único agente ReAct faz tudo (extração + classificação + persistência + consulta)
- **Alternativa rejeitada:** Multi-agente com Extrator + Registrador
- **Motivo:** Overengineering para MVP. Aprender LangGraph com um grafo bem estruturado já ensina todos os conceitos essenciais
- **Revisão:** MVP 2 quando precisar de roteamento por intent

### DA-002: MCP stdio no MVP 1
- **Decisão:** Transport `stdio` (servidor como subprocesso)
- **Alternativa rejeitada:** `streamable-http` (requer uvicorn separado)
- **Motivo:** Zero setup, zero debugging de porta/conexão. Curso já mostrou streamable-http — agora aprender o fluxo, não a infra
- **Revisão:** MVP 3+ quando precisar de servidor compartilhado ou API REST

### DA-003: category como TEXT REFERENCES
- **Decisão:** Coluna `category TEXT REFERENCES categories(name)`, não FK com INTEGER
- **Alternativa rejeitada:** `category_id INTEGER FOREIGN KEY`
- **Motivo:** Queries de análise ficam legíveis sem JOIN. Integridade garantida pelo Pydantic antes do INSERT. Em SQLite, FK enforcement precisa de `PRAGMA foreign_keys=ON` a cada conexão — risco de bug silencioso
- **Trade-off:** Redundância mínima de dado (nome repetido nas linhas) — aceitável para volume de controle pessoal

### DA-004: Hash interno ao servidor MCP
- **Decisão:** Hash SHA256 computado dentro de `record_expense` no servidor
- **Alternativa rejeitada:** Agente envia o hash pronto
- **Motivo:** Agente não deve conhecer detalhes de implementação de deduplicação. Normalização da descrição fica centralizada em um lugar só

### DA-005: Sem HITL real no MVP 1
- **Decisão:** Confirmação de valores altos implementada via system prompt (instrução comportamental), não via `interrupt()` do LangGraph
- **Alternativa rejeitada:** `interrupt()` + `Command(resume=...)` do LangGraph
- **Motivo:** HITL real requer checkpointer externo persistente. `MemorySaver` in-memory não sobrevive a reinicializações — implementação incompleta criaria falsa sensação de segurança
- **Revisão:** MVP 2 com `SqliteSaver` como checkpointer

### DA-006: Sem migrations no MVP 1
- **Decisão:** `CREATE TABLE IF NOT EXISTS` direto no `setup.py`
- **Alternativa rejeitada:** Alembic desde o início
- **Motivo:** Alembic adiciona complexidade que não se justifica com um schema estável no MVP 1
- **Revisão:** Quando o schema precisar evoluir pela primeira vez (provável no MVP 2-3)

### DA-007: config.py com pydantic-settings
- **Decisão:** Centralizar toda configuração em `config.py` usando `pydantic-settings`
- **Alternativa rejeitada:** `os.getenv()` espalhado
- **Motivo:** Tipagem, validação de env vars na inicialização, facilita testes, facilita evolução
- **Não é overengineering:** é o mínimo para um projeto que vai para produção pessoal

### DA-008: Soft delete + audit log para operações destrutivas
- **Decisão:** Exclusões usam `deleted_at TIMESTAMP NULL` (soft delete). Toda mutação grava snapshot em `audit_log`.
- **Alternativa rejeitada:** `DELETE FROM` físico; ausência de auditoria
- **Motivo:** Dados financeiros nunca devem ser destruídos silenciosamente. Soft delete permite recuperação manual; audit log garante rastreabilidade. Custo: ~1 coluna + 1 tabela.
- **Impacto no schema:** coluna `deleted_at` na tabela `expenses` + tabela `audit_log`. Migração via `ALTER TABLE IF NOT EXISTS` para bancos existentes.
- **Regra:** todas as queries de leitura filtram `WHERE deleted_at IS NULL`. `audit_log` nunca é exposto como MCP tool.

### DA-009: confirmed=True como gate obrigatório em tools destrutivas
- **Decisão:** `delete_expense(expense_id, confirmed)` e `update_expense(expense_id, confirmed, ...)` rejeitam imediatamente se `confirmed=False` (default).
- **Alternativa rejeitada:** HITL real com `interrupt()` do LangGraph (requer SqliteSaver — MVP 2+)
- **Motivo:** O parâmetro `confirmed` é o gate técnico que protege contra execução acidental mesmo que o system prompt seja ignorado ou sofra prompt injection. É a última linha de defesa antes do banco.
- **Regra no system prompt:** o agente só passa `confirmed=True` se a mensagem ATUAL do usuário contiver confirmação explícita ("sim", "confirmo", "yes", "pode").
- **Revisão:** substituir por `interrupt()` real no MVP 2 quando migrar para `SqliteSaver`.

### DA-010: find_expense_candidates como tool dedicada para busca pré-destrutiva
- **Decisão:** Nova tool `find_expense_candidates(keyword, expense_date?)` usada obrigatoriamente antes de qualquer delete ou update.
- **Alternativa rejeitada:** usar `query_expenses` genérico; colocar lógica de "mais recente" no nó LangGraph
- **Motivo:** Separar a busca da execução cria um ponto de verificação natural antes de qualquer mutação. A lógica de "retornar apenas a data mais recente" é determinística e pertence ao servidor (requer SQL), não ao LLM.
- **Comportamento:**
  - Com `expense_date`: filtra por data exata informada
  - Sem `expense_date`: executa `MAX(expense_date)` para o keyword e filtra por essa data
  - Retorna `{keyword, date_searched, total_found, records}` — rastreável no LangSmith

### DA-012: Alembic como gerenciador de migrations (MVP 2)
- **Decisão:** Adotar Alembic para gerenciar toda evolução de schema a partir do MVP 2.
- **Alternativa rejeitada:** continuar com `ALTER TABLE` manual em `setup.py`
- **Motivo:** O schema já evoluiu duas vezes (added `deleted_at`, `audit_log`). O hack `ALTER TABLE IF NOT EXISTS` em `setup.py` não escala — Alembic é a solução certa agora.
- **Modelo de convivência:**
  - `setup_database()` permanece no `server.py` como safety net para o subprocesso MCP
  - `main.py` chama `run_migrations()` (Alembic `upgrade head`) no startup — autoridade final sobre o schema
  - Migrations usam `op.execute()` com SQL raw (sem SQLAlchemy ORM) — compatível com sqlite3 existente
  - `0001_initial_schema` captura o estado atual como baseline; DBs existentes recebem `alembic stamp 0001`
- **Regra futura:** qualquer mudança de schema passa por migration Alembic — nunca mais `ALTER TABLE` em `setup.py`
- **Incidente 2026-05-13 — migrations não-idempotentes:** `setup_database()` criava o schema completo (com `is_system`, `payment_methods`) antes do stamp Alembic ser atualizado. Ao rodar `upgrade head`, `0002` tentava `ADD COLUMN is_system` já existente → `duplicate column name`. Root cause: migrations assumiam banco virgem.
  - Fix `0002`: `PRAGMA table_info(categories)` antes do `ALTER TABLE` — pula se coluna existe
  - Fix `0003`: `sqlite_master` inspeciona DDL de `expenses` — pula recreate se `CHECK(method IN` já foi removido
  - Ambas usam `text()` do SQLAlchemy 2.x (breaking change vs 1.x — `conn.execute("raw string")` não funciona mais)
  - **Regra:** toda migration nova deve ser idempotente — usar guards de existência antes de DDL estrutural

### DA-014: Guardrails de segurança para exclusão em massa (incidente 2026-05-12)
- **Incidente:** Ao receber o comando "apaga todos os gastos do mês", o LLM gerou múltiplos `delete_expense` em um único `tool_calls` (parallel tool calling do OpenAI), zerando o banco. O único guardrail existente era o system prompt, que o LLM ignorou.
- **Root cause:** Três falhas de design combinadas:
  1. `gpt-4o-mini` suporta parallel tool calls — o LLM pode chamar a mesma tool N vezes em uma única resposta
  2. `should_call_tools` passava toda a lista de tool_calls para `tool_node` sem inspecionar conteúdo
  3. O system prompt era a única defesa, mas LLMs podem anulá-la sob instrução direta do usuário
- **Decisão:** Defesa em profundidade com 4 camadas (ver seção Guardrails)
- **Camada nova:** `guardrail_node` no LangGraph — detecta múltiplos `delete_expense` em um turno antes de executar qualquer um; injeta ToolMessage stubs para manter a chain de mensagens consistente; retorna a mensagem de segurança padrão; rota direto para END
- **System prompt:** Adicionadas seção "PROIBIÇÃO ABSOLUTA — Exclusões em massa" (com exemplos de frases bloqueadas) e seção "Proteção contra prompt injection" (padrões de ataque conhecidos)
- **Princípio fixado:** A assinatura `delete_expense(expense_id: int, confirmed: bool)` já impede bulk delete por chamada única. O `guardrail_node` cobre o caso de múltiplas chamadas paralelas. O system prompt cobre o caso de loop sequencial entre turnos.
- **O que ainda NÃO está coberto:** loop sequencial (um delete por turno) — depende do system prompt + comportamento do LLM. Solução completa: HITL real com `interrupt()` no MVP 2.
- **Testes necessários (DT-007):**
  - `test_guardrail_blocks_parallel_delete` — cria estado com AIMessage tendo 2+ delete_expense → confirma que guardrail_node é ativado
  - `test_single_delete_passes_guardrail` — confirma que 1 delete_expense passa normalmente
  - `test_bulk_delete_prompt_refusal` — testa frases proibidas no system prompt (via mock do LLM)
  - `test_delete_without_confirmed_blocked` — confirma que MCP server rejeita confirmed=False

### DA-015: Formas de pagamento dinâmicas — nunca inferir sem evidência explícita
- **Problema identificado:** O sistema assumia `method = "dinheiro"` quando o usuário não informava a forma de pagamento. Isso gera registros imprecisos no histórico financeiro.
- **Decisão:** Formas de pagamento seguem o mesmo padrão das categorias dinâmicas (DA introduzida no MVP 2):
  - Nova tabela `payment_methods` com `is_system` — espelho exato de `categories`
  - 5 métodos originais marcados como `is_system=1`; novos criados pelo usuário com `is_system=0`
  - Validação migra do `CHECK` constraint hardcoded no SQLite para consulta dinâmica à tabela
- **Regra comportamental:** Agente NUNCA assume a forma de pagamento. Se ausente, pergunta ao usuário com lista numerada (incluindo "Outra"). Se o usuário responder "Outra" ou método desconhecido → HITL de criação (mesmo protocolo de `create_category`)
- **Regra arquitetural:** Criação de método de pagamento é HITL conversacional (igual a categorias) — não usa `interrupt()` porque não é operação destrutiva
- **Implementação:** ✅ concluída em 2026-05-13 (commit 3e99fcb)
  - Alembic 0003: cria `payment_methods` + seed + recria `expenses` sem o `CHECK(method IN (...))` — SQLite não tem DROP CONSTRAINT; `CREATE new → INSERT SELECT → DROP → RENAME`
  - Novas tools: `list_payment_methods()` e `create_payment_method(name, confirmed)`
  - Removidos: `VALID_METHODS` hardcoded e `PaymentMethod = Literal[...]` em `schemas.py`
  - `record_expense`: parâmetro `method` sem default (obrigatório) — agente sempre pergunta
  - System prompt: regra de nunca assumir método + protocolo HITL idêntico ao de categorias
  - LangGraph: nenhuma mudança no grafo
- **Reaproveitamento:** `create_payment_method` tem assinatura e guardrails idênticos a `create_category` (strip, lowercase, 2–30 chars, unicodedata, duplicate check case-insensitive, `confirmed` gate)

### DA-013: Escopo do MVP 2 (análise crítica)
- **Inclui:** SqliteSaver + trimming, interrupt() HITL, pytest, Alembic, retry OpenAI
- **Exclui deliberadamente:** multi-agente, structlog, output guardrails, service layer, cache, feature flags
- **Multi-agente rejeitado para MVP 2:** agente único já funciona bem; roteador triplicaria calls ao LLM; complexidade artificial sem ganho real
- **structlog rejeitado:** LangSmith cobre ~90% da observabilidade necessária; adicionar structlog seria duplicação
- **Critério de conclusão MVP 2:**
  - Sessão anterior disponível ao reiniciar (`python main.py`)
  - delete/update usam `interrupt()` real
  - `pytest tests/` passa com ≥80% cobertura do MCP server
  - Schema evoluível via `alembic upgrade head`
  - Chamadas OpenAI com retry automático

### DA-016: Busca textual por descrição em `query_expenses`
- **Problema:** `query_expenses` aceita apenas filtros exatos (`category`, `method`, `start_date`, `end_date`). Quando o usuário pergunta "paguei a conta de energia?", o LLM tenta mapear para categoria ("Serviços") e ignora a descrição — retorna lista errada ou responde "não encontrei" mesmo com registro existente.
- **Root cause:** Três falhas combinadas: (1) `query_expenses` sem busca textual; (2) `find_expense_candidates` tem busca por descrição mas está documentada como "pre-destructive only" e comprime resultados para data mais recente — comportamento errado para consultas; (3) seção "Ao CONSULTAR gastos" do system prompt não instrui o agente a buscar por descrição.
- **Decisão:** Adicionar `keyword: Optional[str]` ao `query_expenses`. Filtragem Python com `_normalize_description` após filtros SQL — mesmo padrão já existente em `find_expense_candidates`, zero nova infra. Reescrever seção "Ao CONSULTAR gastos" com protocolo keyword-first.
- **Alternativas rejeitadas:**
  - FTS5: overkill para volume pessoal; `LIKE '%x%'` + Python é suficiente
  - Nova tool `search_expenses`: proliferação desnecessária — `query_expenses` já é o ponto natural
  - Índice em `description`: LIKE com wildcard à esquerda não usa B-tree; sem ganho
- **Aliases ("energia" → "luz"):** instrução no system prompt para o LLM tentar termos relacionados quando `keyword` retornar 0 resultados. Sem mapa hardcoded — o LLM conhece sinônimos.
- **Separação de responsabilidades mantida:**
  - `query_expenses(keyword=...)` → consultas (retorna todos os registros do período)
  - `find_expense_candidates(keyword=...)` → exclusivo para pré-delete/update (comprime para data mais recente)
- **Implementação pendente** — ver Próximos Passos

### DA-011: Separação de responsabilidades — interpretação vs execução
- **Decisão:** Interpretação temporal fica no LLM; lógica SQL fica no servidor MCP.
- **Regra:**
  - LLM converte linguagem natural → `YYYY-MM-DD` quando há data específica ("ontem", "02/03")
  - LLM **não** converte ranges vagos ("semana passada", "mês passado") — trata como ausente, servidor usa lógica do mais recente
  - Servidor executa `MAX(expense_date)` quando `expense_date` é omitida
- **Motivo:** LLM é bom em semântica; servidor é confiável para lógica de dados. Misturar os dois cria comportamento não-determinístico e difícil de testar.
- **Proteção contra ambiguidade:** `find_expense_candidates` sempre retorna `total_found`; se 0, o agente oferece alternativa sem tentar deletar. Se >1, lista e pede escolha por ID.

---

## Roadmap de MVPs

### MVP 1 — Base (atual) ✓ COMPLETO
**Foco:** Registro, consulta, exclusão e edição via CLI
- Agente único ReAct
- MCP stdio com 7 tools (record, query, summary, categories, find_candidates, delete, update)
- SQLite com 3 tabelas (expenses + categories + audit_log)
- Soft delete + audit log
- Guardrails: Pydantic + DB constraints + confirmed=True gate
- HITL conversacional (confirmação via chat)
- Observabilidade LangSmith
- CLI simples com loop de mensagens

### MVP 2 — Robustez (em andamento)
**Foco:** Qualidade e confiabilidade

**Concluído:**
- [x] Alembic migrations (0001–0003) — idempotência corrigida em 2026-05-13 (SQLAlchemy 2.x + guards DDL)
- [x] SqliteSaver + trim_messages — sessão persiste entre reinicializações
- [x] interrupt() HITL — confirm_node para delete/update
- [x] guardrail_node — bloqueia bulk delete via parallel tool calls
- [x] Categorias dinâmicas — create_category com HITL
- [x] Métodos de pagamento dinâmicos (DA-015) — create_payment_method com HITL
- [x] Soft delete + audit_log em todas as operações destrutivas
- [x] Diagramas PlantUML (arquitetura MVP 2 + atividades excluir gasto)
- [x] Busca textual por descrição em query_expenses (DA-016) — keyword parameter com filtragem Python

**Pendente:**
- [ ] Testes automatizados pytest (DT-007)
- [ ] Retry automático OpenAI com tenacity (DT-006)

### MVP 3 — Importação e Histórico
**Foco:** Popular com dados reais
- Tool `bulk_import` para importar CSVs do banco/cartão
- RAG para busca semântica em descrições
- Agentic RAG com LangGraph
- Categorização assistida por embeddings

### MVP 4 — Análise e Alertas
**Foco:** Inteligência financeira
- Orçamento mensal por categoria
- Alertas de estouro de budget
- Comparativo mês a mês
- Insights automáticos ("Você gastou 40% mais em Lazer este mês")
- Registro de investimentos

### MVP 5 — Integrações
**Foco:** Canais de entrada
- WhatsApp / Telegram (via webhook)
- Registro por áudio (Whisper API)
- Leitura de comprovantes (visão computacional)

### MVP 6 — API e Interface
**Foco:** Produto completo
- FastAPI como backend
- Dashboard com gráficos (Streamlit ou frontend simples)
- Múltiplos usuários
- Exportação de relatórios PDF/Excel

---

## Funcionalidades Futuras

- [ ] Importação de extratos bancários (CSV/OFX)
- [ ] Integração WhatsApp/Telegram
- [ ] Registro por áudio (Whisper)
- [ ] Leitura de comprovantes por imagem
- [ ] Dashboard com gráficos via linguagem natural
- [ ] Orçamento mensal por categoria + alertas
- [ ] Registro de investimentos (renda fixa, variável)
- [ ] Memória financeira do usuário (padrões, médias históricas)
- [ ] Relatório mensal automático
- [ ] Exportação CSV/PDF
- [ ] API REST (FastAPI)
- [ ] Frontend web
- [ ] Múltiplos usuários
- [ ] Sincronização com bancos via Open Finance

---

## Dívidas Técnicas

| ID | Descrição | Impacto | Quando resolver |
|---|---|---|---|
| DT-001 | ~~`MemorySaver` in-memory perde contexto ao reiniciar~~ | ✅ Resolvido — AsyncSqliteSaver (MVP 2) | — |
| DT-002 | ~~Sem migrations de banco (só `IF NOT EXISTS`)~~ | ✅ Resolvido — Alembic 0001–0003 (MVP 2) | — |
| DT-003 | Sem testes automatizados | Alto (qualidade) | MVP 2 |
| DT-004 | ~~HITL via prompt, não via `interrupt()` real~~ | ✅ Resolvido — confirm_node + interrupt() (MVP 2) | — |
| DT-005 | Thread safety do SQLite (conexão única) | Baixo (single-user) | MVP 4+ |
| DT-006 | Sem retry para falhas de chamada à OpenAI | Baixo (uso pessoal) | MVP 2 pendente |
| DT-007 | Sem testes automatizados para guardrails de segurança | Alto (regressão crítica) | MVP 2 — próxima prioridade |

---

## Próximos Passos

### Imediato — MVP 1
1. [x] Criar `config.py`
2. [x] Criar `database/setup.py`
3. [x] Criar `models/schemas.py`
4. [x] Criar `mcp_server/server.py`
5. [x] Criar `agent/prompts.py`
6. [x] Criar `agent/guardrails.py`
7. [x] Criar `agent/graph.py`
8. [x] Criar `main.py`
9. [x] Adicionar OPENAI_API_KEY no `.env`
10. [x] Testar fluxo end-to-end — registro e consulta funcionando
11. [ ] Validar traces no LangSmith (ver nota abaixo)

**Nota LangSmith:** `LANGCHAIN_TRACING_V2` deve estar sem aspas no `.env` (ex: `LANGCHAIN_TRACING_V2=true`, não `="true"`).
O LangChain lê essa variável diretamente do ambiente, não via `config.py`.

### MVP 2 — Próximos Passos

**Prioridade 1: DT-006 — Retry automático OpenAI**
- Adicionar `tenacity` ao requirements.txt
- Envolver chamadas à OpenAI com retry exponencial (3 tentativas, 1-3s delay)
- Exemplo: `@retry(stop=stop_after_attempt(3), wait=wait_exponential())`

**Prioridade 2: DT-007 — Testes automatizados para guardrails**
- Resolver database locking em testes pytest
- Testes críticos: `test_guardrail_blocks_parallel_delete`, `test_delete_without_confirmed_blocked`
- Coverage mínima: 80% do MCP server

### MVP 2 — Concluído: DA-016 (2026-05-14)

#### Implementação de Busca Textual por Descrição

1. [x] `mcp_server/server.py` — adicionado `keyword: Optional[str] = None` ao `query_expenses`
   - Filtragem em Python com `_normalize_description` após filtros SQL
   - Suporte a busca parcial, case-insensitive e accent-insensitive
   - Backward compatible — sem keyword retorna todos os registros

2. [x] `agent/prompts.py` — reescrita seção "Ao CONSULTAR gastos"
   - Protocolo keyword-first: `query_expenses(keyword=...)` obrigatório para itens específicos
   - Instrução para tentar sinônimos antes de responder "não encontrei"
   - Distinção explícita entre `query_expenses` (consultas) vs `find_expense_candidates` (pré-delete/update)

3. [x] `tests/` — testes criados (validados manualmente)
   - Arquivo `test_da016_manual.py` com 10 testes cobrindo:
     - Busca exata e parcial
     - Case-insensitive e accent-insensitive
     - Combinação com filtros de data, categoria, método
     - Soft-delete excluído
     - Ordenação DESC
     - Backward compatibility sem keyword
   - Testes pytest criados mas com limitações de database locking (DT-007 futuro)

4. [x] `PROJECT_MEMORY.md` — marcado DA-016 como implementado

---

### Decisão resolvida
- [x] **Fluxo de registro:** Opção A — direto (registra imediatamente, confirma só para valores > R$ 1.000)

### Ambiente
- Conda env: `financas-ia` (Python 3.12)
- Ativar: `conda activate financas-ia`
- Rodar: `python main.py` (a partir do diretório `financas-ia/`)

---

## Convenções do Projeto

### Código
- Python 3.12, type hints em tudo
- Pydantic v2 para toda validação de dados
- `async/await` no LangGraph (padrão do framework)
- Nomes em português para variáveis de domínio, inglês para infraestrutura
- Sem comentários óbvios — código auto-documentado
- Um comentário curto apenas quando o "porquê" não é óbvio

### Banco de dados
- Tabelas: prefixo sem convenção especial (evitar `tb_` — escolha do projeto novo)
- Datas sempre em `DATE` (YYYY-MM-DD), timestamps em `TIMESTAMP`
- Nunca deletar dados financeiros via agente — append-only

### Git
- Commits por MVP / feature concluída
- `.env` nunca versionado
- `financas.db` nunca versionado (dados pessoais)

### Nomenclatura de arquivos
- `snake_case` para tudo
- Sem prefixo `dsa_` (esse era do curso — projeto novo tem identidade própria)

---

## Aprendizados Importantes

### Sobre MCP
- O servidor MCP é uma camada de dados, não de lógica de negócio
- O agente (LangGraph) é o cérebro — regras de negócio ficam aqui
- `stdio` é ideal para desenvolvimento — zero infra extra
- `streamable-http` é para quando precisar de servidor compartilhado

### Sobre LangGraph
- `MemorySaver` é in-memory — perde estado ao reiniciar o processo
- Para persistência real entre sessões: `SqliteSaver` ou `PostgresSaver`
- HITL com `interrupt()` requer checkpointer externo (não MemorySaver)
- `StateGraph` com estado simples (`messages`) é suficiente para MVP

### Sobre Guardrails
- Dois layers são suficientes: Pydantic no servidor + prompt no agente
- `UNIQUE constraint` do SQLite é o guardrail mais confiável para duplicatas
- Não expor tools destrutivas é mais seguro do que guardrail que tenta bloqueá-las

### Sobre LLM
- `gpt-4o-mini` é adequado para extração de entidades e classificação simples
- Temperature 0 para tarefas de extração (determinístico)
- Lista fixa de categorias no prompt elimina inconsistência de classificação

---

*Este arquivo é mantido manualmente ao longo do desenvolvimento.*
*Atualize as seções "Próximos Passos", "Dívidas Técnicas" e "Decisões Arquiteturais" a cada etapa concluída.*
