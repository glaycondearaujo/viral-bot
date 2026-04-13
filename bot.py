"""
Viral Engine Bot — Telegram Bot para Afiliados
Baixa vídeos + gera legendas e hashtags virais.

Plataformas com download:
  ✅ YouTube / Shorts
  ✅ TikTok (público)
  ✅ Twitter / X
  ✅ Pinterest
  ✅ Facebook (público)
  ✅ Kwai
  ⚠️ Instagram (limitado — posts públicos, reels pode falhar)

Uso: TELEGRAM_BOT_TOKEN=xxx python bot.py
"""

import os, re, logging, asyncio, subprocess, tempfile, time, json, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction
from engine import generate, detect_platform, is_link, PLAT_NAMES, PLAT_EMOJI

# ════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", "10000"))
TMP = Path(tempfile.gettempdir()) / "vbot"
TMP.mkdir(exist_ok=True)
STATS = TMP / "stats.json"
MAX_SIZE = 49 * 1024 * 1024

VIDEO_PLATFORMS = {"tiktok","youtube","twitter","pinterest","facebook","kwai","instagram","threads"}

SUPPORT_STATUS = {
    "youtube":   ("✅", "Funciona"),
    "tiktok":    ("✅", "Funciona (vídeos públicos)"),
    "twitter":   ("✅", "Funciona"),
    "pinterest": ("✅", "Funciona"),
    "facebook":  ("✅", "Funciona (vídeos públicos)"),
    "kwai":      ("✅", "Funciona"),
    "instagram": ("⚠️", "Limitado (alguns reels públicos)"),
    "threads":   ("⚠️", "Limitado"),
    "shopee":    ("📝", "Só conteúdo viral"),
    "mercadolivre": ("📝", "Só conteúdo viral"),
}


# ════════════════════════════════════════════════════
# STARTUP — atualiza yt-dlp para última versão
# ════════════════════════════════════════════════════
def update_ytdlp():
    """Atualiza yt-dlp para a versão mais recente na inicialização."""
    try:
        log.info("Atualizando yt-dlp...")
        r = subprocess.run(
            ["pip", "install", "--upgrade", "--break-system-packages", "yt-dlp"],
            capture_output=True, timeout=120
        )
        if r.returncode == 0:
            # Verificar versão
            v = subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=10)
            log.info(f"yt-dlp atualizado: {v.stdout.decode().strip()}")
        else:
            log.warning(f"Falha ao atualizar yt-dlp: {r.stderr.decode()[:200]}")
    except Exception as e:
        log.warning(f"Erro update yt-dlp: {e}")


# ════════════════════════════════════════════════════
# HEALTH SERVER (mantém Render acordado)
# ════════════════════════════════════════════════════
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        s = load_stats()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            f"<h2>Viral Engine Bot — Online</h2>"
            f"<p>Downloads: {s.get('downloads',0)} | "
            f"Usuários: {len(s.get('users',[]))}</p>".encode()
        )
    def log_message(self, *a): pass

def start_http():
    HTTPServer(("0.0.0.0", PORT), Health).serve_forever()


# ════════════════════════════════════════════════════
# STATS
# ════════════════════════════════════════════════════
def load_stats():
    try:
        return json.loads(STATS.read_text()) if STATS.exists() else {"downloads":0,"users":[]}
    except:
        return {"downloads":0,"users":[]}

def save_stats(s):
    try: STATS.write_text(json.dumps(s))
    except: pass

def track(uid):
    s = load_stats()
    s["downloads"] = s.get("downloads",0)+1
    if uid not in s.get("users",[]): s.setdefault("users",[]).append(uid)
    save_stats(s)


