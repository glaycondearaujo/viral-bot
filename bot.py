"""
Viral Engine Bot — Download robusto + Legenda viral
Múltiplas estratégias por plataforma com debug detalhado.
"""

import os, re, logging, asyncio, subprocess, tempfile, time, json, threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from collections import deque
import requests as req

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode, ChatAction
from engine import generate, detect_platform, can_download

# ── Logging com buffer circular para debug ──
DEBUG_LOGS = deque(maxlen=50)

class BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            DEBUG_LOGS.append(self.format(record))
        except: pass

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
_buf = BufferHandler(); _buf.setFormatter(_fmt); _buf.setLevel(logging.INFO)
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO, handlers=[logging.StreamHandler()])
log = logging.getLogger("bot")
log.addHandler(_buf)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", "10000"))
TMP = Path(tempfile.gettempdir()) / "vbot"
TMP.mkdir(exist_ok=True)
STATS = TMP / "stats.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
UA_M = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
UA_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"


# ── Health Server (Render) ──
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
def start_http(): HTTPServer(("0.0.0.0", PORT), Health).serve_forever()


# ── Stats ──
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
    try:
        subprocess.run(["pip","install","--upgrade","--break-system-packages","yt-dlp"], capture_output=True, timeout=120)
        v = subprocess.run(["yt-dlp","--version"], capture_output=True, timeout=10)
        log.info(f"yt-dlp: {v.stdout.decode().strip()}")
    except Exception as e:
        log.warning(f"yt-dlp update falhou: {e}")


