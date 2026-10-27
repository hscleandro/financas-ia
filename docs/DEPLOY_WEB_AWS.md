# Deploy da aplicação web Finanças IA na AWS

Este documento descreve como hospedar a interface web do Finanças IA junto com o bot Telegram na mesma instância AWS (provavelmente Lightsail), sem interromper o bot.

## 1. Pré-requisitos

- Instância AWS Lightsail (ou EC2) já operando o bot Telegram
- Domínio ou subdomínio apontando para o IP da instância (opcional, mas necessário para HTTPS)
- Acesso SSH à instância
- Arquivo `.env` configurado com `WEB_AUTH_PASSWORD` e `WEB_SESSION_SECRET`

## 2. Verificação da instância atual

Antes de instalar, verifique:

```bash
# CPU e memória livres
free -h
top

# Espaço em disco
df -h

# Processos do bot em execução
ps aux | grep -E "(main_telegram_polling|financas-bot)"

# Portas em uso
ss -tlnp | grep -E "(8000|8080|443|80)"
```

Requisitos mínimos estimados:
- 512 MB RAM livre (SQLite + FastAPI é leve)
- 2 GB de disco livre
- Porta 8080 (ou outra) disponível

## 3. Arquitetura de processos

Recomenda-se rodar três processos independentes:

1. **Bot Telegram** (polling ou webhook) — já existente
2. **Aplicação web** — `uvicorn web.main:app`
3. **Proxy reverso** — Nginx ou Caddy (recomendado: Caddy por facilitar HTTPS)

## 4. Configuração local (mesmo servidor)

### 4.1. Variáveis de ambiente

Adicione ao `.env` existente:

```bash
WEB_AUTH_PASSWORD=senha-forte-aqui
WEB_SESSION_SECRET=segredo-aleatorio-longo-aqui
WEB_PORT=8080
```

### 4.2. Iniciar a aplicação web

```bash
source venv/bin/activate
uvicorn web.main:app --host 127.0.0.1 --port 8080
```

Ou em background:

```bash
nohup uvicorn web.main:app --host 127.0.0.1 --port 8080 > /tmp/financas-web.log 2>&1 &
```

### 4.3. Testar localmente

```bash
curl http://127.0.0.1:8080/login
```

## 5. Proxy reverso e HTTPS

### Opção A: Caddy (recomendado)

Caddy configura HTTPS automaticamente via Let's Encrypt.

1. Instale o Caddy:

```bash
sudo apt update
sudo apt install -y caddy
```

2. Configure `/etc/caddy/Caddyfile`:

```
seu-dominio.com {
    reverse_proxy 127.0.0.1:8080
}

# Se o bot usa webhook na porta 8000, adicione:
# webhook.seu-dominio.com {
#     reverse_proxy 127.0.0.1:8000
# }
```

3. Reinicie:

```bash
sudo systemctl reload caddy
```

4. Configure o DNS do seu domínio para o IP público da instância.

### Opção B: Nginx + Certbot

1. Instale Nginx e Certbot:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

2. Configure `/etc/nginx/sites-available/financas-ia`:

```nginx
server {
    listen 80;
    server_name seu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

3. Ative e gere o certificado:

```bash
sudo ln -s /etc/nginx/sites-available/financas-ia /etc/nginx/sites-enabled/
sudo certbot --nginx -d seu-dominio.com
sudo systemctl reload nginx
```

## 6. Persistência com systemd

Crie `/etc/systemd/system/financas-web.service`:

```ini
[Unit]
Description=Financas IA Web
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/financas-ia
Environment="PATH=/home/ubuntu/financas-ia/venv/bin"
ExecStart=/home/ubuntu/financas-ia/venv/bin/uvicorn web.main:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Ative:

```bash
sudo systemctl daemon-reload
sudo systemctl enable financas-web
sudo systemctl start financas-web
sudo systemctl status financas-web
```

## 7. Deploy e rollback

### Deploy simples

```bash
cd /home/ubuntu/financas-ia
git pull origin feature/web-v1
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart financas-web
```

### Rollback

```bash
git checkout <commit-anterior>
sudo systemctl restart financas-web
```

## 8. Segurança

- **Nunca exponha o banco SQLite diretamente** na internet.
- A aplicação web deve rodar em `127.0.0.1:8080` (ou porta local), acessível apenas via proxy reverso.
- Use `WEB_AUTH_PASSWORD` forte (mínimo 16 caracteres).
- Mantenha `WEB_SESSION_SECRET` aleatório e segredo.
- Não coloque credenciais em logs nem em repositório público.

## 9. Monitoramento

```bash
# Logs da aplicação web
journalctl -u financas-web -f

# Logs do bot (se já existir)
tail -f /tmp/telegram_bot.log

# Saúde da aplicação
curl -k https://seu-dominio.com/login
```

## 10. Custos

- **Mesma instância Lightsail**: sem custo adicional.
- **Novo domínio**: ~USD 10-15/ano (se não tiver).
- **Caddy/Nginx + Let's Encrypt**: gratuito.

Se a instância atual não suportar (RAM < 512 MB), considere:
- Upgrade do plano Lightsail (~USD 5-10/mês)
- Migrar para EC2 t3.micro (~USD 7-10/mês) com monitoramento

**Não contrate novos recursos sem autorização do usuário.**
