"""
Viral Engine Bot — Download + Legenda Viral

TELEGRAM_BOT_TOKEN=xxx python bot.py
"""

import os, re, logging, asyncio, subprocess, tempfile, time, json, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import quote
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

# ── Health (Render) ──
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
def start_http(): HTTPServer(("0.0.0.0", PORT), H).serve_forever()

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

def _save(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp


# ════════════════════════════════════════════════════
# COMPRESSÃO — reduz tamanho mantendo qualidade
# ════════════════════════════════════════════════════
def compress_video(src: str, target_mb: int = 45) -> str:
    """Comprime vídeo para caber no limite do Telegram mantendo qualidade."""
    size_mb = os.path.getsize(src) / (1024*1024)
    if size_mb <= target_mb:
        return src

    dst = src.rsplit(".",1)[0] + "_comp.mp4"
    log.info(f"Comprimindo {size_mb:.1f}MB → ~{target_mb}MB")

    # Calcular bitrate alvo
    try:
        # Duração do vídeo
        probe = subprocess.run(
            ["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0", src],
            capture_output=True, timeout=30
        )
        duration = float(probe.stdout.decode().strip() or "60")
        target_bits = target_mb * 8 * 1024 * 1024
        video_bitrate = int((target_bits / duration) * 0.9)  # 90% para vídeo, 10% áudio
        video_bitrate = max(video_bitrate, 500000)  # mínimo 500kbps

        r = subprocess.run([
            "ffmpeg", "-y", "-i", src,
            "-c:v", "libx264", "-b:v", str(video_bitrate),
            "-preset", "fast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-map_metadata", "-1",
            dst
        ], capture_output=True, timeout=300)

        if r.returncode == 0 and os.path.exists(dst):
            new_size = os.path.getsize(dst) / (1024*1024)
            log.info(f"Comprimido: {new_size:.1f}MB")
            return dst
    except Exception as e:
        log.warning(f"Compressão falhou: {e}")

    return src


# ════════════════════════════════════════════════════
# DOWNLOADERS
# ════════════════════════════════════════════════════

async def dl_tiktok(url: str) -> str | None:
    """TikTok — TikWM API (HD, sem watermark)."""
    try:
        r = req.post("https://www.tikwm.com/api/", data={"url": url, "hd": 1},
                      headers={"User-Agent": UA}, timeout=30)
        data = r.json()
        if data.get("code") == 0 and data.get("data"):
            vurl = data["data"].get("hdplay") or data["data"].get("play")
            if vurl:
                vr = req.get(vurl, timeout=120, headers={"User-Agent": "okhttp"})
                if vr.status_code == 200 and len(vr.content) > 10000:
                    log.info(f"TikTok OK: {len(vr.content)//1024}KB")
                    return _save(vr.content, "tt")
    except Exception as e:
        log.warning(f"TikWM: {e}")
    # Fallback yt-dlp
    return await dl_ytdlp(url, "tiktok")


async def dl_instagram(url: str) -> str | None:
    """Instagram — embed scraping → yt-dlp fallback."""
    try:
        m = re.search(r'/(p|reel|reels)/([A-Za-z0-9_-]+)', url)
        if m:
            sc = m.group(2)
            r = req.get(f"https://www.instagram.com/p/{sc}/embed/",
                        headers={"User-Agent": UA}, timeout=15)
            vm = re.search(r'"video_url"\s*:\s*"([^"]+)"', r.text)
            if not vm: vm = re.search(r'<video[^>]+src="([^"]+)"', r.text)
            if vm:
                vurl = vm.group(1).replace("\\u0026","&").replace("\\/","/")
                vr = req.get(vurl, timeout=120, headers={"User-Agent": UA, "Referer": "https://www.instagram.com/"})
                if vr.status_code == 200 and len(vr.content) > 10000:
                    log.info(f"Instagram OK: {len(vr.content)//1024}KB")
                    return _save(vr.content, "ig")
    except Exception as e:
        log.warning(f"IG embed: {e}")
    return await dl_ytdlp(url, "instagram")


async def dl_ytdlp(url: str, plat: str = "") -> str | None:
    """Download genérico via yt-dlp — qualidade máxima."""
    out = str(TMP / f"dl_{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-warnings", "--no-playlist", "--no-check-certificates",
        "--socket-timeout", "30", "--retries", "5", "--extractor-retries", "3",
        # QUALIDADE MÁXIMA — sem limite de tamanho (comprimo depois)
        "-f", "best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", out,
        "--print", "after_move:filepath",
        "--user-agent", UA,
    ]
    if plat == "tiktok": cmd += ["--add-header","Referer:https://www.tiktok.com/"]
    elif plat == "instagram": cmd += ["--add-header","Referer:https://www.instagram.com/"]
    elif plat == "twitter": cmd += ["--add-header","Referer:https://twitter.com/"]
    elif plat == "pinterest": cmd += ["--add-header","Referer:https://www.pinterest.com/"]
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp):
                log.info(f"yt-dlp OK: {os.path.getsize(fp)//1024}KB")
                return fp
        log.warning(f"yt-dlp fail: {stderr.decode()[:300]}")
    except Exception as e:
        log.warning(f"yt-dlp err: {e}")
    return None


