# 🚀 Viral Engine Bot — Deploy no Render

## O que esse bot faz

- **Shopee Video**: baixa vídeos SEM marca d'água via Playwright (Chromium headless)
- **TikTok**: via TikWM API (sem marca d'água)
- **Instagram**: Reels via embed scraping
- **YouTube, Kwai, X, Pinterest, Facebook**: via yt-dlp
- Legenda + hashtags focadas no PRODUTO REAL extraído do vídeo

---

## ⚠️ Escolha do plano Render

**Render Free (0$)** → ❌ NÃO funciona. Só tem 512MB de RAM e o Chromium usa 500MB-1GB.

**Render Starter ($7/mês)** → ⚠️ Funciona apertado. 512MB. Configurei `--single-process` no Chromium pra caber. Pode crashar em picos de uso.

**Render Standard ($25/mês)** → ✅ Recomendado. 2GB RAM, sem problemas.

O `render.yaml` vem configurado com `plan: standard`. Se for usar Starter, mude para `plan: starter` no arquivo.

---

## 📦 Passo a passo do deploy

### Passo 1: GitHub
1. Crie um repositório NOVO (ex: `viral-bot-render`)
2. Faça upload destes 7 arquivos:
   - `bot.py`
   - `engine.py`
   - `shopee_extractor.py`
   - `Dockerfile`
   - `requirements.txt`
   - `render.yaml`
   - `README.md`

### Passo 2: Render
1. Entre em https://render.com
2. Clique em **"New +"** → **"Web Service"**
3. Conecte seu repositório GitHub
4. Render detecta o `render.yaml` automaticamente
5. Confirme o plano (Standard recomendado)
6. Clique em **"Create Web Service"**

### Passo 3: Configurar o token
1. No Render, vá em **"Environment"** (menu lateral)
2. Adicione: `TELEGRAM_BOT_TOKEN` = seu token do @BotFather
3. Clique em **"Save Changes"** — o Render redeploya automaticamente

### Passo 4: Aguardar o build
- ⏱ **Primeiro build: ~10-15 minutos** (baixa imagem do Playwright com Chromium)
- Builds seguintes: ~3-5 min
- Acompanhe em **"Logs"** — quando aparecer `🚀 Viral Engine Bot rodando!`, está no ar

### Passo 5: Manter sempre ativo (UptimeRobot)
Render Starter/Standard não "dormem" como o Free, mas configure UptimeRobot como garantia:
1. https://uptimerobot.com (gratuito)
2. Crie um monitor HTTP(s)
3. URL: `https://seu-bot.onrender.com` (aparece no dashboard Render)
4. Intervalo: 5 minutos

---

## 🔧 Comandos do bot

- `/start` — boas-vindas
- `/debug` — últimos 60 logs técnicos (envie se algo der errado)

---

## 🐛 Se der erro

### "Shopee não baixa"
1. Envie `/debug` no bot
2. Procure nas últimas linhas por `PW:` (logs do Playwright)
3. Cenários comuns:
   - `PW: não capturou vídeo` → Shopee mudou o player, me envie o log
   - `OOM killed` nos logs do Render → Upgrade pra Standard (2GB)
   - `Timeout navegação` → Shopee lento ou rede travou, tente de novo

### "Build falha no Render"
- O Docker do Playwright é grande (~1.5GB). Render precisa de disco suficiente
- Se falhar por espaço, tente o plano Standard

### "Bot muito lento na Shopee"
- 15-40s é NORMAL. O navegador precisa: abrir → carregar página → esperar JS → interceptar
- TikTok/Instagram continuam instantâneos (usam APIs diretas)

---

## 💡 Como funciona a extração Shopee

1. Bot recebe link `https://s.shopee.com.br/...`
2. Abre Chromium headless simulando celular Android
3. Navega para a página da Shopee Video
4. **Intercepta TODOS os requests de rede**
5. Filtra: `.mp4` + CDN Shopee (`susercontent.com`) + não é thumbnail
6. Pega URL do vídeo ORIGINAL (antes da marca d'água ser aplicada pelo player)
7. Lê o título do produto via `meta[og:title]`
8. Baixa o MP4 direto do CDN
9. Gera hashtags específicas baseadas no título REAL

Isso é igual ao que o SVDown faz — rodando no seu servidor.

---

## 📊 Consumo estimado

| Recurso | Idle | Durante Shopee | Outras plataformas |
|---------|------|----------------|--------------------|
| RAM     | 200MB | 600-900MB     | 300MB              |
| CPU     | 0.1% | 20-40% (15-30s)| Baixo             |

**Custo mensal estimado:**
- Starter: $7/mês fixo
- Standard: $25/mês fixo
- (Render cobra por tempo ativo, não por uso)

---

## 📝 Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `bot.py` | Servidor Telegram, handlers, roteamento |
| `shopee_extractor.py` | Extração via Playwright (Chromium) |
| `engine.py` | Geração de legendas + hashtags do produto |
| `Dockerfile` | Imagem Docker com Playwright + ffmpeg |
| `requirements.txt` | Dependências Python |
| `render.yaml` | Config do Render |

---

## ✅ Checklist pré-deploy

- [ ] Token do bot criado no @BotFather
- [ ] Conta no Render (com cartão se escolher plano pago)
- [ ] Repositório GitHub com os 7 arquivos
- [ ] Plano escolhido (Starter ou Standard)
- [ ] Região escolhida no render.yaml (oregon padrão)
