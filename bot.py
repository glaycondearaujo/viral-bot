"""
Viral Engine Bot — Versão Honesta
- Shopee: 3 estratégias + cookies autenticados + aviso de marca d'água
- Callbacks funcionando (use_context + persistência de state)
- Hashtags focadas no produto
"""

import os
import re
import logging
import asyncio
import subprocess
import tempfile
import time
import json
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import deque
import requests as req

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, PicklePersistence
)
from telegram.constants import ParseMode, ChatAction

from engine import generate, detect_platform, can_download
from shopee_extractor import download_shopee

# ══════════════════════════════════════════════════════════════
# Logging com buffer
# ══════════════════════════════════════════════════════════════

DEBUG_LOGS = deque(maxlen=120)

class BufferHandler(logging.Handler):
    def emit(self, record):
        try: DEBUG_LOGS.append(self.format(record))
        except: pass

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
_buf = BufferHandler(); _buf.setFormatter(_fmt); _buf.setLevel(logging.INFO)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
for name in ("bot", "shopee_extractor"):
    logging.getLogger(name).addHandler(_buf)
log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", "10000"))
COOKIES_PATH = os.environ.get("SHOPEE_COOKIES_PATH", "/app/shopee_cookies.txt")

TMP = Path(tempfile.gettempdir()) / "vbot"
TMP.mkdir(exist_ok=True)
STATS = TMP / "stats.json"
STATE = TMP / "user_state.json"  # persistência dos callbacks

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


# ══════════════════════════════════════════════════════════════
# Persistência de estado dos callbacks (arquivo)
# ══════════════════════════════════════════════════════════════

_state_lock = threading.Lock()

def load_state() -> dict:
    try:
        if STATE.exists():
            return json.loads(STATE.read_text())
    except: pass
    return {}

def save_state(state: dict):
    try:
        with _state_lock:
            STATE.write_text(json.dumps(state))
    except Exception as e:
        log.error(f"save_state erro: {e}")

def set_user_data(uid: int, data: dict):
    """Salva dados do usuário em arquivo (sobrevive a restart)."""
    state = load_state()
    state[str(uid)] = data
    save_state(state)

def get_user_data(uid: int) -> dict:
    state = load_state()
    return state.get(str(uid), {})


# ══════════════════════════════════════════════════════════════
# Health server
# ══════════════════════════════════════════════════════════════

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

def start_http():
    HTTPServer(("0.0.0.0", PORT), Health).serve_forever()


# ══════════════════════════════════════════════════════════════
# Stats
# ══════════════════════════════════════════════════════════════

def load_s():
    try: return json.loads(STATS.read_text()) if STATS.exists() else {"d": 0, "u": []}
    except: return {"d": 0, "u": []}

def save_s(s):
    try: STATS.write_text(json.dumps(s))
    except: pass

def track(uid):
    s = load_s(); s["d"] = s.get("d", 0) + 1
    if uid not in s.get("u", []): s.setdefault("u", []).append(uid)
    save_s(s)


def update_ytdlp():
    try:
        subprocess.run(["pip", "install", "--upgrade", "--break-system-packages", "yt-dlp"],
                       capture_output=True, timeout=120)
    except: pass


# ══════════════════════════════════════════════════════════════
# Download de plataformas que não são Shopee
# ══════════════════════════════════════════════════════════════