def strip_meta(src: str) -> str:
    """Remove metadados com ffmpeg."""
    dst = src.rsplit(".",1)[0] + "_clean.mp4"
    try:
        r = subprocess.run([
            "ffmpeg","-y","-i",src,
            "-map_metadata","-1","-fflags","+bitexact",
            "-flags:v","+bitexact","-flags:a","+bitexact",
            "-c","copy",dst
        ], capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return src


async def process_video(url: str, plat: str) -> tuple[str | None, bool]:
    """
    Roteador principal.
    Retorna (filepath, is_shopee_redirect).
    Se is_shopee_redirect=True, filepath é None e o bot deve redirecionar pro SVDown.
    """
    if plat == "shopee":
        # Shopee Video: a marca d'água é injetada pelo CDN da Shopee.
        # Ferramentas como SVDown usam API proprietária para extrair o original.
        # Não é possível replicar sem engenharia reversa do backend deles.
        return None, True

    elif plat == "tiktok":
        fp = await dl_tiktok(url)
        return fp, False

    elif plat == "instagram":
        fp = await dl_instagram(url)
        return fp, False

    else:  # youtube, twitter, pinterest, facebook, kwai, threads
        fp = await dl_ytdlp(url, plat)
        return fp, False


def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p): os.remove(p)
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
        "🎵 TikTok\n"
        "▶️ YouTube / Shorts\n"
        "🐦 Twitter / X\n"
        "📌 Pinterest\n"
        "📘 Facebook\n"
        "🎬 Kwai\n"
        "📸 Instagram\n"
        "🛒 Shopee \\(via SVDown\\)\n\n"
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
        # ── SHOPEE → redireciona para SVDown ──
        if plat == "shopee":
            svdown_url = f"https://svdown.tech/"
            data = generate(link)
            ctx.user_data["full"] = data["full"]
            ctx.user_data["src"] = link

            await update.message.reply_text(
                f"🛒 *Shopee Video detectado*\n\n"
                f"Para baixar vídeos da Shopee sem marca d'água em HD, "
                f"use o SVDown:\n\n"
                f"1️⃣ Acesse svdown\\.tech\n"
                f"2️⃣ Cole o link do vídeo\n"
                f"3️⃣ Clique em Buscar Vídeo\n\n"
                f"O SVDown remove a marca d'água e entrega em qualidade original\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Abrir SVDown", url=svdown_url)],
                ])
            )

            # Gera legenda + hashtags mesmo assim
            await update.message.reply_text(
                data["full"],
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Copiar tudo", callback_data="copy")],
                    [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
                ])
            )
            track(uid)
            return

        # ── OUTRAS PLATAFORMAS → download direto ──
        status = await update.message.reply_text("⏳ Baixando em HD...")
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        fp, _ = await process_video(link, plat)

        if fp:
            # Limpar metadados
            cleaned = strip_meta(fp)
            final = cleaned if cleaned != fp else fp

            # Comprimir se necessário
            size_mb = os.path.getsize(final) / (1024*1024)
            if size_mb > 49:
                try: await status.edit_text(f"🗜 Comprimindo ({size_mb:.0f}MB → ~45MB)...")
                except: pass
                final = compress_video(final)

            size_mb = os.path.getsize(final) / (1024*1024)
            if size_mb <= 49:
                try: await status.delete()
                except: pass
                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption="✅ Sem marca d'água · sem metadados · HD",
                            read_timeout=300, write_timeout=300,
                        )
                    track(uid)
                except Exception as e:
                    log.error(f"Envio: {e}")
                    try: await status.edit_text("⚠️ Erro ao enviar. Tente novamente.")
                    except: pass
            else:
                try: await status.edit_text(f"⚠️ Vídeo muito grande ({size_mb:.0f}MB) mesmo após compressão.")
                except: pass

            cleanup(fp)
            if cleaned and cleaned != fp: cleanup(cleaned)
            if final != fp and final != cleaned: cleanup(final)
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
        # ── TEXTO / LINK DE PRODUTO → só conteúdo ──
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
    q = update.callback_query
    await q.answer()
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
    if not TOKEN:
        print("❌ Configure TELEGRAM_BOT_TOKEN")
        return

    update_ytdlp()
    threading.Thread(target=start_http, daemon=True).start()

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.add_handler(CallbackQueryHandler(handle_cb))

    log.info("🚀 Bot rodando!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