# ════════════════════════════════════════════════════
# DOWNLOAD — config específica por plataforma
# ════════════════════════════════════════════════════
def get_ytdlp_cmd(url: str, platform: str | None, output: str) -> list:
    """Monta comando yt-dlp otimizado por plataforma."""
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "--no-check-certificates",
        "--max-filesize", "49m",
        "--socket-timeout", "30",
        "--retries", "5",
        "--fragment-retries", "5",
        "--extractor-retries", "3",
        "-f", "best[ext=mp4][filesize<49M]/best[ext=mp4]/best[filesize<49M]/best",
        "--merge-output-format", "mp4",
        "-o", output,
        "--print", "after_move:filepath",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]

    if platform == "tiktok":
        cmd += [
            "--add-header", "Referer:https://www.tiktok.com/",
            "--add-header", "Accept-Language:pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        ]
    elif platform == "instagram":
        cmd += [
            "--add-header", "Referer:https://www.instagram.com/",
            "--add-header", "Accept-Language:pt-BR,pt;q=0.9",
        ]
    elif platform == "twitter":
        cmd += [
            "--add-header", "Referer:https://twitter.com/",
        ]
    elif platform == "pinterest":
        cmd += [
            "--add-header", "Referer:https://www.pinterest.com/",
        ]
    elif platform == "kwai":
        cmd += [
            "--add-header", "Referer:https://www.kwai.com/",
        ]

    cmd.append(url)
    return cmd


async def download_video(url: str, platform: str | None = None) -> tuple[str | None, str | None]:
    """Baixa vídeo. Retorna (filepath, erro) — um dos dois é None."""
    uid = f"{int(time.time())}_{os.getpid()}"
    out = str(TMP / f"{uid}.%(ext)s")
    cmd = get_ytdlp_cmd(url, platform, out)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)

        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp):
                log.info(f"OK: {fp} ({os.path.getsize(fp)//1024}KB)")
                return fp, None

        err = stderr.decode()
        # Diagnóstico do erro
        if "login" in err.lower() or "cookie" in err.lower() or "authentication" in err.lower():
            return None, "auth"
        elif "not available" in err.lower() or "private" in err.lower():
            return None, "private"
        elif "geo" in err.lower() or "country" in err.lower():
            return None, "geo"
        elif "filesize" in err.lower():
            return None, "size"
        else:
            log.warning(f"yt-dlp erro: {err[:300]}")
            return None, "unknown"

    except asyncio.TimeoutError:
        return None, "timeout"
    except Exception as e:
        log.error(f"Erro: {e}")
        return None, "crash"


def strip_meta(src: str) -> str:
    """Remove metadados com ffmpeg."""
    dst = src.rsplit(".",1)[0] + "_c.mp4"
    try:
        r = subprocess.run([
            "ffmpeg","-y","-i",src,
            "-map_metadata","-1","-fflags","+bitexact",
            "-flags:v","+bitexact","-flags:a","+bitexact",
            "-c","copy",dst
        ], capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst):
            return dst
    except: pass
    return src


async def extract_mp3(src: str) -> str | None:
    dst = src.rsplit(".",1)[0] + ".mp3"
    try:
        r = subprocess.run([
            "ffmpeg","-y","-i",src,"-vn","-acodec","libmp3lame",
            "-q:a","2","-map_metadata","-1",dst
        ], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return None


def cleanup(*p):
    for f in p:
        try:
            if f and os.path.exists(f): os.remove(f)
        except: pass


# ════════════════════════════════════════════════════
# MENSAGENS DE ERRO (humanizadas)
# ════════════════════════════════════════════════════
ERROR_MSGS = {
    "auth": (
        "🔒 *Vídeo requer autenticação*\n\n"
        "A plataforma exige login para acessar este conteúdo\\.\n"
        "Isso é comum no Instagram e em vídeos privados\\.\n\n"
        "💡 *Dica:* tente com vídeos públicos ou use o SVDown "
        "\\(svdown\\.tech\\) para Instagram\\."
    ),
    "private": (
        "🔒 *Vídeo privado ou indisponível*\n\n"
        "Este conteúdo é privado ou foi removido\\."
    ),
    "geo": (
        "🌍 *Vídeo com restrição geográfica*\n\n"
        "Não está disponível na região do servidor\\."
    ),
    "size": (
        "📦 *Vídeo muito grande*\n\n"
        "Excede o limite de 50MB do Telegram\\."
    ),
    "timeout": (
        "⏱ *Tempo esgotado*\n\n"
        "O download demorou demais\\. Tente novamente\\."
    ),
    "unknown": (
        "⚠️ *Não consegui baixar*\n\n"
        "A plataforma pode ter bloqueado ou o link é inválido\\.\n"
        "Tente outro link ou verifique se o vídeo é público\\."
    ),
    "crash": (
        "❌ *Erro interno*\n\n"
        "Algo deu errado\\. Tente novamente\\."
    ),
}


# ════════════════════════════════════════════════════
# TELEGRAM FORMATTING
# ════════════════════════════════════════════════════
def esc(t): return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(t))