def _save_bytes(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp

def _dl_url(url, headers=None, min_size=30000):
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        r = req.get(url, headers=h, timeout=180, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > min_size:
            return r.content
    except Exception as e:
        log.warning(f"_dl: {e}")
    return None


async def dl_tiktok(url):
    for ep in ["https://www.tikwm.com/api/", "https://tikwm.com/api/"]:
        try:
            r = req.post(ep, data={"url": url, "hd": 1}, headers={"User-Agent": UA}, timeout=30)
            d = r.json()
            if d.get("code") == 0 and d.get("data"):
                u = d["data"].get("hdplay") or d["data"].get("play")
                title = d["data"].get("title", "")
                if u:
                    c = _dl_url(u, {"User-Agent": "okhttp"})
                    if c:
                        return _save_bytes(c, "tt"), {"title": title, "caption": title}
        except Exception as e:
            log.warning(f"TikWM: {e}")
    fp = await dl_ytdlp(url, "tiktok")
    return fp, None


async def dl_instagram(url):
    try:
        m = re.search(r"/(p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
        if m:
            sc = m.group(2)
            for embed in [f"https://www.instagram.com/p/{sc}/embed/",
                          f"https://www.instagram.com/reel/{sc}/embed/"]:
                try:
                    r = req.get(embed, headers={"User-Agent": UA}, timeout=15)
                    for pat in [r'"video_url"\s*:\s*"([^"]+)"',
                                r'<video[^>]+src="([^"]+)"',
                                r'property="og:video"[^>]*content="([^"]+)"']:
                        vm = re.search(pat, r.text)
                        if vm:
                            u = (vm.group(1).replace("\\u0026", "&")
                                 .replace("\\/", "/").replace("&amp;", "&"))
                            c = _dl_url(u, {"Referer": "https://www.instagram.com/"})
                            if c: return _save_bytes(c, "ig"), None
                except Exception as e:
                    log.warning(f"IG embed: {e}")
    except Exception as e:
        log.warning(f"IG: {e}")
    fp = await dl_ytdlp(url, "instagram")
    return fp, None


async def dl_ytdlp(url, plat=""):
    out = str(TMP / f"dl_{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist", "--no-check-certificates",
           "--socket-timeout", "30", "--retries", "3",
           "-f", "best[ext=mp4]/best", "--merge-output-format", "mp4",
           "-o", out, "--print", "after_move:filepath", "--user-agent", UA]
    refs = {
        "tiktok": "https://www.tiktok.com/",
        "instagram": "https://www.instagram.com/",
        "youtube": "https://www.youtube.com/",
        "kwai": "https://www.kwai.com/",
    }
    if plat in refs:
        cmd += ["--add-header", f"Referer:{refs[plat]}"]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp):
                return fp
    except Exception as e:
        log.warning(f"yt-dlp: {e}")
    return None


# ══════════════════════════════════════════════════════════════
# Roteador
# ══════════════════════════════════════════════════════════════

async def download_video(url, plat):
    """
    Retorna: (filepath, metadata, extra_info)
    extra_info: dict com "watermark_detected", "endcard_trimmed", "strategy_used", "debug"
    """
    if plat == "shopee":
        result = await download_shopee(url, cookies_path=COOKIES_PATH)
        return (
            result.get("filepath"),
            result.get("metadata", {}),
            {
                "watermark_detected": result.get("watermark_detected", False),
                "endcard_trimmed": result.get("endcard_trimmed", False),
                "strategy_used": result.get("strategy_used"),
                "debug": result.get("debug", []),
            }
        )
    if plat == "tiktok":
        fp, md = await dl_tiktok(url)
        return fp, md, {}
    if plat == "instagram":
        fp, md = await dl_instagram(url)
        return fp, md, {}
    fp = await dl_ytdlp(url, plat)
    return fp, None, {}


# ══════════════════════════════════════════════════════════════
# Pós-processamento
# ══════════════════════════════════════════════════════════════

def strip_meta(src):
    dst = src.rsplit(".", 1)[0] + "_clean.mp4"
    try:
        r = subprocess.run(["ffmpeg", "-y", "-i", src,
            "-map_metadata", "-1", "-c", "copy", "-movflags", "+faststart", dst],
            capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return src


def compress(src, target=45):
    sz = os.path.getsize(src) / (1024 * 1024)
    if sz <= target: return src
    dst = src.rsplit(".", 1)[0] + "_comp.mp4"
    try:
        p = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                            "-of", "csv=p=0", src], capture_output=True, timeout=30)
        dur = float(p.stdout.decode().strip() or "60")
        vbr = max(int((target * 8 * 1024 * 1024 / dur) * 0.88), 700000)
        subprocess.run(["ffmpeg", "-y", "-i", src,
            "-c:v", "libx264", "-b:v", str(vbr),
            "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-map_metadata", "-1", dst],
            capture_output=True, timeout=600)
        if os.path.exists(dst): return dst
    except: pass
    return src


def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p): os.remove(p)
        except: pass


