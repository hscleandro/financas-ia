# Finanças IA - Assistente Financeiro Pessoal com Telegram Bot

Sistema de gerenciamento de finanças pessoais com IA, integrado ao Telegram. Permite registrar, consultar e analisar gastos através de conversas naturais com um assistente inteligente.

## 📋 Funcionalidades

### Telegram Bot
- 💬 Interface conversacional via Telegram Bot
- 💰 Registro de despesas com confirmação HITL (Human-in-the-Loop)
- 📊 Consultas e análises de gastos
- 🏷️ Categorias e formas de pagamento personalizáveis
- 👥 Multi-tenant com isolamento de dados por usuário
- 🔒 Whitelist de segurança (apenas usuários autorizados)
- 🤖 IA integrada via LangGraph + OpenAI

### Interface Web (V1)
- 📊 Dashboard de despesas responsivo (categoria, forma de pagamento, evolução mensal)
- 📥 Importação de fatura PDF do cartão Bradesco
- 🔍 Seleção de titular/cartão e conciliação 1:1 com tolerância de ±2 dias
- ✏️ Revisão em três seções: só na fatura, na fatura e no banco, só no banco
- 🏷️ Definição de categoria por lançamento ao importar
- ✅ Confirmação única com transação atômica e audit log
- 🔒 Autenticação por senha mestre

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

### 8. Executar a Interface Web (V1)

```bash
# Adicione ao .env
WEB_AUTH_PASSWORD=senha-forte-aqui
WEB_SESSION_SECRET=segredo-aleatorio-longo-aqui
WEB_PORT=8080

# Aplique migrations
alembic upgrade head

# Inicie a aplicação web
source venv/bin/activate
uvicorn web.main:app --host 0.0.0.0 --port 8080
```

Acesse `http://localhost:8080` no navegador e faça login com a senha definida.

### 9. Executar o Bot

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

#### Opção C: Docker (Recomendado para Produção)

Docker simplifica o deployment e garante consistência entre ambientes.

##### 1. Pré-requisitos Docker