def _save(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp


def _dl(url, headers=None, min_size=50000):
    """Baixa URL direta. Retorna bytes ou None."""
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        log.info(f"_dl: baixando {url[:80]}...")
        r = req.get(url, headers=h, timeout=180, allow_redirects=True, stream=True)
        log.info(f"_dl: status={r.status_code}, content-type={r.headers.get('content-type','?')}")
        if r.status_code == 200:
            content = r.content
            log.info(f"_dl: recebido {len(content)//1024}KB")
            if len(content) > min_size:
                return content
            else:
                log.warning(f"_dl: arquivo muito pequeno ({len(content)} bytes)")
    except Exception as e:
        log.warning(f"_dl erro: {e}")
    return None


# ════════════════════════════════════════════════════════════════
# SHOPEE VIDEO — 7 ESTRATÉGIAS EM CASCATA
# ════════════════════════════════════════════════════════════════

def _shopee_resolve(url):
    """Resolve link curto seguindo redirecionamentos."""
    try:
        log.info(f"SHOPEE[resolve]: resolvendo {url}")
        r = req.get(url, headers={"User-Agent": UA_M, "Accept-Language": "pt-BR"},
                    allow_redirects=True, timeout=25)
        final = r.url
        log.info(f"SHOPEE[resolve]: → {final}")
        return final, r.text
    except Exception as e:
        log.warning(f"SHOPEE[resolve] erro: {e}")
    return url, ""


def _shopee_vid_from_url(url):
    """Extrai video ID de múltiplos formatos de URL Shopee."""
    patterns = [
        r'share-video/(\d+)',
        r'/video/(\d+)',
        r'videoId=(\d+)',
        r'video_id=(\d+)',
        r'vid=(\d+)',
        r'[?&]v=(\d{10,})',
    ]
    for pat in patterns:
        m = re.search(pat, url, re.I)
        if m:
            log.info(f"SHOPEE[vid]: encontrado via regex {pat!r} → {m.group(1)}")
            return m.group(1)

    # universal-link?redir=...
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if 'redir' in qs:
            redir = unquote(qs['redir'][0])
            log.info(f"SHOPEE[vid]: tentando redir → {redir}")
            for pat in patterns:
                m = re.search(pat, redir, re.I)
                if m:
                    log.info(f"SHOPEE[vid]: encontrado no redir → {m.group(1)}")
                    return m.group(1)
    except: pass
    return None


def _shopee_vid_from_html(html):
    """Busca video_id no HTML (JSON embeddado)."""
    patterns = [
        r'"video_id"\s*:\s*"?(\d{10,})',
        r'"videoId"\s*:\s*"?(\d{10,})',
        r'"vid"\s*:\s*"?(\d{10,})',
        r'share-video/(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            log.info(f"SHOPEE[vid-html]: {m.group(1)}")
            return m.group(1)
    return None


def _shopee_extract_from_html(html, source=""):
    """Extrai URL do vídeo do HTML — múltiplos padrões."""
    if not html: return None

    # Ordem dos padrões: mais específicos primeiro
    patterns = [
        # JSON: default_format.url (estrutura oficial Shopee Video)
        (r'"default_format"\s*:\s*\{[^{}]*?"url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'default_format.url'),
        (r'"default_format"\s*:\s*\{[^{}]*?"url"\s*:\s*"(https?://[^"]+)"', 'default_format.url'),
        # Campos comuns com MP4
        (r'"mms_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'mms_url'),
        (r'"cdn_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'cdn_url'),
        (r'"play_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'play_url'),
        (r'"playUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', 'playUrl'),
        (r'"video_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'video_url'),
        (r'"videoUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', 'videoUrl'),
        (r'"hd_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'hd_url'),
        (r'"download_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'download_url'),
        # Open Graph
        (r'<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)', 'og:video'),
        (r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video', 'og:video (reversed)'),
        (r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)', 'twitter:player'),
        # Tags HTML
        (r'<video[^>]+src=["\']([^"\']+)["\']', '<video>'),
        (r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']', '<source>'),
    ]

    for pat, name in patterns:
        for m in re.finditer(pat, html, re.I):
            u = m.group(1)
            # Decodificar escapes JSON
            u = (u.replace("\\u002F","/").replace("\\u0026","&")
                   .replace("\\/","/").replace("&amp;","&"))
            # Validar
            if len(u) < 30: continue
            if not u.startswith("http"): continue
            low = u.lower()
            if any(x in low for x in ["thumb","cover","preview","poster",".jpg",".jpeg",".png",".gif",".webp",".svg"]):
                continue
            log.info(f"SHOPEE[html-{source}]: {name} → {u[:100]}")
            return u

    # Última tentativa: qualquer .mp4
    for m in re.finditer(r'https?://[^\s"\'<>\\]+\.mp4(?:\?[^\s"\'<>\\]*)?', html):
        u = m.group(0)
        low = u.lower()
        if any(x in low for x in ["thumb","cover","preview","poster"]): continue
        log.info(f"SHOPEE[html-{source}]: generic .mp4 → {u[:100]}")
        return u

    return None


async def dl_shopee(url):
    """Download Shopee Video — 7 estratégias em cascata."""
    log.info(f"━━━ SHOPEE START: {url}")

    # Estratégia 1: Resolver link e extrair do HTML inicial
    final_url, initial_html = _shopee_resolve(url)

    vurl = None
    if initial_html:
        vurl = _shopee_extract_from_html(initial_html, "inicial")
        if vurl:
            content = _dl(vurl, {"Referer": final_url})
            if content:
                log.info(f"━━━ SHOPEE OK (estrategia 1)")
                return _save(content, "shopee")

    # Estratégia 2: Extrair video_id e acessar página share-video diretamente
    vid = _shopee_vid_from_url(final_url) or _shopee_vid_from_url(url)
    if not vid and initial_html:
        vid = _shopee_vid_from_html(initial_html)
    log.info(f"SHOPEE[vid final]: {vid}")

    if vid:
        # Múltiplas URLs de share-video
        share_urls = [
            f"https://sv.shopee.com.br/share-video/{vid}",
            f"https://sv.shopee.com.br/share-video/{vid}?",
        ]
        for surl in share_urls:
            for user_agent, label in [(UA_M, "mobile"), (UA, "desktop"), (UA_IOS, "ios")]:
                try:
                    log.info(f"SHOPEE[share]: {surl} ({label})")
                    r = req.get(surl, headers={
                        "User-Agent": user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                        "Referer": "https://sv.shopee.com.br/",
                    }, timeout=20, allow_redirects=True)
                    log.info(f"SHOPEE[share]: status={r.status_code}, html={len(r.text)}b")
                    vurl = _shopee_extract_from_html(r.text, f"share-{label}")
                    if vurl:
                        content = _dl(vurl, {"Referer": surl, "User-Agent": user_agent})
                        if content:
                            log.info(f"━━━ SHOPEE OK (estrategia 2-{label})")
                            return _save(content, "shopee")
                except Exception as e:
                    log.warning(f"SHOPEE[share] {label}: {e}")

    # Estratégia 3: yt-dlp (pode ter suporte generic)
    log.info("SHOPEE: tentando yt-dlp...")
    try:
        fp = await dl_ytdlp(final_url, "shopee")
        if fp:
            log.info(f"━━━ SHOPEE OK (estrategia 3 - yt-dlp)")
            return fp
    except Exception as e:
        log.warning(f"SHOPEE yt-dlp: {e}")

    # Estratégia 4: yt-dlp com URL original (pode ser diferente após redirect)
    if url != final_url:
        try:
            fp = await dl_ytdlp(url, "shopee")
            if fp:
                log.info(f"━━━ SHOPEE OK (estrategia 4)")
                return fp
        except: pass

    log.warning(f"━━━ SHOPEE FALHOU: todas as estratégias")
    return None


# ════════════════════════════════════════════════════════════════
# TIKTOK — TikWM + fallbacks
# ════════════════════════════════════════════════════════════════

async def dl_tiktok(url):
    log.info(f"━━━ TIKTOK START: {url}")
    for endpoint in ["https://www.tikwm.com/api/", "https://tikwm.com/api/"]:
        try:
            log.info(f"TIKTOK: {endpoint}")
            r = req.post(endpoint, data={"url": url, "hd": 1},
                         headers={"User-Agent": UA}, timeout=30)
            d = r.json()
            if d.get("code") == 0 and d.get("data"):
                u = d["data"].get("hdplay") or d["data"].get("play")
                if u:
                    c = _dl(u, {"User-Agent": "okhttp"})
                    if c:
                        log.info(f"━━━ TIKTOK OK")
                        return _save(c, "tt")
        except Exception as e:
            log.warning(f"TIKTOK {endpoint}: {e}")

    log.info("TIKTOK: yt-dlp fallback")
    return await dl_ytdlp(url, "tiktok")


# ════════════════════════════════════════════════════════════════
# INSTAGRAM — embed + yt-dlp
# ════════════════════════════════════════════════════════════════

async def dl_instagram(url):
    log.info(f"━━━ IG START: {url}")
    try:
        m = re.search(r'/(p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
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
                            u = (vm.group(1).replace("\\u0026","&")
                                 .replace("\\/","/").replace("&amp;","&"))
                            c = _dl(u, {"Referer": "https://www.instagram.com/"})
                            if c:
                                log.info(f"━━━ IG OK")
                                return _save(c, "ig")
                except Exception as e:
                    log.warning(f"IG embed: {e}")
    except Exception as e:
        log.warning(f"IG: {e}")

    return await dl_ytdlp(url, "instagram")


# ════════════════════════════════════════════════════════════════
# yt-dlp — YouTube, Twitter, Pinterest, Facebook, Kwai, fallback
# ════════════════════════════════════════════════════════════════

async def dl_ytdlp(url, plat=""):
    log.info(f"━━━ YT-DLP START: {url} (plat={plat})")
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
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp):
                log.info(f"━━━ YT-DLP OK: {os.path.getsize(fp)//1024}KB")
                return fp
        err = stderr.decode()[:500] if stderr else ""
        log.warning(f"YT-DLP falhou: rc={proc.returncode}, err={err}")
    except asyncio.TimeoutError:
        log.warning(f"YT-DLP timeout")
    except Exception as e:
        log.warning(f"YT-DLP erro: {e}")
    return None


# ════════════════════════════════════════════════════════════════
# ROTEADOR
# ════════════════════════════════════════════════════════════════

async def download_video(url, plat):
    if plat == "shopee":
        fp = await dl_shopee(url)
        return fp
    if plat == "tiktok": return await dl_tiktok(url)
    if plat == "instagram": return await dl_instagram(url)
    return await dl_ytdlp(url, plat)


# ════════════════════════════════════════════════════════════════
# POST-PROCESSING (sem delogo — qualidade preservada)
# ════════════════════════════════════════════════════════════════

def strip_meta(src):
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
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(t))


# ════════════════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════════════════

def _kb():
    """Teclado inline padrão com callbacks."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
        [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
        [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
        [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
    ])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    await update.message.reply_text(
        "🚀 *Viral Engine*\n\n"
        "Cole o link do vídeo\\.\n"
        "Eu baixo sem marca d'água e gero legenda \\+ hashtags\\.\n\n"
        "🛒 Shopee · 🎵 TikTok · ▶️ YouTube\n"
        "🐦 X · 📌 Pinterest · 📘 Facebook\n"
        "🎬 Kwai · 📸 Instagram\n\n"
        f"_{esc(str(s.get('d',0)))} downloads realizados_\n\n"
        "Comandos:\n"
        "/start \\- início\n"
        "/debug \\- últimos logs \\(para suporte\\)",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Mostra os últimos 50 logs — útil para diagnosticar falhas."""
    if not DEBUG_LOGS:
        await update.message.reply_text("Sem logs disponíveis.")
        return
    logs_text = "\n".join(list(DEBUG_LOGS)[-50:])
    if len(logs_text) > 3800:
        logs_text = logs_text[-3800:]
    await update.message.reply_text(f"```\n{logs_text}\n```", parse_mode=ParseMode.MARKDOWN_V2)


async def handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text or len(text) < 3: return

    uid = update.effective_user.id
    link_m = re.search(r'https?://\S+', text)
    link = link_m.group(0) if link_m else None
    plat = detect_platform(link) if link else None

    log.info(f"━━━━━━━━━━ NOVA MSG de {uid}: link={link} plat={plat}")

    if link and can_download(plat):
        status = await update.message.reply_text(f"⏳ Baixando do {plat.upper()}...")
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        fp = None
        error_detail = ""
        try:
            fp = await download_video(link, plat)
        except Exception as e:
            error_detail = str(e)[:200]
            log.error(f"download_video erro: {e}")

        if fp:
            cleaned = strip_meta(fp)
            final = cleaned if cleaned != fp else fp

            sz = os.path.getsize(final) / (1024*1024)
            log.info(f"Tamanho final: {sz:.1f}MB")

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
                    try: await status.edit_text(f"⚠️ Erro ao enviar: {str(e)[:100]}")
                    except: pass
            else:
                try: await status.edit_text(f"⚠️ Vídeo muito grande ({sz:.0f}MB).")
                except: pass

            cleanup(fp)
            if cleaned and cleaned != fp: cleanup(cleaned)
            if final != fp and final != cleaned: cleanup(final)
        else:
            msg = "⚠️ Não consegui baixar. Envie /debug para ver os detalhes."
            try: await status.edit_text(msg)
            except: pass

        # Sempre gerar legenda, independente de sucesso no download
        try:
            data = generate(link)
            ctx.user_data["shopee"] = data.get("shopee", "")
            ctx.user_data["tiktok"] = data.get("tiktok", "")
            ctx.user_data["insta"] = data.get("insta", "")
            ctx.user_data["src"] = link
            log.info(f"Caption gerada. user_data keys: {list(ctx.user_data.keys())}")

            await update.message.reply_text(data["full"], reply_markup=_kb())
        except Exception as e:
            log.error(f"Erro gerando legenda: {e}")

    else:
        # Texto livre — apenas legenda
        await update.message.reply_chat_action(ChatAction.TYPING)
        try:
            data = generate(link or text)
            ctx.user_data["shopee"] = data.get("shopee", "")
            ctx.user_data["tiktok"] = data.get("tiktok", "")
            ctx.user_data["insta"] = data.get("insta", "")
            ctx.user_data["src"] = link or text
            log.info(f"Caption gerada (texto). user_data keys: {list(ctx.user_data.keys())}")

            await update.message.reply_text(data["full"], reply_markup=_kb())
            track(uid)
        except Exception as e:
            log.error(f"Erro legenda: {e}")
            await update.message.reply_text(f"⚠️ Erro: {str(e)[:100]}")


async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handler dos botões inline — com debug."""
    q = update.callback_query
    try:
        await q.answer()
    except Exception as e:
        log.warning(f"q.answer erro: {e}")

    action = q.data
    log.info(f"CALLBACK: {action} — user_data keys: {list(ctx.user_data.keys())}")

    mapping = {
        "cp_shopee": ("shopee", "🛒 Legenda Shopee"),
        "cp_tiktok": ("tiktok", "🎵 Legenda TikTok"),
        "cp_insta":  ("insta",  "📸 Legenda Instagram"),
    }

    if action in mapping:
        key, label = mapping[action]
        text = ctx.user_data.get(key, "")
        log.info(f"CALLBACK {action}: texto tem {len(text)} chars")
        if text:
            await q.message.reply_text(f"{label}:\n\n{text}")
        else:
            await q.message.reply_text(
                "⚠️ Sem legenda armazenada nesta conversa.\n"
                "Envie o link (ou nome do produto) novamente."
            )

    elif action == "regen":
        src = ctx.user_data.get("src", "")
        log.info(f"REGEN src: {src[:60] if src else '(vazio)'}")
        if src:
            try:
                data = generate(src)
                ctx.user_data["shopee"] = data.get("shopee", "")
                ctx.user_data["tiktok"] = data.get("tiktok", "")
                ctx.user_data["insta"] = data.get("insta", "")
                await q.message.reply_text(data["full"], reply_markup=_kb())
            except Exception as e:
                log.error(f"Regen erro: {e}")
                await q.message.reply_text(f"⚠️ Erro: {str(e)[:100]}")
        else:
            await q.message.reply_text("⚠️ Envie um link ou nome de produto primeiro.")


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "Iniciar"),
        BotCommand("debug", "Ver logs (suporte)"),
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

    log.info("🚀 Bot rodando!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