def esc(t):
    return re.sub(r"([_*\[\]()~`>#+=|{}.!\\-])", r"\\\1", str(t))


# ══════════════════════════════════════════════════════════════
# Handlers Telegram
# ══════════════════════════════════════════════════════════════

def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copiar legenda #1", callback_data="cp_v1")],
        [InlineKeyboardButton("📋 Versão alternativa #2", callback_data="cp_v2")],
        [InlineKeyboardButton("📋 Versão alternativa #3", callback_data="cp_v3")],
        [InlineKeyboardButton("🔄 Gerar nova legenda", callback_data="regen")],
    ])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    has_cookies = os.path.exists(COOKIES_PATH)
    cookies_status = "✅ Autenticado" if has_cookies else "⚠️ Modo anônimo"

    await update.message.reply_text(
        "🚀 *Viral Engine*\n\n"
        "Cole o link do vídeo\\.\n"
        "Eu baixo e gero legenda \\+ hashtags\\.\n\n"
        f"Shopee: {esc(cookies_status)}\n\n"
        "🛒 Shopee · 🎵 TikTok · 📸 Instagram\n"
        "▶️ YouTube · 🎬 Kwai · 🐦 X\n\n"
        f"_{esc(str(s.get('d', 0)))} downloads_\n\n"
        "/start · /debug",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not DEBUG_LOGS:
        await update.message.reply_text("Sem logs disponíveis.")
        return
    text = "\n".join(list(DEBUG_LOGS)[-60:])
    if len(text) > 3800:
        text = text[-3800:]
    await update.message.reply_text(f"```\n{text}\n```", parse_mode=ParseMode.MARKDOWN_V2)


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text or len(text) < 3: return

    uid = update.effective_user.id
    link_m = re.search(r"https?://\S+", text)
    link = link_m.group(0) if link_m else None
    plat = detect_platform(link) if link else None

    log.info(f"━━━━━ MSG user={uid} plat={plat}")

    metadata = None
    extra_info = {}

    if link and can_download(plat):
        if plat == "shopee":
            status = await update.message.reply_text(
                "⏳ Processando Shopee (pode demorar 30-60s)..."
            )
        else:
            status = await update.message.reply_text(f"⏳ Baixando do {plat.upper()}...")

        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        fp = None
        try:
            fp, metadata, extra_info = await download_video(link, plat)
        except Exception as e:
            log.error(f"download_video: {e}")

        if fp:
            cleaned = strip_meta(fp)
            final = cleaned if cleaned != fp else fp

            sz = os.path.getsize(final) / (1024 * 1024)
            if sz > 49:
                try: await status.edit_text(f"🗜 Otimizando ({sz:.0f}MB)...")
                except: pass
                final = compress(final)

            sz = os.path.getsize(final) / (1024 * 1024)
            if sz <= 49:
                try: await status.delete()
                except: pass

                # Construir caption HONESTA com status
                caption_parts = []

                if extra_info.get("watermark_detected"):
                    caption_parts.append(
                        "⚠️ *Marca d'água presente*\n"
                        "Tecnicamente impossível remover sem recursos adicionais\\."
                    )
                else:
                    caption_parts.append("✅ *Sem marca d'água detectada*")

                if extra_info.get("endcard_trimmed"):
                    caption_parts.append("✂️ Endcard vermelho cortado")

                strategy = extra_info.get("strategy_used")
                if strategy:
                    strategy_label = {
                        "mobile_api": "API autenticada",
                        "playwright_auth": "Playwright autenticado",
                        "playwright": "Playwright público",
                    }.get(strategy, strategy)
                    caption_parts.append(f"_Método: {esc(strategy_label)}_")

                if metadata and metadata.get("username"):
                    caption_parts.append(f"📎 @{esc(metadata['username'])}")

                caption_text = "\n".join(caption_parts)

                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption=caption_text,
                            parse_mode=ParseMode.MARKDOWN_V2,
                            read_timeout=300,
                            write_timeout=300,
                            supports_streaming=True,
                        )
                    track(uid)
                except Exception as e:
                    log.error(f"Envio: {e}")
                    try: await status.edit_text(f"⚠️ Erro ao enviar: {str(e)[:100]}")
                    except: pass
            else:
                try: await status.edit_text(f"⚠️ Vídeo muito grande ({sz:.0f}MB).")
                except: pass

            cleanup(fp)
            if cleaned and cleaned != fp: cleanup(cleaned)
            if final != fp and final != cleaned: cleanup(final)
        else:
            try:
                await status.edit_text(
                    "⚠️ Não consegui baixar\\.\n"
                    "Envie /debug para detalhes técnicos\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except: pass

        # Gerar legenda (mesmo se download falhou) e SALVAR em arquivo
        try:
            data = generate(link, metadata=metadata)
            set_user_data(uid, {
                "v1": data["v1"],
                "v2": data["v2"],
                "v3": data["v3"],
                "src": link,
                "metadata": metadata,
            })

            header = ""
            if metadata and metadata.get("product_name"):
                header = f"📦 *Produto:* {esc(metadata['product_name'][:80])}\n\n"

            full_msg = (header + data["full"]) if header else data["full"]

            if header:
                await update.message.reply_text(
                    full_msg, reply_markup=_kb(),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await update.message.reply_text(data["full"], reply_markup=_kb())

        except Exception as e:
            log.error(f"Legenda erro: {e}")

    else:
        # Texto livre
        await update.message.reply_chat_action(ChatAction.TYPING)
        try:
            data = generate(link or text)
            set_user_data(uid, {
                "v1": data["v1"],
                "v2": data["v2"],
                "v3": data["v3"],
                "src": link or text,
                "metadata": None,
            })
            await update.message.reply_text(data["full"], reply_markup=_kb())
            track(uid)
        except Exception as e:
            log.error(f"Legenda texto: {e}")
            await update.message.reply_text(f"⚠️ Erro: {str(e)[:100]}")


async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callbacks dos botões — agora carregam do arquivo, não do ctx.user_data."""
    q = update.callback_query
    try: await q.answer()
    except: pass

    uid = q.from_user.id
    action = q.data
    log.info(f"CB user={uid} action={action}")

    user_data = get_user_data(uid)

    if action in ("cp_v1", "cp_v2", "cp_v3"):
        key = action.replace("cp_", "")
        text = user_data.get(key, "")
        if text:
            await q.message.reply_text(text)
        else:
            await q.message.reply_text(
                "⚠️ Sem legenda armazenada.\n"
                "Envie o link novamente."
            )

    elif action == "regen":
        src = user_data.get("src", "")
        md = user_data.get("metadata")
        if src:
            try:
                data = generate(src, metadata=md)
                set_user_data(uid, {
                    "v1": data["v1"],
                    "v2": data["v2"],
                    "v3": data["v3"],
                    "src": src,
                    "metadata": md,
                })
                await q.message.reply_text(data["full"], reply_markup=_kb())
            except Exception as e:
                log.error(f"Regen: {e}")
                await q.message.reply_text(f"⚠️ {str(e)[:80]}")
        else:
            await q.message.reply_text("⚠️ Envie um link primeiro.")


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Iniciar"),
        BotCommand("debug", "Ver logs"),
    ])


def main():
    if not TOKEN:
        print("❌ Configure TELEGRAM_BOT_TOKEN")
        return

    update_ytdlp()
    threading.Thread(target=start_http, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.add_handler(CallbackQueryHandler(handle_cb))

    log.info("🚀 Viral Engine Bot (versão honesta) rodando!")
    log.info(f"Cookies: {'✅ encontrados' if os.path.exists(COOKIES_PATH) else '⚠️ não encontrados em ' + COOKIES_PATH}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
