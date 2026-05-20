# Finanças IA - Assistente Financeiro Pessoal com Telegram Bot

Sistema de gerenciamento de finanças pessoais com IA, integrado ao Telegram. Permite registrar, consultar e analisar gastos através de conversas naturais com um assistente inteligente.

## 📋 Funcionalidades

- 💬 Interface conversacional via Telegram Bot
- 💰 Registro de despesas com confirmação HITL (Human-in-the-Loop)
- 📊 Consultas e análises de gastos
- 🏷️ Categorias e formas de pagamento personalizáveis
- 👥 Multi-tenant com isolamento de dados por usuário
- 🔒 Whitelist de segurança (apenas usuários autorizados)
- 🤖 IA integrada via LangGraph + OpenAI

## 🚀 Guia de Instalação e Configuração

### 1. Pré-requisitos

- Python 3.10+
- Conta no Telegram
- API Key da OpenAI

### 2. Clonar o Repositório

```bash
git clone https://github.com/hscleandro/financas-ia.git
cd financas-ia
```

### 3. Criar Ambiente Virtual

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows
```

### 4. Instalar Dependências

```bash
pip install -r requirements.txt
```

### 5. Configurar o Telegram Bot

#### 5.1. Criar um Bot no Telegram

1. Abra o Telegram e procure por `@BotFather`
2. Envie o comando `/newbot`
3. Escolha um nome para seu bot (ex: "Meu Assistente Financeiro")
4. Escolha um username único terminando em `bot` (ex: `meu_financas_bot`)
5. O BotFather vai retornar um **token** assim:
   ```
   Use this token to access the HTTP API:
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
6. **Copie esse token** (você vai precisar dele)

#### 5.2. Obter seu Telegram ID

1. No Telegram, procure por `@userinfobot`
2. Inicie uma conversa e ele vai te enviar seu **ID numérico**
3. Anote esse número (ex: `974597459`)

### 6. Configurar Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto:

```bash
cp .env.example .env
```

Edite o arquivo `.env` e configure:

```bash
# OpenAI API
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Telegram Bot (obrigatório)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Telegram Webhook (opcional - apenas para produção)
TELEGRAM_WEBHOOK_SECRET=meu-segredo-super-secreto
TELEGRAM_WEBHOOK_URL=https://meudominio.com/webhook/telegram

# Banco de dados
DATABASE_PATH=./financas.db
CHECKPOINTS_PATH=./checkpoints.db
```

**⚠️ Importante:**
- Substitua `OPENAI_API_KEY` pela sua chave real da OpenAI
- Substitua `TELEGRAM_BOT_TOKEN` pelo token que o BotFather te deu
- Não compartilhe o arquivo `.env` (ele já está no .gitignore)

### 7. Inicializar o Banco de Dados

Execute o script de setup para criar as tabelas e adicionar seu usuário:

```bash
python setup_telegram_user.py SEU_TELEGRAM_ID "Seu Nome"
```

**Exemplo:**
```bash
python setup_telegram_user.py 974597459 "Leandro"
```

Este comando vai:
- ✅ Executar todas as migrations do banco de dados
- ✅ Criar as tabelas necessárias
- ✅ Adicionar você como usuário autorizado
- ✅ Retornar seu `user_id` interno

### 8. Executar o Bot

#### Opção A: Usando o Script de Controle (Recomendado)

```bash
# Ver comandos disponíveis
./bot_control.sh

# Iniciar o bot em background
./bot_control.sh start

# Ver status do bot
./bot_control.sh status

# Ver logs em tempo real
./bot_control.sh logs -f

# Parar o bot
./bot_control.sh stop

# Reiniciar o bot
./bot_control.sh restart
```

#### Opção B: Execução Manual

```bash
# Modo foreground (você vê os logs no terminal)
python main_telegram_polling.py

# Modo background (liberando o terminal)
nohup python main_telegram_polling.py > /tmp/telegram_bot.log 2>&1 &

# Ver logs
tail -f /tmp/telegram_bot.log

# Parar o bot
pkill -f main_telegram_polling.py
```

### 9. Testar o Bot

1. Abra o Telegram
2. Procure pelo username do seu bot (ex: `@meu_financas_bot`)
3. Clique em "Iniciar" ou envie `/start`
4. Envie uma mensagem de teste:

**Exemplos de comandos:**
```
Registre um gasto de R$ 50 em alimentação no cartão de crédito

Quanto gastei esse mês?

Liste os gastos dessa semana

Mostre meus gastos de transporte

Adicione uma despesa de R$ 25 em Uber com pix
```

## 🎯 Comandos do Bot

O bot entende linguagem natural. Exemplos:

### Registrar Despesas
- "Gastei R$ 30 no almoço"
- "Registre R$ 50 em transporte com débito"
- "Paguei R$ 100 na farmácia com pix"

### Consultar Gastos
- "Quanto gastei hoje?"
- "Mostre meus gastos dessa semana"
- "Lista as despesas de alimentação"
- "Qual o total do mês?"

### Análises
- "Resumo dos últimos 7 dias"
- "Quanto gastei em transporte esse mês?"
- "Mostre o resumo de ontem"

## 🗂️ Estrutura do Projeto

```
financas-ia/
├── agent/                      # Agente LangGraph
│   ├── graph.py               # Grafo de estados
│   ├── nodes.py               # Nós do grafo
│   └── tools.py               # Tools do LangChain
├── api/                       # FastAPI (webhook produção)
│   └── webhook.py
├── bot/                       # Telegram Bot
│   ├── handlers.py            # Processamento de mensagens
│   └── keyboards.py           # Teclados inline (HITL)
├── database/                  # Camada de dados
│   ├── setup.py               # Setup inicial
│   └── user_setup.py          # Gestão de usuários
├── migrations/                # Alembic migrations
│   └── versions/
├── services/                  # Service Layer
│   └── expense_service.py     # Lógica de negócio
├── tests/                     # Testes
├── bot_control.sh            # Script de controle do bot
├── main_telegram_polling.py  # Entrypoint polling
├── setup_telegram_user.py    # Setup de usuários
├── config.py                 # Configurações
├── requirements.txt          # Dependências
└── .env                      # Variáveis de ambiente
```

## 🛠️ Gerenciamento de Usuários

### Adicionar Novo Usuário

```bash
python setup_telegram_user.py TELEGRAM_ID "Nome do Usuário"
```

### Listar Usuários (via SQLite)

```bash
sqlite3 financas.db "SELECT * FROM users;"
```

### Desativar Usuário

```bash
sqlite3 financas.db "UPDATE users SET is_active = 0 WHERE telegram_id = TELEGRAM_ID;"
```

### Reativar Usuário

```bash
sqlite3 financas.db "UPDATE users SET is_active = 1 WHERE telegram_id = TELEGRAM_ID;"
```

## 🔧 Troubleshooting

### Bot não responde

1. Verifique se está rodando:
   ```bash
   ./bot_control.sh status
   ```

2. Verifique os logs:
   ```bash
   ./bot_control.sh logs -f
   ```

3. Verifique o token no `.env`:
   ```bash
   cat .env | grep TELEGRAM_BOT_TOKEN
   ```

### Erro: "Acesso não autorizado"

Você precisa estar registrado no banco de dados:
```bash
python setup_telegram_user.py SEU_TELEGRAM_ID "Seu Nome"
```

### Erro: "OPENAI_API_KEY não configurado"

Configure a chave no arquivo `.env`:
```bash
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Bot trava ou não inicia

1. Verifique se outro processo está usando a porta:
   ```bash
   pkill -f main_telegram_polling.py
   ```

2. Limpe os arquivos de lock do SQLite:
   ```bash
   rm -f *.db-shm *.db-wal
   ```

3. Reinicie o bot:
   ```bash
   ./bot_control.sh restart
   ```

### Ver logs detalhados

```bash
# Últimas 50 linhas
./bot_control.sh logs

# Acompanhar em tempo real
./bot_control.sh logs -f

# Ver tudo
cat /tmp/telegram_bot.log
```

## 🧪 Testes

### Executar Todos os Testes

```bash
pytest
```

### Executar Testes com Cobertura

```bash
pytest --cov=. --cov-report=html
```

### Testar Isolamento Multi-tenant

```bash
pytest tests/test_multitenant_isolation.py -v
```

## 📦 Dependências Principais

- **python-telegram-bot** - Interface com Telegram API
- **langgraph** - Framework de agentes com estados
- **langchain** - Construção de tools e prompts
- **openai** - Integração com GPT
- **fastapi** - API para webhook (produção)
- **alembic** - Migrations de banco de dados
- **sqlite3** - Banco de dados local

## 🚀 Deploy (Produção)

Para deploy em produção com webhook, consulte:
- `README_TELEGRAM.md` - Guia completo de integração Telegram
- `api/webhook.py` - Implementação do webhook FastAPI

## 📝 Licença

Este projeto é de uso pessoal/educacional.

## 🤝 Contribuindo

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/MinhaFeature`)
3. Commit suas mudanças (`git commit -m 'feat: adiciona MinhaFeature'`)
4. Push para a branch (`git push origin feature/MinhaFeature`)
5. Abra um Pull Request

## 📧 Contato

Para dúvidas ou sugestões, abra uma issue no GitHub.

---

**Desenvolvido com ❤️ usando Python, LangGraph e OpenAI**
