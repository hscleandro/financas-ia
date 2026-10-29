#!/bin/bash
set -e

# Script de deploy para Amazon Lightsail
# Subir web, bot e nginx com Docker Compose

echo "🚀 Iniciando deploy do Finanças IA Web no Lightsail..."

# 1. Backup do banco de dados
echo "📦 Fazendo backup do banco de dados..."
mkdir -p ~/backups
cp data/financas.db ~/backups/financas.db.$(date +%Y%m%d_%H%M%S).bak 2>/dev/null || echo "⚠️  financas.db não encontrado para backup"
cp data/checkpoints.db ~/backups/checkpoints.db.$(date +%Y%m%d_%H%M%S).bak 2>/dev/null || echo "⚠️  checkpoints.db não encontrado para backup"

# 2. Atualizar código
echo "📥 Atualizando código da branch main..."
git checkout main
git pull origin main

# 3. Verificar variáveis de ambiente necessárias
echo "🔍 Verificando variáveis de ambiente..."
REQUIRED_VARS="OPENAI_API_KEY TELEGRAM_BOT_TOKEN WEB_AUTH_PASSWORD WEB_SESSION_SECRET"
MISSING=0
for var in $REQUIRED_VARS; do
    if [ -z "${!var}" ]; then
        echo "❌ ERRO: Variável $var não está definida no .env"
        MISSING=1
    fi
done

if [ $MISSING -eq 1 ]; then
    echo "Por favor, defina as variáveis acima no arquivo .env e tente novamente."
    exit 1
fi

# 4. Parar containers antigos
echo "🛑 Parando containers antigos..."
docker-compose down

# 5. Subir novos containers
echo "▶️  Subindo bot, web e nginx..."
docker-compose up -d --build

# 6. Aguardar web subir
echo "⏳ Aguardando web iniciar..."
for i in {1..30}; do
    if curl -sf http://127.0.0.1:8080/login > /dev/null 2>&1; then
        echo "✅ Web está respondendo na porta 8080"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "⚠️  Web não respondeu a tempo. Verifique os logs com: docker-compose logs financas-web"
    fi
    sleep 1
done

# 7. Status final
echo ""
echo "🎉 Deploy finalizado!"
echo ""
echo "Acesse o dashboard em: http://$(curl -s ifconfig.me)/"
echo ""
echo "Comandos úteis:"
echo "  docker-compose logs -f financas-web   # logs da web"
echo "  docker-compose logs -f financas-bot   # logs do bot"
echo "  docker-compose logs -f nginx          # logs do nginx"
echo "  docker-compose ps                     # status dos containers"
