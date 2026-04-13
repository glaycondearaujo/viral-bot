"""
Viral Engine Bot — Download multi-plataforma + legenda viral.

TikTok → TikWM API (sem bloqueio, sem marca d'água)
YouTube/Twitter/Pinterest/Facebook → yt-dlp
Instagram → embed scraping + yt-dlp fallback

Uso: TELEGRAM_BOT_TOKEN=xxx python bot.py
"""

import os, re, logging, asyncio, subprocess, tempfile, time, json, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode, ChatAction
from engine import generate, detect_platform, can_download

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", "10000"))
TMP = Path(tempfile.gettempdir()) / "vbot"
TMP.mkdir(exist_ok=True)
STATS = TMP / "stats.json"

# ── Health ──
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
def http(): HTTPServer(("0.0.0.0", PORT), H).serve_forever()

# ── Stats ──
def load_s():
    try: return json.loads(STATS.read_text()) if STATS.exists() else {"d":0,"u":[]}
    except: return {"d":0,"u":[]}
def save_s(s):
    try: STATS.write_text(json.dumps(s))
    except: pass
def track(uid):
    s=load_s(); s["d"]=s.get("d",0)+1
    if uid not in s.get("u",[]): s.setdefault("u",[]).append(uid)
    save_s(s)

# ── yt-dlp update ──
def update_ytdlp():
    try:
        subprocess.run(["pip","install","--upgrade","--break-system-packages","yt-dlp"],
                       capture_output=True, timeout=120)
        v = subprocess.run(["yt-dlp","--version"], capture_output=True, timeout=10)
        log.info(f"yt-dlp: {v.stdout.decode().strip()}")
    except: pass

# ════════════════════════════════════════════════════
# DOWNLOAD — ESTRATÉGIA POR PLATAFORMA
# ════════════════════════════════════════════════════

async def download_tiktok(url: str) -> str | None:
    """TikTok via TikWM API — funciona de qualquer servidor."""
    try:
        r = req.post(
            "https://www.tikwm.com/api/",
            data={"url": url, "hd": 1},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30
        )
        data = r.json()
        if data.get("code") == 0 and data.get("data"):
            video_url = data["data"].get("hdplay") or data["data"].get("play")
            if video_url:
                fp = str(TMP / f"tt_{int(time.time())}.mp4")
                vr = req.get(video_url, timeout=60, headers={"User-Agent": "okhttp"})
                if vr.status_code == 200 and len(vr.content) > 10000:
                    with open(fp, "wb") as f:
                        f.write(vr.content)
                    log.info(f"TikTok OK: {len(vr.content)//1024}KB")
                    return fp
    except Exception as e:
        log.warning(f"TikWM falhou: {e}")
    return None


async def download_instagram(url: str) -> str | None:
    """Instagram via embed page scraping."""
    try:
        # Tentar extrair do embed
        shortcode = None
        m = re.search(r'/(p|reel|reels)/([A-Za-z0-9_-]+)', url)
        if m:
            shortcode = m.group(2)

        if shortcode:
            embed_url = f"https://www.instagram.com/p/{shortcode}/embed/"
            r = req.get(embed_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            }, timeout=15)

            # Procurar URL do vídeo no HTML do embed
            video_match = re.search(r'"video_url":"([^"]+)"', r.text)
            if not video_match:
                video_match = re.search(r'<video[^>]+src="([^"]+)"', r.text)

            if video_match:
                video_url = video_match.group(1).replace("\\u0026", "&").replace("\\/", "/")
                fp = str(TMP / f"ig_{int(time.time())}.mp4")
                vr = req.get(video_url, timeout=60, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.instagram.com/",
                })
                if vr.status_code == 200 and len(vr.content) > 10000:
                    with open(fp, "wb") as f:
                        f.write(vr.content)
                    log.info(f"Instagram OK: {len(vr.content)//1024}KB")
                    return fp
    except Exception as e:
        log.warning(f"Instagram embed falhou: {e}")

    # Fallback: yt-dlp
    return await download_ytdlp(url, "instagram")


