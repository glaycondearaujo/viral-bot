"""
Viral Engine Bot — Download sem marca d'água + Legenda viral
Extração via APIs nativas de cada plataforma.
"""

import os, re, logging, asyncio, subprocess, tempfile, time, json, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
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
UA_M = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
UA_SHOPEE = "Android app Shopeee appver=31600 platform=native"


# ── Servidor HTTP (Render) ──
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
def start_http(): HTTPServer(("0.0.0.0", PORT), Health).serve_forever()


# ── Estatísticas ──
def load_s():
    try: return json.loads(STATS.read_text()) if STATS.exists() else {"d":0,"u":[]}
    except: return {"d":0,"u":[]}
def save_s(s):
    try: STATS.write_text(json.dumps(s))
    except: pass
def track(uid):
    s = load_s(); s["d"] = s.get("d",0)+1
    if uid not in s.get("u",[]): s.setdefault("u",[]).append(uid)
    save_s(s)


def update_ytdlp():
    try: subprocess.run(["pip","install","--upgrade","--break-system-packages","yt-dlp"], capture_output=True, timeout=120)
    except: pass


def _save(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp


def _dl(url, headers=None, min_size=50000):
    """Baixa URL direta com headers. Retorna bytes ou None."""
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        r = req.get(url, headers=h, timeout=180, allow_redirects=True, stream=True)
        if r.status_code == 200:
            content = r.content
            if len(content) > min_size:
                return content
    except Exception as e:
        log.warning(f"_dl erro: {e}")
    return None


# ════════════════════════════════════════════════════
# SHOPEE VIDEO — extração do vídeo ORIGINAL sem marca d'água
# ════════════════════════════════════════════════════

def _shopee_resolve(url):
    """Resolve links curtos (s.shopee.com.br, shp.ee) seguindo redirects."""
    try:
        r = req.get(url, headers={"User-Agent": UA_M}, allow_redirects=True, timeout=20)
        return r.url, r.text
    except Exception as e:
        log.warning(f"Resolve erro: {e}")
    return url, ""


def _shopee_extract_vid(url):
    """Extrai o ID do vídeo de uma URL Shopee Video."""
    # Padrões comuns:
    # https://sv.shopee.com.br/share-video/9834756482
    # https://shopee.com.br/video/9834756482
    # https://shopee.com.br/universal-link?redir=...video...
    patterns = [
        r'share-video/(\d+)',
        r'/video/(\d+)',
        r'videoId=(\d+)',
        r'vid=(\d+)',
        r'video_id[=/](\d+)',
        r'sv[./](\d{10,})',
    ]
    for pat in patterns:
        m = re.search(pat, url, re.I)
        if m: return m.group(1)

    # universal-link com redir
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if 'redir' in qs:
            redir = unquote(qs['redir'][0])
            for pat in patterns:
                m = re.search(pat, redir, re.I)
                if m: return m.group(1)
    except: pass
    return None


def _shopee_video_api(vid):
    """Chama endpoints oficiais da Shopee Video para pegar o MP4 original."""
    if not vid: return None

    # Endpoints que servem o vídeo SEM marca d'água (usado pelo app mobile)
    endpoints = [
        f"https://sv.shopee.com.br/api/v1/share/video/{vid}",
        f"https://sv.shopee.com.br/api/v1/video/detail?video_id={vid}",
        f"https://shopee.com.br/api/v4/sv/video_detail?video_id={vid}",
        f"https://shopee.com.br/api/v4/shop_video/get_video_info?video_id={vid}",
        f"https://sv-mms-live-br.shopee.com.br/api/v1/video/{vid}",
    ]

    for ep in endpoints:
        try:
            r = req.get(ep, headers={
                "User-Agent": UA_SHOPEE,
                "Accept": "application/json",
                "Referer": "https://shopee.com.br/",
                "X-Shopee-Language": "pt-BR",
                "X-API-SOURCE": "pc",
            }, timeout=15)
            if r.status_code == 200:
                try:
                    data = r.json()
                    vurl = _dig_video_url(data)
                    if vurl:
                        log.info(f"Shopee API {ep[:40]}... OK: {vurl[:80]}")
                        return vurl
                except: pass
        except Exception as e:
            log.debug(f"Endpoint {ep[:40]}: {e}")
    return None


def _dig_video_url(obj, depth=0):
    """Busca recursiva por URLs de vídeo em um JSON."""
    if depth > 10: return None
    if isinstance(obj, str):
        if obj.startswith("http") and (".mp4" in obj or "/video/" in obj or "/mms/" in obj):
            if not any(x in obj.lower() for x in ["thumb","cover","preview",".jpg",".png",".webp"]):
                return obj
        return None
    if isinstance(obj, dict):
        # Chaves prioritárias
        priority = ["default_format","video_url","play_url","playUrl","playAddr",
                    "url","download_url","hd_url","video","mms_url","cdn_url","src"]
        for k in priority:
            if k in obj:
                v = obj[k]
                if isinstance(v, (str, dict, list)):
                    found = _dig_video_url(v, depth+1)
                    if found: return found
        # Depois busca em todos os campos
        for v in obj.values():
            found = _dig_video_url(v, depth+1)
            if found: return found
    if isinstance(obj, list):
        for item in obj:
            found = _dig_video_url(item, depth+1)
            if found: return found
    return None


def _shopee_html_extract(html, final_url):
    """Extrai URL do vídeo do HTML (próxima camada de fallback)."""
    # 1. Buscar JSON embeddado com vídeo
    for pat in [
        r'"default_format"\s*:\s*\{[^}]*"url"\s*:\s*"([^"]+)"',
        r'"play_url"\s*:\s*"([^"]+)"',
        r'"video_url"\s*:\s*"([^"]+)"',
        r'"playUrl"\s*:\s*"([^"]+)"',
        r'"mms_url"\s*:\s*"([^"]+)"',
        r'"hd_url"\s*:\s*"([^"]+)"',
        r'"cdn_url"\s*:\s*"([^"]+\.mp4[^"]*)"',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            u = m.group(1).replace("\\u002F","/").replace("\\/","/").replace("\\u0026","&")
            if len(u) > 20 and ".mp4" in u:
                log.info(f"Shopee HTML extract: {u[:80]}")
                return u

    # 2. og:video / twitter:video
    for pat in [
        r'<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']twitter:video(?::url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+\.mp4[^"\']*)["\']',
    ]:
        m = re.search(pat, html, re.I)
        if m:
            u = m.group(1).replace("&amp;","&")
            if ".mp4" in u:
                log.info(f"Shopee meta: {u[:80]}"); return u

    # 3. URLs diretas de .mp4 no HTML
    urls = re.findall(r'https?://[^\s"\'<>\\]+\.mp4(?:\?[^\s"\'<>\\]*)?', html)
    for u in urls:
        if not any(x in u.lower() for x in ["thumb","cover","preview"]):
            log.info(f"Shopee direct mp4: {u[:80]}"); return u

    return None


async def dl_shopee(url):
    """Download Shopee Video SEM marca d'água — estratégia multi-camada."""
    log.info(f"Shopee: iniciando {url}")

    # 1. Resolver link curto
    final_url, html = _shopee_resolve(url)
    log.info(f"Shopee: resolvido → {final_url[:100]}")

    # 2. Extrair video ID da URL
    vid = _shopee_extract_vid(final_url) or _shopee_extract_vid(url)
    if not vid:
        # Tentar extrair do HTML
        m = re.search(r'"video_?id"\s*:\s*"?(\d{10,})', html)
        if m: vid = m.group(1)
    log.info(f"Shopee: video_id = {vid}")

    # 3. Tentar endpoints da API (retornam vídeo ORIGINAL sem marca d'água)
    vurl = None
    if vid:
        vurl = _shopee_video_api(vid)

    # 4. Fallback: extração do HTML
    if not vurl and html:
        vurl = _shopee_html_extract(html, final_url)

    # 5. Fallback: requisição mobile do HTML final
    if not vurl:
        try:
            r = req.get(final_url, headers={"User-Agent": UA_M}, timeout=15)
            vurl = _shopee_html_extract(r.text, final_url)
        except: pass

    # 6. Download do vídeo
    if vurl:
        content = _dl(vurl, headers={"Referer": final_url, "User-Agent": UA_M})
        if content:
            log.info(f"Shopee download OK: {len(content)//1024}KB")
            return _save(content, "shopee")

    log.warning(f"Shopee: falhou (vid={vid}, vurl={vurl})")
    return None


# ════════════════════════════════════════════════════
# TIKTOK — TikWM API (vídeo sem marca d'água)
# ════════════════════════════════════════════════════

async def dl_tiktok(url):
    for endpoint in ["https://www.tikwm.com/api/", "https://tikwm.com/api/"]:
        try:
            r = req.post(endpoint, data={"url":url,"hd":1},
                         headers={"User-Agent":UA}, timeout=30)
            d = r.json()
            if d.get("code") == 0 and d.get("data"):
                u = d["data"].get("hdplay") or d["data"].get("play")
                if u:
                    c = _dl(u, {"User-Agent": "okhttp"})
                    if c:
                        log.info(f"TikTok OK: {len(c)//1024}KB")
                        return _save(c, "tt")
        except Exception as e:
            log.warning(f"TikWM {endpoint}: {e}")
    return await dl_ytdlp(url, "tiktok")


# ════════════════════════════════════════════════════
# INSTAGRAM — embed scraping
# ════════════════════════════════════════════════════

async def dl_instagram(url):
    try:
        m = re.search(r'/(p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
        if m:
            sc = m.group(2)
            for embed in [f"https://www.instagram.com/p/{sc}/embed/",
                          f"https://www.instagram.com/reel/{sc}/embed/"]:
                r = req.get(embed, headers={"User-Agent": UA}, timeout=15)
                for pat in [r'"video_url"\s*:\s*"([^"]+)"',
                            r'<video[^>]+src="([^"]+)"',
                            r'property="og:video"[^>]*content="([^"]+)"']:
                    vm = re.search(pat, r.text)
                    if vm:
                        u = vm.group(1).replace("\\u0026","&").replace("\\/","/").replace("&amp;","&")
                        c = _dl(u, {"Referer": "https://www.instagram.com/"})
                        if c:
                            log.info(f"IG OK: {len(c)//1024}KB")
                            return _save(c, "ig")
    except Exception as e:
        log.warning(f"IG: {e}")
    return await dl_ytdlp(url, "instagram")


# ════════════════════════════════════════════════════
# yt-dlp — YouTube, Twitter, Pinterest, Facebook, Kwai
# ════════════════════════════════════════════════════

async def dl_ytdlp(url, plat=""):
    out = str(TMP / f"dl_{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = ["yt-dlp","--no-warnings","--no-playlist","--no-check-certificates",
           "--socket-timeout","30","--retries","5","--extractor-retries","3",
           "-f","best[ext=mp4]/best","--merge-output-format","mp4",
           "-o",out,"--print","after_move:filepath","--user-agent",UA]
    refs = {"tiktok":"https://www.tiktok.com/","instagram":"https://www.instagram.com/",
            "twitter":"https://twitter.com/","pinterest":"https://www.pinterest.com/",
            "shopee":"https://shopee.com.br/"}
    if plat in refs: cmd += ["--add-header", f"Referer:{refs[plat]}"]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(*cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp): return fp
    except: pass
    return None


# ════════════════════════════════════════════════════
# ROTEADOR
# ════════════════════════════════════════════════════

async def download_video(url, plat):
    if plat == "shopee":
        fp = await dl_shopee(url)
        if not fp: fp = await dl_ytdlp(url, "shopee")
        return fp
    if plat == "tiktok": return await dl_tiktok(url)
    if plat == "instagram": return await dl_instagram(url)
    return await dl_ytdlp(url, plat)


# ════════════════════════════════════════════════════
# POST-PROCESSING (limpeza de metadados e compressão)
# Sem delogo — o vídeo baixado JÁ não tem marca d'água.
# ════════════════════════════════════════════════════

def strip_meta(src):
    """Remove metadados sem re-encodar (preserva qualidade)."""
    dst = src.rsplit(".",1)[0] + "_clean.mp4"
    try:
        r = subprocess.run(["ffmpeg","-y","-i",src,
            "-map_metadata","-1","-fflags","+bitexact",
            "-flags:v","+bitexact","-flags:a","+bitexact",
            "-c","copy","-movflags","+faststart",dst],
            capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return src


def compress(src, target=45):
    """Comprime vídeo mantendo qualidade se passar do limite do Telegram."""
    sz = os.path.getsize(src) / (1024*1024)
    if sz <= target: return src
    dst = src.rsplit(".",1)[0] + "_comp.mp4"
    try:
        p = subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration",
                           "-of","csv=p=0",src], capture_output=True, timeout=30)
        dur = float(p.stdout.decode().strip() or "60")
        vbr = max(int((target*8*1024*1024/dur)*0.88), 700000)
        subprocess.run(["ffmpeg","-y","-i",src,
            "-c:v","libx264","-b:v",str(vbr),
            "-preset","medium","-crf","23",
            "-c:a","aac","-b:a","128k",
            "-movflags","+faststart","-map_metadata","-1",dst],
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
    """Escape para Markdown V2."""
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(t))


# ════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    await update.message.reply_text(
        "🚀 *Viral Engine*\n\n"
        "Cole o link do vídeo\\.\n"
        "Eu baixo sem marca d'água em qualidade original\\.\n"
        "E gero legenda \\+ hashtags virais\\.\n\n"
        "🛒 Shopee · 🎵 TikTok · ▶️ YouTube\n"
        "🐦 X · 📌 Pinterest · 📘 Facebook\n"
        "🎬 Kwai · 📸 Instagram\n\n"
        f"_{esc(str(s.get('d',0)))} downloads realizados_\n\n"
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
            # Apenas limpeza de metadados (sem delogo, sem blur)
            cleaned = strip_meta(fp)
            final = cleaned if cleaned != fp else fp

            sz = os.path.getsize(final) / (1024*1024)
            if sz > 49:
                try: await status.edit_text(f"🗜 Otimizando ({sz:.0f}MB)...")
                except: pass
                final = compress(final)

            sz = os.path.getsize(final) / (1024*1024)
            if sz <= 49:
                try: await status.delete()
                except: pass
                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption="✅ Sem marca d'água · qualidade original",
                            read_timeout=300, write_timeout=300,
                            supports_streaming=True,
                        )
                    track(uid)
                except Exception as e:
                    log.error(f"Erro envio: {e}")
                    try: await status.edit_text("⚠️ Erro ao enviar. Tente novamente.")
                    except: pass
            else:
                try: await status.edit_text(f"⚠️ Vídeo muito grande ({sz:.0f}MB).")
                except: pass

            cleanup(fp)
            if cleaned and cleaned != fp: cleanup(cleaned)
            if final != fp and final != cleaned: cleanup(final)
        else:
            try: await status.edit_text("⚠️ Não consegui baixar. Verifique se o vídeo é público.")
            except: pass

        # Gerar legenda + hashtags
        data = generate(link)
        ctx.user_data["shopee"] = data.get("shopee", data.get("full", ""))
        ctx.user_data["tiktok"] = data.get("tiktok", data.get("full", ""))
        ctx.user_data["insta"] = data.get("insta", data.get("full", ""))
        ctx.user_data["src"] = link

        await update.message.reply_text(
            data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
                [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
                [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ])
        )

    else:
        # Texto livre / nome de produto
        await update.message.reply_chat_action(ChatAction.TYPING)
        data = generate(link or text)
        ctx.user_data["shopee"] = data.get("shopee", data.get("full", ""))
        ctx.user_data["tiktok"] = data.get("tiktok", data.get("full", ""))
        ctx.user_data["insta"] = data.get("insta", data.get("full", ""))
        ctx.user_data["src"] = link or text

        await update.message.reply_text(
            data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
                [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
                [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ])
        )
        track(uid)


async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.answer()
    except: pass

    action = q.data

    if action == "cp_shopee":
        t = ctx.user_data.get("shopee", "")
        if t:
            await q.message.reply_text(t)
        else:
            await q.message.reply_text("⚠️ Sem legenda armazenada. Envie o link novamente.")

    elif action == "cp_tiktok":
        t = ctx.user_data.get("tiktok", "")
        if t:
            await q.message.reply_text(t)
        else:
            await q.message.reply_text("⚠️ Sem legenda armazenada. Envie o link novamente.")

    elif action == "cp_insta":
        t = ctx.user_data.get("insta", "")
        if t:
            await q.message.reply_text(t)
        else:
            await q.message.reply_text("⚠️ Sem legenda armazenada. Envie o link novamente.")

    elif action == "regen":
        src = ctx.user_data.get("src", "")
        if src:
            data = generate(src)
            ctx.user_data["shopee"] = data.get("shopee", data.get("full", ""))
            ctx.user_data["tiktok"] = data.get("tiktok", data.get("full", ""))
            ctx.user_data["insta"] = data.get("insta", data.get("full", ""))

            await q.message.reply_text(
                data["full"],
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
                    [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
                    [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
                    [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
                ])
            )
        else:
            await q.message.reply_text("⚠️ Envie um link ou nome de produto primeiro.")


async def post_init(app):
    await app.bot.set_my_commands([BotCommand("start", "Iniciar")])


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
