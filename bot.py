"""
Viral Engine Bot — Download multi-plataforma + Legenda Viral

Shopee: 4 camadas de extração (CDN / API / HTML / og:video)
TikTok: TikWM API
YouTube/Twitter/Pinterest/Facebook/Kwai: yt-dlp
Instagram: embed + yt-dlp

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
UA_MOBILE = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"

# ── Health ──
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
    except: pass

def _save(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp

def _dl_file(url, headers=None) -> bytes | None:
    """Baixa arquivo de uma URL, retorna bytes ou None."""
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        r = req.get(url, headers=h, timeout=120, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > 50000:  # mínimo 50KB = vídeo real
            return r.content
    except: pass
    return None


# ════════════════════════════════════════════════════
# SHOPEE — 4 CAMADAS DE EXTRAÇÃO
# ════════════════════════════════════════════════════

def _resolve_shopee_url(url: str) -> str:
    """Resolve links curtos (shp.ee, s.shopee.com.br) → URL final."""
    try:
        r = req.get(url, headers={"User-Agent": UA_MOBILE}, allow_redirects=True, timeout=15)
        return r.url
    except:
        return url


def _extract_ids_from_url(url: str) -> tuple:
    """Extrai shop_id e item_id de URLs de produto Shopee."""
    # Padrão: /product/SHOPID/ITEMID ou -i.SHOPID.ITEMID
    m = re.search(r'i\.(\d+)\.(\d+)', url)
    if m: return m.group(1), m.group(2)
    m = re.search(r'/product/(\d+)/(\d+)', url)
    if m: return m.group(1), m.group(2)
    return None, None


def _shopee_layer1_api(url: str) -> str | None:
    """Camada 1: API de produto Shopee → vídeo do CDN (sem watermark)."""
    shop_id, item_id = _extract_ids_from_url(url)
    if not shop_id or not item_id:
        return None

    log.info(f"Shopee Layer1: API shop={shop_id} item={item_id}")
    try:
        api_url = f"https://shopee.com.br/api/v4/pdp/get_pc?shop_id={shop_id}&item_id={item_id}"
        r = req.get(api_url, headers={
            "User-Agent": UA,
            "Referer": url,
            "Accept": "application/json",
            "x-shopee-language": "pt-BR",
        }, timeout=15)

        if r.status_code == 200:
            data = r.json()
            item = data.get("data", {}).get("item", {})

            # Procurar vídeo na lista de vídeos do item
            video_list = item.get("video_info_list", [])
            for v in video_list:
                # Tentar diferentes campos de URL
                for key in ["video_url", "url", "default_format"]:
                    vurl = v.get(key)
                    if isinstance(vurl, dict): vurl = vurl.get("url")
                    if vurl and ("mp4" in vurl or "video" in vurl):
                        log.info(f"Shopee Layer1 encontrou: {vurl[:80]}")
                        return vurl

            # Também checar no tier_variations e imagens que podem ser vídeos
            video = item.get("video")
            if video:
                vurl = video if isinstance(video, str) else video.get("video_url", "")
                if vurl:
                    log.info(f"Shopee Layer1 video field: {vurl[:80]}")
                    return vurl

    except Exception as e:
        log.warning(f"Shopee Layer1 falhou: {e}")
    return None


def _shopee_layer2_html(url: str, html: str) -> str | None:
    """Camada 2: Extrair URL de vídeo do HTML da página."""
    log.info("Shopee Layer2: HTML scraping")

    # Prioridade: URLs de vídeo do CDN Shopee
    cdn_patterns = [
        # CDN de vídeo Shopee
        r'(https?://(?:cf|cv|down)[^"\'\\,\s]+shopee[^"\'\\,\s]*\.mp4[^"\'\\,\s]*)',
        r'(https?://[^"\'\\,\s]*susercontent\.com[^"\'\\,\s]*\.mp4[^"\'\\,\s]*)',
        r'(https?://[^"\'\\,\s]*shopee[^"\'\\,\s]*(?:mms|video|media)[^"\'\\,\s]*)',
        # JSON fields
        r'"(?:video_url|videoUrl|playUrl|play_url|video_link)"\s*:\s*"(https?://[^"]+)"',
        # Genérico - qualquer URL de vídeo
        r'"(https?://[^"]+\.mp4(?:\?[^"]*)?)"',
        # Tag <video>
        r'<video[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']',
    ]

    for pat in cdn_patterns:
        matches = re.findall(pat, html, re.I)
        for match in matches:
            candidate = match.replace("\\u002F","/").replace("\\/","/").replace("\\u0026","&")
            # Filtrar URLs inválidas
            if len(candidate) < 20: continue
            if any(x in candidate.lower() for x in ["thumbnail","image","jpg","png","gif","webp","sprite"]): continue
            log.info(f"Shopee Layer2 candidato: {candidate[:80]}")
            return candidate

    return None


def _shopee_layer3_og(html: str) -> str | None:
    """Camada 3: Open Graph og:video meta tag."""
    log.info("Shopee Layer3: og:video")
    m = re.search(r'<meta[^>]+property=["\']og:video["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video["\']', html, re.I)
    if m:
        vurl = m.group(1).replace("&amp;","&")
        log.info(f"Shopee Layer3 encontrou: {vurl[:80]}")
        return vurl
    return None


def _shopee_layer4_mobile(url: str) -> str | None:
    """Camada 4: Fetch como mobile app — pode retornar dados diferentes."""
    log.info("Shopee Layer4: Mobile fetch")
    try:
        r = req.get(url, headers={
            "User-Agent": UA_MOBILE,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }, timeout=15, allow_redirects=True)

        # Procurar URLs de vídeo no HTML mobile
        patterns = [
            r'"(?:video_url|videoUrl|playUrl|play_url)"\s*:\s*"(https?://[^"]+)"',
            r'"(https?://[^"]+\.mp4[^"]*)"',
        ]
        for pat in patterns:
            matches = re.findall(pat, r.text, re.I)
            for match in matches:
                candidate = match.replace("\\u002F","/").replace("\\/","/").replace("\\u0026","&")
                if len(candidate) < 20: continue
                if any(x in candidate.lower() for x in ["thumbnail","image","jpg","png"]): continue
                log.info(f"Shopee Layer4 candidato: {candidate[:80]}")
                return candidate
    except Exception as e:
        log.warning(f"Shopee Layer4: {e}")
    return None


async def dl_shopee(url: str) -> str | None:
    """Shopee Video — 4 camadas de extração em cascata."""
    resolved = _resolve_shopee_url(url)
    log.info(f"Shopee: {url} → {resolved}")

    # Fetch HTML da página
    html = ""
    try:
        r = req.get(resolved, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"}, timeout=15)
        html = r.text
    except: pass

    # Tentar cada camada
    video_url = None

    # Layer 1: API de produto
    video_url = _shopee_layer1_api(resolved)

    # Layer 2: HTML scraping
    if not video_url and html:
        video_url = _shopee_layer2_html(resolved, html)

    # Layer 3: og:video
    if not video_url and html:
        video_url = _shopee_layer3_og(html)

    # Layer 4: Mobile fetch
    if not video_url:
        video_url = _shopee_layer4_mobile(resolved)

    # Download do vídeo encontrado
    if video_url:
        log.info(f"Shopee: baixando {video_url[:80]}")
        content = _dl_file(video_url, {"Referer": resolved})
        if content:
            log.info(f"Shopee OK: {len(content)//1024}KB")
            return _save(content, "shopee")
        else:
            log.warning("Shopee: URL encontrada mas download falhou")

    log.warning("Shopee: nenhuma URL de vídeo encontrada")
    return None


# ════════════════════════════════════════════════════
# OUTROS DOWNLOADERS
# ════════════════════════════════════════════════════

async def dl_tiktok(url: str) -> str | None:
    try:
        r = req.post("https://www.tikwm.com/api/", data={"url": url, "hd": 1}, headers={"User-Agent": UA}, timeout=30)
        data = r.json()
        if data.get("code") == 0 and data.get("data"):
            vurl = data["data"].get("hdplay") or data["data"].get("play")
            if vurl:
                content = _dl_file(vurl, {"User-Agent": "okhttp"})
                if content:
                    log.info(f"TikTok OK: {len(content)//1024}KB")
                    return _save(content, "tt")
    except Exception as e:
        log.warning(f"TikWM: {e}")
    return await dl_ytdlp(url, "tiktok")

async def dl_instagram(url: str) -> str | None:
    try:
        m = re.search(r'/(p|reel|reels)/([A-Za-z0-9_-]+)', url)
        if m:
            r = req.get(f"https://www.instagram.com/p/{m.group(2)}/embed/", headers={"User-Agent": UA}, timeout=15)
            vm = re.search(r'"video_url"\s*:\s*"([^"]+)"', r.text)
            if not vm: vm = re.search(r'<video[^>]+src="([^"]+)"', r.text)
            if vm:
                vurl = vm.group(1).replace("\\u0026","&").replace("\\/","/")
                content = _dl_file(vurl, {"Referer": "https://www.instagram.com/"})
                if content:
                    log.info(f"IG OK: {len(content)//1024}KB")
                    return _save(content, "ig")
    except Exception as e:
        log.warning(f"IG: {e}")
    return await dl_ytdlp(url, "instagram")

async def dl_ytdlp(url: str, plat: str = "") -> str | None:
    out = str(TMP / f"dl_{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = [
        "yt-dlp","--no-warnings","--no-playlist","--no-check-certificates",
        "--socket-timeout","30","--retries","5","--extractor-retries","3",
        "-f","best[ext=mp4]/best","--merge-output-format","mp4",
        "-o",out,"--print","after_move:filepath","--user-agent",UA,
    ]
    headers = {"tiktok":"https://www.tiktok.com/","instagram":"https://www.instagram.com/",
               "twitter":"https://twitter.com/","pinterest":"https://www.pinterest.com/"}
    if plat in headers: cmd += ["--add-header",f"Referer:{headers[plat]}"]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp): return fp
    except: pass
    return None


# ════════════════════════════════════════════════════
# POST-PROCESSING
# ════════════════════════════════════════════════════

def strip_meta(src):
    dst = src.rsplit(".",1)[0] + "_clean.mp4"
    try:
        r = subprocess.run(["ffmpeg","-y","-i",src,"-map_metadata","-1","-fflags","+bitexact","-flags:v","+bitexact","-flags:a","+bitexact","-c","copy",dst], capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return src

def compress(src, target_mb=45):
    size_mb = os.path.getsize(src) / (1024*1024)
    if size_mb <= target_mb: return src
    dst = src.rsplit(".",1)[0] + "_comp.mp4"
    try:
        probe = subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0",src], capture_output=True, timeout=30)
        dur = float(probe.stdout.decode().strip() or "60")
        vbr = max(int((target_mb*8*1024*1024/dur)*0.85), 500000)
        subprocess.run(["ffmpeg","-y","-i",src,"-c:v","libx264","-b:v",str(vbr),"-preset","fast","-crf","28","-c:a","aac","-b:a","128k","-movflags","+faststart","-map_metadata","-1",dst], capture_output=True, timeout=300)
        if os.path.exists(dst): return dst
    except: pass
    return src

def cleanup(*p):
    for f in p:
        try:
            if f and os.path.exists(f): os.remove(f)
        except: pass

def esc(t): return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(t))


# ════════════════════════════════════════════════════
# ROTEADOR
# ════════════════════════════════════════════════════

async def download_video(url, plat):
    if plat == "shopee": return await dl_shopee(url)
    elif plat == "tiktok": return await dl_tiktok(url)
    elif plat == "instagram": return await dl_instagram(url)
    else: return await dl_ytdlp(url, plat)


# ════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    await update.message.reply_text(
        "🚀 *Viral Engine*\n\n"
        "Cole o link do vídeo\\.\n"
        "Eu baixo sem marca d'água e gero legenda \\+ hashtags\\.\n\n"
        "🛒 Shopee Video\n🎵 TikTok\n▶️ YouTube\n🐦 Twitter/X\n"
        "📌 Pinterest\n📘 Facebook\n🎬 Kwai\n📸 Instagram\n\n"
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
        status = await update.message.reply_text("⏳ Baixando em HD...")
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        fp = await download_video(link, plat)

        if fp:
            cleaned = strip_meta(fp)
            final = cleaned if cleaned != fp else fp

            size_mb = os.path.getsize(final) / (1024*1024)
            if size_mb > 49:
                try: await status.edit_text(f"🗜 Comprimindo ({size_mb:.0f}MB)...")
                except: pass
                final = compress(final)

            size_mb = os.path.getsize(final) / (1024*1024)
            if size_mb <= 49:
                try: await status.delete()
                except: pass
                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(video=f, caption="✅ Sem marca d'água · HD", read_timeout=300, write_timeout=300)
                    track(uid)
                except Exception as e:
                    log.error(f"Envio: {e}")
                    try: await status.edit_text("⚠️ Erro ao enviar. Tente novamente.")
                    except: pass
            else:
                try: await status.edit_text(f"⚠️ Vídeo muito grande ({size_mb:.0f}MB) mesmo após compressão.")
                except: pass

            cleanup(fp)
            if cleaned != fp: cleanup(cleaned)
            if final != fp and final != cleaned: cleanup(final)
        else:
            try: await status.edit_text("⚠️ Não consegui baixar. Verifique se o vídeo é público e tente novamente.")
            except: pass

        # Legenda + hashtags
        data = generate(link)
        ctx.user_data["full"] = data["full"]
        ctx.user_data["src"] = link
        await update.message.reply_text(data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copiar tudo", callback_data="copy")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ]))
    else:
        await update.message.reply_chat_action(ChatAction.TYPING)
        data = generate(link or text)
        ctx.user_data["full"] = data["full"]
        ctx.user_data["src"] = link or text
        await update.message.reply_text(data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copiar tudo", callback_data="copy")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ]))
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
    threading.Thread(target=start_http, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    app.add_handler(CallbackQueryHandler(handle_cb))
    log.info("🚀 Bot rodando!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