async def download_ytdlp(url: str, plat: str = "") -> str | None:
    """Fallback genérico via yt-dlp."""
    uid = f"{int(time.time())}_{os.getpid()}"
    out = str(TMP / f"{uid}.%(ext)s")
    cmd = [
        "yt-dlp","--no-warnings","--no-playlist","--no-check-certificates",
        "--max-filesize","49m","--socket-timeout","30","--retries","5",
        "--extractor-retries","3",
        "-f","best[ext=mp4][filesize<49M]/best[ext=mp4]/best[filesize<49M]/best",
        "--merge-output-format","mp4","-o",out,"--print","after_move:filepath",
        "--user-agent","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    ]
    if plat == "instagram": cmd += ["--add-header","Referer:https://www.instagram.com/"]
    elif plat == "twitter": cmd += ["--add-header","Referer:https://twitter.com/"]
    elif plat == "pinterest": cmd += ["--add-header","Referer:https://www.pinterest.com/"]
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp):
                log.info(f"yt-dlp OK: {os.path.getsize(fp)//1024}KB")
                return fp
        log.warning(f"yt-dlp falhou: {stderr.decode()[:200]}")
    except: pass
    return None


async def download_video(url: str, plat: str) -> str | None:
    """Roteador de download — escolhe estratégia por plataforma."""
    if plat == "tiktok":
        fp = await download_tiktok(url)
        if fp: return fp
        return await download_ytdlp(url, plat)  # fallback

    elif plat == "instagram":
        return await download_instagram(url)

    else:  # youtube, twitter, pinterest, facebook, kwai, threads
        return await download_ytdlp(url, plat)


def strip_meta(src):
    dst = src.rsplit(".",1)[0] + "_c.mp4"
    try:
        r = subprocess.run(["ffmpeg","-y","-i",src,"-map_metadata","-1",
            "-fflags","+bitexact","-flags:v","+bitexact","-flags:a","+bitexact",
            "-c","copy",dst], capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return src

def cleanup(*p):
    for f in p:
        try:
            if f and os.path.exists(f): os.remove(f)
        except: pass

def esc(t): return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(t))

# ════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    await update.message.reply_text(
        "🚀 *Viral Engine*\n\n"
        "Cole o link do vídeo\\.\n"
        "Eu baixo sem marca d'água e gero legenda \\+ hashtags\\.\n\n"
        "✅ TikTok \\| YouTube \\| Twitter \\| Pinterest \\| Kwai\n"
        "⚠️ Instagram \\(público\\)\n\n"
        f"_{esc(str(s.get('d',0)))} downloads_\n\n"
        "👇 Manda o link",
        parse_mode=ParseMode.MARKDOWN_V2
    )

async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text or len(text) < 3: return

    uid = update.effective_user.id
    link_m = re.search(r'https?://\S+', text)
    link = link_m.group(0) if link_m else None
    plat = detect_platform(link) if link else None

    if link and can_download(plat):
        status = await update.message.reply_text("⏳ Baixando...")
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        fp = await download_video(link, plat)
        clean = None

        if fp:
            clean = strip_meta(fp)
            final = clean if clean != fp else fp

            if os.path.getsize(final) <= 49*1024*1024:
                try: await status.delete()
                except: pass
                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption="✅ Sem marca d'água · sem metadados",
                            read_timeout=120, write_timeout=120,
                        )
                    track(uid)
                except Exception as e:
                    log.error(f"Envio: {e}")
                    try: await status.edit_text("⚠️ Erro ao enviar. Tente novamente.")
                    except: pass
            else:
                try: await status.edit_text("⚠️ Vídeo muito grande (>50MB).")
                except: pass

            cleanup(fp)
            if clean and clean != fp: cleanup(clean)
        else:
            try: await status.edit_text("⚠️ Não consegui baixar. Verifique se o vídeo é público.")
            except: pass

        # Legenda + hashtags
        data = generate(link)
        ctx.user_data["full"] = data["full"]
        ctx.user_data["src"] = link
        await update.message.reply_text(
            data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copiar tudo", callback_data="copy")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ])
        )
    else:
        await update.message.reply_chat_action(ChatAction.TYPING)
        data = generate(link or text)
        ctx.user_data["full"] = data["full"]
        ctx.user_data["src"] = link or text
        await update.message.reply_text(
            data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copiar tudo", callback_data="copy")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ])
        )
        track(uid)

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "copy":
        f = ctx.user_data.get("full","")
        if f: await q.message.reply_text(f)
    elif q.data == "regen":
        src = ctx.user_data.get("src","")
        if src:
            data = generate(src)
            ctx.user_data["full"] = data["full"]
            await q.message.reply_text(data["full"],
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Copiar tudo", callback_data="copy")],
                    [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
                ]))

async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start","Iniciar")])

def main():
    if not TOKEN: print("❌ Configure TELEGRAM_BOT_TOKEN"); return
    update_ytdlp()
    threading.Thread(target=http, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.add_handler(CallbackQueryHandler(handle_cb))
    log.info("🚀 Bot rodando!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
