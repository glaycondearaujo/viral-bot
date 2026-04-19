# 🚀 Viral Engine Bot — Versão Honesta com Cookies Autenticados

## ⚠️ Leia isso antes de tudo

Este bot tenta extrair vídeos da Shopee **sem marca d'água** usando 3 estratégias em cascata com seus cookies autenticados da Shopee. **Não há garantia de 100% de sucesso** na remoção da marca d'água porque a Shopee aplica a marca no servidor. O bot **sempre avisa honestamente** se conseguiu ou não remover, em vez de fingir sucesso.

## Como o bot funciona

Quando você envia um link da Shopee, o bot executa em cascata:

1. **Estratégia 1 — API Mobile Autenticada.** Tenta 6 endpoints internos da Shopee com seus cookies + headers de app Android. Se algum retornar a URL original do CDN, baixa direto.
2. **Estratégia 2 — Playwright Autenticado.** Se a API falhar, abre Chromium com seus cookies injetados, navega até a página do vídeo e intercepta as requisições MP4 no CDN Shopee.
3. **Pós-processamento.** Detecta e corta o endcard vermelho. Analisa pixels do canto do vídeo para verificar se a marca d'água está presente.
4. **Envio honesto.** Na legenda do vídeo enviado ao Telegram, o bot informa: método usado, se endcard foi cortado e se marca d'água foi detectada ou não.

Para TikTok, Instagram, YouTube, Kwai e outras plataformas, funciona normalmente via APIs e yt-dlp.

## Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `bot.py` | Bot Telegram principal, roteia plataformas, gerencia callbacks |
| `shopee_extractor.py` | 3 estratégias Shopee + detecção de marca d'água |
| `engine.py` | Legendas + hashtags focadas no produto |
| `Dockerfile` | Imagem com Playwright 1.58 + ffmpeg |
| `requirements.txt` | Dependências Python |
| `render.yaml` | Config do Render |
| `shopee_cookies.txt` | **Seus cookies autenticados da Shopee (já incluído)** |

## Deploy no Render — passo a passo

### 1. Criar repositório no GitHub

Crie um repositório **NOVO** (não reutilize o antigo — este é um projeto diferente).

Faça upload destes 7 arquivos:
- `bot.py`
- `engine.py`
- `shopee_extractor.py`
- `Dockerfile`
- `requirements.txt`
- `render.yaml`
- `shopee_cookies.txt`

### 2. Deploy no Render

1. Entre em https://render.com
2. Clique em **"New +"** → **"Web Service"**
3. Conecte seu repositório GitHub
4. O Render detecta o `render.yaml` automaticamente
5. Confirme o plano **Standard ($25/mês, 2GB RAM)** — recomendado
6. Clique em **"Create Web Service"**

### 3. Configurar o token do Telegram

1. No dashboard do Render, vá em **"Environment"**
2. Adicione: `TELEGRAM_BOT_TOKEN` com o token do seu bot (criado no @BotFather)
3. Salve — o Render redeploya automaticamente

### 4. Aguardar o build

- ⏱ **Primeiro build: 10-15 minutos** (imagem do Playwright é ~1.5GB)
- Quando aparecer `🚀 Viral Engine Bot (versão honesta) rodando!` + `Cookies: ✅ encontrados` nos logs, está no ar

### 5. Testar no Telegram

Envie um link da Shopee (`https://br.shp.ee/...`) para o bot. Aguarde 30-60s. O bot vai responder com:
- O vídeo baixado
- Legenda indicando se tem marca d'água ou não, método usado, e se endcard foi cortado
- Mensagem com hashtags focadas no produto + 3 variações

## Manutenção dos cookies

**Seus cookies atuais expiram por volta de fim de junho/2026** (cookies `SPC_EC` e `SPC_ST`). Quando isso acontecer:

1. Extensão recomendada: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. Faça login em shopee.com.br pelo navegador
3. Com a extensão, exporte os cookies do domínio shopee.com.br no formato Netscape
4. Substitua o arquivo `shopee_cookies.txt` no repositório GitHub
5. O Render redeploya automaticamente

## Riscos e limitações

**Remoção de marca d'água não é garantida.** A Shopee aplica a marca no servidor antes de enviar o vídeo. A única maneira de pegar o vídeo original limpo é via API interna do app mobile, que usa assinatura criptográfica HMAC que muda a cada versão do app. Seus cookies autenticados **aumentam a chance** de sucesso porque abrem acesso a alguns endpoints internos, mas **não garantem 100%**.

**Risco de banimento da sua conta Shopee.** Usar cookies autenticados para scraping automatizado pode violar os Termos de Uso da Shopee. Para uso moderado (20-50 downloads/dia), o risco é baixo. Evite picos de uso.

**Cookies expiram e precisam ser atualizados.** Conforme descrito acima, a cada ~2 meses.

## Comandos do bot

- `/start` — mensagem de boas-vindas com status de cookies
- `/debug` — últimos 60 logs técnicos (envie se algo der errado)

## Troubleshooting

### "Shopee não baixa nenhum vídeo"
Envie `/debug` no bot. Os logs vão mostrar qual estratégia está falhando:
- `STRAT1[resp]: 401` ou `403` → cookies expiraram, exporte novos
- `STRAT2: nenhum vídeo interceptado` → Shopee mudou o player, me envie o log completo

### "Vídeo veio com marca d'água"
Isso acontece quando a estratégia 1 (API mobile) falha e caímos no Playwright. Nesse caso, a legenda já avisa: "⚠️ Marca d'água presente". Os concorrentes (SVDown, @achadoshdfreebot) podem funcionar melhor porque usam infraestrutura dedicada (proxies residenciais, app mobile simulado com assinatura HMAC, etc.).

### "Copiar legenda não funciona"
Foi corrigido nesta versão. O estado dos callbacks agora é persistido em arquivo (`/tmp/vbot/user_state.json`) e sobrevive a restart do bot. Se ainda não funcionar, envie `/debug` e me mostre o log do callback.

### "Hashtags não estão relacionadas ao produto"
Isso acontece quando o Playwright não consegue ler o título do vídeo via `meta[og:title]`. O fallback é gerar hashtags genéricas. A solução é garantir que a estratégia 1 ou 2 capture os metadados — o que depende dos cookies estarem válidos.

## Consumo estimado

- RAM idle: ~200MB
- RAM durante Shopee (Chromium aberto): 600-900MB
- CPU durante extração: 20-40% por 30-60s
- Custo Render Standard: $25/mês fixo

## Versionamento

Esta é a **versão honesta v1.0** (abril 2026). As mudanças principais em relação às versões anteriores:

- ✅ 3 estratégias em cascata com cookies autenticados
- ✅ Detecção de marca d'água via análise de pixels (YMAX/YAVG)
- ✅ Detecção e corte de endcard vermelho da Shopee
- ✅ Callbacks corrigidos com persistência em arquivo
- ✅ Aviso honesto na legenda do vídeo quando marca d'água não é removida
- ✅ Hashtags 100% focadas no produto (zero plataformas)
- ✅ Metadados extraídos do DOM (título, criador) para hashtags relevantes
- ✅ Debug detalhado via `/debug`