def build_msgs(data):
    msgs = []
    L = ["📝 *LEGENDAS*"]
    if data["platform_name"]:
        L.append(f"{esc(data['platform_emoji'])} {esc(data['platform_name'])} \\| 📁 {esc(data['cat_label'])}")
    L.append("─"*25)
    for t,l in data["legendas"].items():
        L.append(f"\n*{esc(t)}*\n{esc(l)}")
    msgs.append("\n".join(L))

    L = ["🏷 *HASHTAGS*\n"]
    for g,tags in data["hashtags"].items():
        L.append(f"*{esc(g)}*\n{esc(' '.join(tags))}\n")
    L.append(f"📋 *COPIAR TUDO:*\n{esc(data['all_tags'])}")
    msgs.append("\n".join(L))

    L = ["⚡ *HOOKS*\n"]
    for i,h in enumerate(data["hooks"]):
        L.append(f"*{i+1}\\.* {esc(h)}")
    msgs.append("\n".join(L))
    return msgs

def quick_copy(data):
    return f"{list(data['legendas'].values())[0]}\n\n{data['all_tags']}"


# ════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_stats()
    await update.message.reply_text(
        "🚀 *Viral Engine Bot*\n\n"
        "Baixe vídeos sem marca d'água \\+ legendas e hashtags virais\\.\n\n"
        "*Cole um link de vídeo:*\n"
        "✅ YouTube \\| TikTok \\| Twitter/X \\| Pinterest \\| Facebook \\| Kwai\n"
        "⚠️ Instagram \\(limitado a posts públicos\\)\n\n"
        "*Ou cole um link de produto / nome:*\n"
        "🛒 Shopee \\| Mercado Livre \\| qualquer produto\n"
        "→ Gero legendas, hashtags e hooks virais\n\n"
        f"📊 {esc(str(s.get('downloads',0)))} downloads \\| "
        f"{esc(str(len(s.get('users',[]))))} usuários\n\n"
        "Manda o link\\! 👇",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Comandos*\n\n"
        "/start \\— Iniciar\n"
        "/plataformas \\— Ver status por plataforma\n"
        "/stats \\— Estatísticas\n\n"
        "Ou envie qualquer *link* ou *nome de produto*\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def cmd_plataformas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["🌐 *Plataformas*\n"]
    for k, name in PLAT_NAMES.items():
        emoji = PLAT_EMOJI.get(k,"🔗")
        status_emoji, status_text = SUPPORT_STATUS.get(k, ("❓","Desconhecido"))
        lines.append(f"{emoji} *{esc(name)}* {status_emoji} {esc(status_text)}")
    lines.append(f"\n_Atualizado com yt\\-dlp mais recente_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_stats()
    await update.message.reply_text(
        f"📊 Downloads: *{esc(str(s.get('downloads',0)))}*\n"
        f"👥 Usuários: *{esc(str(len(s.get('users',[]))))}*",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text or len(text) < 2: return

    uid = update.effective_user.id
    link_m = re.search(r'https?://\S+', text)
    link = link_m.group(0) if link_m else None
    plat = detect_platform(link) if link else None
    can_dl = plat in VIDEO_PLATFORMS

    if link and can_dl:
        pn = PLAT_NAMES.get(plat, "plataforma")
        pe = PLAT_EMOJI.get(plat, "🔗")

        status = await update.message.reply_text(
            f"{pe} *{esc(pn)}* detectado\n⏳ Baixando\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        filepath, err = await download_video(link, plat)
        clean = None
        audio = None

        if filepath:
            await status.edit_text("🧹 Limpando metadados\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            clean = strip_meta(filepath)
            final = clean if clean != filepath else filepath

            if os.path.getsize(final) <= MAX_SIZE:
                await status.edit_text("📤 Enviando\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption=f"✅ Sem marca d'água · sem metadados\n{pe} {pn}",
                            read_timeout=120, write_timeout=120,
                        )
                    track(uid)
                except Exception as e:
                    log.error(f"Envio: {e}")
                    await update.message.reply_text("⚠️ Erro ao enviar. Tente novamente.")
            else:
                await status.edit_text(ERROR_MSGS["size"], parse_mode=ParseMode.MARKDOWN_V2)

            audio = await extract_mp3(filepath)
            cleanup(filepath)
            if clean != filepath: cleanup(clean)
        else:
            # Mostrar erro específico
            err_msg = ERROR_MSGS.get(err, ERROR_MSGS["unknown"])
            await status.edit_text(err_msg, parse_mode=ParseMode.MARKDOWN_V2)

        # Gerar conteúdo viral sempre
        await asyncio.sleep(0.5)
        data = generate(link)
        for m in build_msgs(data):
            await update.message.reply_text(m, parse_mode=ParseMode.MARKDOWN_V2)
            await asyncio.sleep(0.3)

        ctx.user_data["qc"] = quick_copy(data)
        ctx.user_data["last"] = text

        btns = [[InlineKeyboardButton("📋 Copiar Legenda + Hashtags", callback_data="copy")]]
        if audio and os.path.exists(audio):
            ctx.user_data["audio"] = audio
            btns.append([InlineKeyboardButton("🎵 Baixar MP3", callback_data="audio")])
        btns.append([InlineKeyboardButton("🔄 Gerar Novamente", callback_data="regen")])

        await update.message.reply_text(
            "✅ *Pronto\\!*",
            reply_markup=InlineKeyboardMarkup(btns),
            parse_mode=ParseMode.MARKDOWN_V2
        )

    else:
        await update.message.reply_chat_action(ChatAction.TYPING)
        data = generate(link or text)
        for m in build_msgs(data):
            await update.message.reply_text(m, parse_mode=ParseMode.MARKDOWN_V2)
            await asyncio.sleep(0.3)

        ctx.user_data["qc"] = quick_copy(data)
        ctx.user_data["last"] = text
        await update.message.reply_text(
            "✅ *Pronto\\!*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copiar Legenda + Hashtags", callback_data="copy")],
                [InlineKeyboardButton("🔄 Gerar Novamente", callback_data="regen")],
            ]),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        track(uid)


async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "copy":
        qc = ctx.user_data.get("qc","")
        if qc: await q.message.reply_text(qc)
    elif q.data == "audio":
        a = ctx.user_data.get("audio")
        if a and os.path.exists(a):
            try:
                with open(a,"rb") as f:
                    await q.message.reply_audio(audio=f, caption="🎵 MP3")
            except: pass
            finally: cleanup(a)
    elif q.data == "regen":
        last = ctx.user_data.get("last","")
        if last:
            data = generate(last)
            await q.message.reply_text(quick_copy(data))


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start","Iniciar"),
        BotCommand("help","Ajuda"),
        BotCommand("plataformas","Plataformas suportadas"),
        BotCommand("stats","Estatísticas"),
    ])


# ════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════
def main():
    if not TOKEN:
        print("❌ Configure TELEGRAM_BOT_TOKEN")
        print("  export TELEGRAM_BOT_TOKEN='seu_token'")
        return

    # Atualizar yt-dlp antes de iniciar
    update_ytdlp()

    # Health server (Render)
    threading.Thread(target=start_http, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plataformas", cmd_plataformas))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_handler(CallbackQueryHandler(handle_cb))

    log.info("🚀 Bot rodando!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