- Docker instalado ([Guia de instalação](https://docs.docker.com/get-docker/))
- Docker Compose instalado (geralmente vem com Docker Desktop)

##### 2. Configurar Variáveis de Ambiente

```bash
# Copiar exemplo de .env para Docker
cp .env.docker.example .env

# Editar com seus valores
nano .env  # ou vim, gedit, code, etc.
```

Preencha obrigatoriamente:
- `OPENAI_API_KEY` - Sua chave da OpenAI
- `TELEGRAM_BOT_TOKEN` - Token do BotFather
- `BOT_MODE` - "polling" (desenvolvimento) ou "webhook" (produção)

##### 3. Criar Diretório de Dados

```bash
# Criar diretório para persistência do banco de dados
mkdir -p data
```

##### 4. Registrar Usuário (Primeira Vez)

Antes de iniciar o bot, registre seu usuário:

```bash
# Build da imagem
docker-compose build

# Rodar setup de usuário
docker-compose run --rm financas-bot python setup_telegram_user.py SEU_TELEGRAM_ID "Seu Nome"

# Exemplo:
docker-compose run --rm financas-bot python setup_telegram_user.py 974597459 "Leandro"
```

##### 5. Iniciar o Bot com Docker Compose

```bash
# Iniciar em background
docker-compose up -d

# Ver logs em tempo real
docker-compose logs -f

# Verificar status
docker-compose ps
```

##### 6. Gerenciar o Container

```bash
# Parar o bot
docker-compose down

# Reiniciar o bot
docker-compose restart

# Ver logs (últimas 100 linhas)
docker-compose logs --tail=100

# Acompanhar logs
docker-compose logs -f financas-bot

# Executar comandos dentro do container
docker-compose exec financas-bot bash
```

##### 7. Build Manual (Alternativa ao Docker Compose)

```bash
# Build da imagem
docker build -t financas-ia-bot .

# Executar em modo polling (desenvolvimento)
docker run -d \
  --name financas-bot \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  financas-ia-bot

# Executar em modo webhook (produção)
docker run -d \
  --name financas-bot \
  --env-file .env \
  -e BOT_MODE=webhook \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  financas-ia-bot

# Ver logs
docker logs -f financas-bot

# Parar container
docker stop financas-bot

# Remover container
docker rm financas-bot
```

##### 8. Volumes e Persistência

Os dados do banco são armazenados no diretório `./data/`:
- `data/financas.db` - Banco de dados principal
- `data/checkpoints.db` - Estados do LangGraph

**⚠️ Backup:** Faça backup regular do diretório `data/`

```bash
# Backup manual
tar -czf backup-$(date +%Y%m%d).tar.gz data/

# Restaurar backup
tar -xzf backup-20260519.tar.gz
```

##### 9. Troubleshooting Docker

**Container não inicia:**
```bash
# Ver logs de erro
docker-compose logs financas-bot

# Verificar variáveis de ambiente
docker-compose config
```

**Banco de dados travado:**
```bash
# Parar container
docker-compose down

# Limpar locks do SQLite
rm -f data/*.db-shm data/*.db-wal

# Reiniciar
docker-compose up -d
```

**Reconstruir imagem após mudanças:**
```bash
docker-compose build --no-cache
docker-compose up -d
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
│   ├── expense_service.py     # Lógica de negócio de despesas
│   ├── income_service.py      # Lógica de negócio de receitas
│   ├── statement_parser.py    # Parser de fatura PDF Bradesco
│   └── statement_service.py   # Conciliação de faturas
├── web/                       # Interface web V1
│   ├── main.py                # App FastAPI
│   ├── auth.py                # Autenticação
│   ├── templates/             # Templates Jinja2
│   └── static/                # CSS/JS/uploads
├── tests/                     # Testes
├── data/                      # Dados persistentes (volumes)
│   ├── financas.db            # Banco principal
│   └── checkpoints.db         # Estados LangGraph
├── Dockerfile                 # Container image
├── docker-compose.yml         # Orquestração Docker
├── docker-entrypoint.sh       # Script de inicialização
├── .dockerignore              # Arquivos ignorados no build
├── .env.docker.example        # Exemplo de .env para Docker
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

## 💬 Otimizações de UX para Telegram

O bot foi otimizado especificamente para a experiência mobile do Telegram:

### Características

- ✅ **Mensagens curtas e diretas** (2-3 linhas)
- ✅ **Formatação Markdown aprimorada** (negrito, itálico, estrutura)
- ✅ **Emojis estratégicos** para feedback visual rápido
- ✅ **Botões inline claros** ("✅ Sim, confirmar" vs "❌ Não, cancelar")
- ✅ **Listas truncadas** (máx 10 itens + resumo)
- ✅ **Respostas otimizadas** para leitura em tela pequena

### Exemplo de Interação

**Usuário:** "Gastei 50 reais no almoço com pix"

**Bot:**
```
✅ R$ 50,00 · Almoço · Alimentação · pix · 19/05/2026
```

**Usuário:** "Quanto gastei em alimentação esse mês?"

**Bot:**
```
📊 Resumo - Maio 2026

🍔 Alimentação: R$ 1.250,00

💰 Total: R$ 1.250,00
```

Para mais detalhes, consulte: [docs/UX_TELEGRAM_GUIDELINES.md](docs/UX_TELEGRAM_GUIDELINES.md)

## 📦 Dependências Principais

- **python-telegram-bot** - Interface com Telegram API
- **langgraph** - Framework de agentes com estados
- **langchain** - Construção de tools e prompts
- **openai** - Integração com GPT
- **fastapi** - API para webhook (produção)
- **alembic** - Migrations de banco de dados
- **sqlite3** - Banco de dados local

## 🚀 Deploy (Produção)

### Docker (Recomendado)

A aplicação está containerizada e pronta para deploy:

```bash
# Configurar .env com BOT_MODE=webhook
echo "BOT_MODE=webhook" >> .env

# Build e deploy
docker-compose up -d

# Verificar saúde
docker-compose ps
curl http://localhost:8000/health
```

**Requisitos para webhook:**
- Domínio público com HTTPS
- Configurar `TELEGRAM_WEBHOOK_URL` no `.env`
- Configurar `TELEGRAM_WEBHOOK_SECRET` (segredo único)
- Expor porta 8000 (ou configurar reverse proxy)

### Deploy Manual

Para deploy em produção sem Docker, consulte:
- [docs/README_TELEGRAM.md](docs/README_TELEGRAM.md) - Guia completo de integração Telegram
- `api/webhook.py` - Implementação do webhook FastAPI

### Plataformas Recomendadas

- **AWS EC2** - Máquinas virtuais com Docker
- **DigitalOcean Droplets** - Deploy simples com Docker
- **Railway** - Deploy automático via Git
- **Fly.io** - Containerização nativa
- **Render** - Deploy gratuito (tier limitado)

## 📚 Documentação Adicional

- [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) - Estrutura completa do projeto
- [docs/UX_TELEGRAM_GUIDELINES.md](docs/UX_TELEGRAM_GUIDELINES.md) - Boas práticas de UX
- [docs/CHANGELOG_SPRINT5.md](docs/CHANGELOG_SPRINT5.md) - Mudanças da Sprint 5
- [docs/README_TELEGRAM.md](docs/README_TELEGRAM.md) - Integração Telegram detalhada

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
