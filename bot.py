"""
Viral Engine Bot

TikTok     → TikWM API
Shopee     → Scraper (resolve link + extrai vídeo do CDN)
Instagram  → Embed scraping + yt-dlp
YouTube/Twitter/Pinterest/Facebook/Kwai → yt-dlp

TELEGRAM_BOT_TOKEN=xxx python bot.py
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

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# ── Health ──
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
def http(): HTTPServer(("0.0.0.0", PORT), Health).serve_forever()

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

def update_ytdlp():
    try:
        subprocess.run(["pip","install","--upgrade","--break-system-packages","yt-dlp"], capture_output=True, timeout=120)
        v = subprocess.run(["yt-dlp","--version"], capture_output=True, timeout=10)
        log.info(f"yt-dlp: {v.stdout.decode().strip()}")
    except: pass


# ════════════════════════════════════════════════════
# DOWNLOADERS POR PLATAFORMA
# ════════════════════════════════════════════════════

def _save(content, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}.mp4")
    with open(fp, "wb") as f:
        f.write(content)
    return fp


async def download_shopee(url: str) -> str | None:
    """Shopee Video — resolve link curto + extrai vídeo do HTML/JSON."""
    try:
        # 1. Resolver link curto (shp.ee, s.shopee.com.br)
        session = req.Session()
        session.headers.update({"User-Agent": UA})
        r = session.get(url, allow_redirects=True, timeout=15)
        final_url = r.url
        html = r.text
        log.info(f"Shopee URL resolvida: {final_url}")

        # 2. Procurar URL do vídeo no HTML
        patterns = [
            # JSON embeddado na página
            r'"videoUrl"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
            r'"video_url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
            r'"playUrl"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
            r'"play_url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
            r'"url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
            # Tag video no HTML
            r'<video[^>]+src="(https?://[^"]+)"',
            r'<source[^>]+src="(https?://[^"]+\.mp4[^"]*)"',
            # Shopee CDN patterns
            r'(https?://(?:cf|cv|down)\.shopee\.[^"\'\\]+\.mp4[^"\'\\]*)',
            r'(https?://(?:videosg|video)[^"\'\\]+shopee[^"\'\\]+\.mp4[^"\'\\]*)',
            # Genérico - qualquer .mp4 no CDN
            r'(https?://[^"\'\\\s]+\.mp4(?:\?[^"\'\\\s]*)?)',
        ]

        video_url = None
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                candidate = m.group(1).replace("\\u002F", "/").replace("\\/", "/").replace("\\u0026", "&")
                # Filtrar URLs que não são vídeos reais
                if ".mp4" in candidate and "shopee" not in candidate.split("/")[-1][:10]:
                    video_url = candidate
                    break
                elif ".mp4" in candidate:
                    video_url = candidate
                    break

        if not video_url:
            # Tentar encontrar em scripts JSON
            json_blocks = re.findall(r'<script[^>]*>.*?(\{.*?"mp4".*?\}|.*?"video".*?\}).*?</script>', html, re.S | re.I)
            for block in json_blocks[:5]:
                m = re.search(r'(https?://[^"\'\\]+\.mp4[^"\'\\]*)', block)
                if m:
                    video_url = m.group(1).replace("\\/", "/").replace("\\u0026", "&")
                    break

        if not video_url:
            # Última tentativa: buscar qualquer URL de vídeo na página inteira
            all_urls = re.findall(r'https?://[^\s"\'<>\\]+\.mp4[^\s"\'<>\\]*', html)
            if all_urls:
                video_url = all_urls[0].replace("\\/", "/")

        if video_url:
            log.info(f"Shopee video URL: {video_url[:100]}")
            vr = req.get(video_url, timeout=60, headers={"User-Agent": UA, "Referer": final_url})
            if vr.status_code == 200 and len(vr.content) > 10000:
                log.info(f"Shopee OK: {len(vr.content)//1024}KB")
                return _save(vr.content, "shopee")

        log.warning("Shopee: nenhuma URL de vídeo encontrada no HTML")
    except Exception as e:
        log.warning(f"Shopee erro: {e}")
    return None


async def download_tiktok(url: str) -> str | None:
    """TikTok via TikWM API."""
    try:
        r = req.post("https://www.tikwm.com/api/", data={"url": url, "hd": 1},
                      headers={"User-Agent": UA}, timeout=30)
        data = r.json()
        if data.get("code") == 0 and data.get("data"):
            vurl = data["data"].get("hdplay") or data["data"].get("play")
            if vurl:
                vr = req.get(vurl, timeout=60, headers={"User-Agent": "okhttp"})
                if vr.status_code == 200 and len(vr.content) > 10000:
                    log.info(f"TikTok OK: {len(vr.content)//1024}KB")
                    return _save(vr.content, "tt")
    except Exception as e:
        log.warning(f"TikWM: {e}")
    return None


async def download_instagram(url: str) -> str | None:
    """Instagram via embed scraping."""
    try:
        m = re.search(r'/(p|reel|reels)/([A-Za-z0-9_-]+)', url)
        if m:
            sc = m.group(2)
            r = req.get(f"https://www.instagram.com/p/{sc}/embed/",
                        headers={"User-Agent": UA, "Accept": "text/html"}, timeout=15)
            vm = re.search(r'"video_url":"([^"]+)"', r.text)
            if not vm: vm = re.search(r'<video[^>]+src="([^"]+)"', r.text)
            if vm:
                vurl = vm.group(1).replace("\\u0026","&").replace("\\/","/")
                vr = req.get(vurl, timeout=60, headers={"User-Agent": UA, "Referer": "https://www.instagram.com/"})
                if vr.status_code == 200 and len(vr.content) > 10000:
                    log.info(f"Instagram OK: {len(vr.content)//1024}KB")
                    return _save(vr.content, "ig")
    except Exception as e:
        log.warning(f"Instagram: {e}")
    return await download_ytdlp(url, "instagram")


async def download_ytdlp(url: str, plat: str = "") -> str | None:
    """Fallback genérico via yt-dlp."""
    out = str(TMP / f"{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = [
        "yt-dlp","--no-warnings","--no-playlist","--no-check-certificates",
        "--max-filesize","49m","--socket-timeout","30","--retries","5",
        "--extractor-retries","3",
        "-f","best[ext=mp4][filesize<49M]/best[ext=mp4]/best[filesize<49M]/best",
        "--merge-output-format","mp4","-o",out,"--print","after_move:filepath",
        "--user-agent", UA,
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
        log.warning(f"yt-dlp: {stderr.decode()[:200]}")
    except: pass
    return None


async def download_video(url: str, plat: str) -> str | None:
    """Roteador principal — escolhe estratégia por plataforma."""
    if plat == "shopee":
        return await download_shopee(url)
    elif plat == "tiktok":
        fp = await download_tiktok(url)
        return fp or await download_ytdlp(url, plat)
    elif plat == "instagram":
        return await download_instagram(url)
    else:
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
        "🛒 Shopee Video\n"
        "🎵 TikTok\n"
        "▶️ YouTube\n"
        "🐦 Twitter/X\n"
        "📌 Pinterest\n"
        "📘 Facebook\n"
        "🎬 Kwai\n"
        "📸 Instagram \\(público\\)\n\n"
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
