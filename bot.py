"""
Viral Engine Bot — Download Shopee/TikTok/YouTube/etc + Legenda Viral
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

# ── Logging ──
DEBUG_LOGS = deque(maxlen=80)

class BufferHandler(logging.Handler):
    def emit(self, record):
        try: DEBUG_LOGS.append(self.format(record))
        except: pass

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
_buf = BufferHandler(); _buf.setFormatter(_fmt); _buf.setLevel(logging.INFO)
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO,
                    handlers=[logging.StreamHandler()])
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


# ── Health ──
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
        log.warning(f"yt-dlp update: {e}")


def _save(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp


def _dl(url, headers=None, min_size=30000):
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        log.info(f"_dl: {url[:80]}")
        r = req.get(url, headers=h, timeout=180, allow_redirects=True)
        log.info(f"_dl: status={r.status_code}, size={len(r.content)//1024 if r.content else 0}KB, type={r.headers.get('content-type','?')[:40]}")
        if r.status_code == 200:
            ct = r.headers.get('content-type','').lower()
            if 'video' in ct or 'octet-stream' in ct or 'mp4' in ct:
                if len(r.content) > min_size:
                    return r.content
            elif len(r.content) > min_size:
                # Confiar se for grande, mesmo sem content-type
                return r.content
    except Exception as e:
        log.warning(f"_dl erro: {e}")
    return None


# ════════════════════════════════════════════════════════════════
# SHOPEE VIDEO — estratégias em cascata
# ════════════════════════════════════════════════════════════════

def _shopee_resolve(url):
    """Resolve link curto. Retorna (url_final, html)."""
    try:
        log.info(f"SHOPEE[resolve]: {url}")
        r = req.get(url, headers={
            "User-Agent": UA_M,
            "Accept-Language": "pt-BR,pt;q=0.9"
        }, allow_redirects=True, timeout=25)
        log.info(f"SHOPEE[resolve]: → {r.url[:120]}")
        return r.url, r.text
    except Exception as e:
        log.warning(f"SHOPEE[resolve] erro: {e}")
    return url, ""


def _shopee_real_share_url(resolved_url):
    """Extrai URL real do share-video de dentro do universal-link?redir=..."""
    try:
        parsed = urlparse(resolved_url)
        qs = parse_qs(parsed.query)
        if 'redir' in qs:
            real = unquote(qs['redir'][0])
            log.info(f"SHOPEE[unwrap]: {real[:120]}")
            return real
    except Exception as e:
        log.warning(f"SHOPEE[unwrap] erro: {e}")
    return resolved_url


def _shopee_extract_vid(url):
    """Extrai video ID (base64 ou numérico) da URL."""
    # ID base64 OU numérico, tamanho >= 8
    ID_PAT = r'([A-Za-z0-9+/=_\-]{8,})'
    patterns = [
        (rf'share-video/{ID_PAT}(?:[?&#]|$)', 'share-video/'),
        (rf'/video/{ID_PAT}(?:[?&#]|$)', '/video/'),
        (rf'videoId={ID_PAT}', 'videoId='),
        (rf'video_id={ID_PAT}', 'video_id='),
    ]

    # Testar na URL direta
    for pat, name in patterns:
        m = re.search(pat, url, re.I)
        if m:
            vid = m.group(1).rstrip('=') + '=' * (4 - len(m.group(1)) % 4) if '=' in m.group(1) else m.group(1)
            # Só aceitar se tiver característica de ID (letra+num misturado ou só número longo)
            if len(m.group(1)) >= 8:
                log.info(f"SHOPEE[vid]: via '{name}' → {m.group(1)}")
                return m.group(1)

    # Tentar dentro de redir=
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if 'redir' in qs:
            redir = unquote(qs['redir'][0])
            for pat, name in patterns:
                m = re.search(pat, redir, re.I)
                if m and len(m.group(1)) >= 8:
                    log.info(f"SHOPEE[vid]: via redir '{name}' → {m.group(1)}")
                    return m.group(1)
    except: pass

    return None


def _shopee_vid_from_html(html):
    patterns = [
        r'"video_?id"\s*:\s*"([A-Za-z0-9+/=_\-]{8,})"',
        r'"videoId"\s*:\s*"([A-Za-z0-9+/=_\-]{8,})"',
        r'"vid"\s*:\s*"([A-Za-z0-9+/=_\-]{8,})"',
        r'share-video/([A-Za-z0-9+/=_\-]{8,})',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            log.info(f"SHOPEE[vid-html]: {m.group(1)}")
            return m.group(1)
    return None


def _shopee_extract_video_url(html, source=""):
    """Extrai URL do vídeo MP4 do HTML."""
    if not html or len(html) < 100:
        return None

    # Padrões específicos da Shopee (mais confiáveis primeiro)
    patterns = [
        (r'"default_format"\s*:\s*\{[^{}]*?"url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'default_format.url'),
        (r'"default_format"\s*:\s*\{[^{}]*?"url"\s*:\s*"(https?://[^"]+)"', 'default_format.url (no mp4)'),
        (r'"formats"\s*:\s*\[[^\]]*?"url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'formats[].url'),
        (r'"mms_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'mms_url'),
        (r'"cdn_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'cdn_url'),
        (r'"play_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'play_url'),
        (r'"playUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', 'playUrl'),
        (r'"video_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'video_url'),
        (r'"videoUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', 'videoUrl'),
        (r'"hd_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'hd_url'),
        (r'"download_url"\s*:\s*"([^"]+\.mp4[^"]*)"', 'download_url'),
        # Open Graph
        (r'<meta[^>]+property=["\']og:video(?::url|:secure_url)?["\'][^>]+content=["\']([^"\']+)', 'og:video'),
        (r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video', 'og:video rev'),
        (r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)', 'twitter:player'),
        # HTML tags
        (r'<video[^>]+src=["\']([^"\']+)["\']', 'video src'),
        (r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']', 'source src'),
    ]

    for pat, name in patterns:
        for m in re.finditer(pat, html, re.I):
            u = m.group(1)
            u = (u.replace("\\u002F","/").replace("\\u0026","&")
                 .replace("\\/","/").replace("&amp;","&").replace("\\\"",'"'))
            if len(u) < 25 or not u.startswith("http"):
                continue
            low = u.lower()
            # Descartar thumbnails/imagens
            if any(x in low for x in [".jpg",".jpeg",".png",".gif",".webp",".svg",
                                      "thumb","cover","preview","poster","avatar",
                                      "_tn",".ico"]):
                continue
            log.info(f"SHOPEE[html-{source}] {name}: {u[:100]}")
            return u

    # Fallback: qualquer .mp4 limpo
    for m in re.finditer(r'https?://[^\s"\'<>\\(){}]+\.mp4(?:\?[^\s"\'<>\\(){}]*)?', html):
        u = m.group(0)
        low = u.lower()
        if any(x in low for x in ["thumb","cover","preview","poster"]):
            continue
        log.info(f"SHOPEE[html-{source}] generic mp4: {u[:100]}")
        return u

    return None


async def dl_shopee(url):
    """Download Shopee Video SEM marca d'água via scraping do share-video."""
    log.info(f"━━━━━━ SHOPEE START: {url}")

    # 1. Resolver link curto (shp.ee → universal-link)
    resolved, html1 = _shopee_resolve(url)

    # 2. Desembrulhar o universal-link (pegar o redir=...)
    real_share = _shopee_real_share_url(resolved)
    log.info(f"SHOPEE[real]: {real_share[:120]}")

    # 3. Extrair vid
    vid = _shopee_extract_vid(resolved) or _shopee_extract_vid(url)
    if not vid and html1:
        vid = _shopee_vid_from_html(html1)
    log.info(f"SHOPEE[vid]: {vid}")

    # 4. Tentar extrair vídeo do HTML inicial (universal-link geralmente é só redirect,
    #    mas às vezes tem metadata)
    if html1:
        vurl = _shopee_extract_video_url(html1, "universal")
        if vurl:
            content = _dl(vurl, {"Referer": resolved, "User-Agent": UA_M})
            if content:
                log.info(f"━━ SHOPEE OK (universal-link HTML)")
                return _save(content, "shopee")

    # 5. Acessar página /share-video/ diretamente com múltiplos user agents
    urls_to_try = []
    if real_share and real_share != resolved:
        urls_to_try.append(real_share)
    if vid:
        urls_to_try.append(f"https://sv.shopee.com.br/share-video/{vid}")

    for target_url in urls_to_try:
        for ua, ua_name in [(UA_M, "mobile"), (UA_IOS, "ios"), (UA, "desktop")]:
            try:
                log.info(f"SHOPEE[fetch-{ua_name}]: {target_url[:120]}")
                r = req.get(target_url, headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Referer": "https://sv.shopee.com.br/",
                    "sec-ch-ua-mobile": "?1" if ua_name == "mobile" else "?0",
                }, timeout=25, allow_redirects=True)
                log.info(f"SHOPEE[fetch-{ua_name}]: status={r.status_code}, html={len(r.text)}b")

                if r.status_code == 200 and len(r.text) > 1000:
                    vurl = _shopee_extract_video_url(r.text, f"share-{ua_name}")
                    if vurl:
                        content = _dl(vurl, {"Referer": target_url, "User-Agent": ua})
                        if content:
                            log.info(f"━━ SHOPEE OK (share-video {ua_name})")
                            return _save(content, "shopee")
                    else:
                        # Se o HTML não tem vídeo, pode ser uma página SPA que carrega via JS
                        # Tentar buscar endpoints de API no JS
                        api_patterns = [
                            r'["\'](?:/api/v\d+/[^"\']+|https?://[^"\']*api[^"\']+video[^"\']*)["\']',
                        ]
                        for ap in api_patterns:
                            matches = re.findall(ap, r.text)[:5]
                            for api_url in matches:
                                if not api_url.startswith('http'):
                                    api_url = "https://sv.shopee.com.br" + api_url
                                log.info(f"SHOPEE[api-try]: {api_url[:100]}")
            except Exception as e:
                log.warning(f"SHOPEE[fetch-{ua_name}] erro: {e}")

    # 6. yt-dlp como fallback final (pode funcionar se a URL for reconhecida pelo generic extractor)
    log.info("SHOPEE: yt-dlp fallback")
    for try_url in [real_share, resolved, url]:
        if try_url and try_url.startswith('http'):
            try:
                fp = await dl_ytdlp(try_url, "shopee")
                if fp:
                    log.info(f"━━ SHOPEE OK (yt-dlp)")
                    return fp
            except: pass

    log.warning(f"━━ SHOPEE FALHOU")
    return None


# ════════════════════════════════════════════════════════════════
# OUTRAS PLATAFORMAS
# ════════════════════════════════════════════════════════════════

async def dl_tiktok(url):
    log.info(f"━━ TIKTOK: {url}")
    for endpoint in ["https://www.tikwm.com/api/", "https://tikwm.com/api/"]:
        try:
            r = req.post(endpoint, data={"url": url, "hd": 1},
                         headers={"User-Agent": UA}, timeout=30)
            d = r.json()
            if d.get("code") == 0 and d.get("data"):
                u = d["data"].get("hdplay") or d["data"].get("play")
                if u:
                    c = _dl(u, {"User-Agent": "okhttp"})
                    if c: return _save(c, "tt")
        except Exception as e:
            log.warning(f"TIKWM {endpoint}: {e}")
    return await dl_ytdlp(url, "tiktok")


async def dl_instagram(url):
    log.info(f"━━ IG: {url}")
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
                            if c: return _save(c, "ig")
                except Exception as e:
                    log.warning(f"IG embed: {e}")
    except Exception as e:
        log.warning(f"IG: {e}")
    return await dl_ytdlp(url, "instagram")


async def dl_ytdlp(url, plat=""):
    log.info(f"━━ YT-DLP: {url[:80]} (plat={plat})")
    out = str(TMP / f"dl_{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = ["yt-dlp","--no-warnings","--no-playlist","--no-check-certificates",
           "--socket-timeout","30","--retries","5","--extractor-retries","3",
           "-f","best[ext=mp4]/best","--merge-output-format","mp4",
           "-o",out,"--print","after_move:filepath","--user-agent",UA]
    refs = {"tiktok":"https://www.tiktok.com/","instagram":"https://www.instagram.com/",
            "twitter":"https://twitter.com/","pinterest":"https://www.pinterest.com/",
            "shopee":"https://sv.shopee.com.br/"}
    if plat in refs: cmd += ["--add-header", f"Referer:{refs[plat]}"]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(*cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp):
                log.info(f"YT-DLP OK: {os.path.getsize(fp)//1024}KB")
                return fp
        err = stderr.decode()[:400] if stderr else ""
        log.warning(f"YT-DLP rc={proc.returncode}: {err}")
    except asyncio.TimeoutError:
        log.warning("YT-DLP timeout")
    except Exception as e:
        log.warning(f"YT-DLP erro: {e}")
    return None


async def download_video(url, plat):
    if plat == "shopee": return await dl_shopee(url)
    if plat == "tiktok": return await dl_tiktok(url)
    if plat == "instagram": return await dl_instagram(url)
    return await dl_ytdlp(url, plat)


# ════════════════════════════════════════════════════════════════
# POST-PROCESSING
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
    sz = os.path.getsize(src)/(1024*1024)
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copiar legenda + hashtags #1", callback_data="cp_v1")],
        [InlineKeyboardButton("📋 Copiar versão alternativa #2", callback_data="cp_v2")],
        [InlineKeyboardButton("📋 Copiar versão alternativa #3", callback_data="cp_v3")],
        [InlineKeyboardButton("🔄 Gerar nova legenda", callback_data="regen")],
    ])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    await update.message.reply_text(
        "🚀 *Viral Engine*\n\n"
        "Cole o link do vídeo\\.\n"
        "Eu baixo sem marca d'água em qualidade original\\.\n"
        "E gero legenda \\+ hashtags do produto\\.\n\n"
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
    link_m = re.search(r'https?://\S+', text)
    link = link_m.group(0) if link_m else None
    plat = detect_platform(link) if link else None

    log.info(f"━━━━━━━━ NOVA MSG user={uid}: link={link} plat={plat}")

    if link and can_download(plat):
        status = await update.message.reply_text(f"⏳ Baixando do {plat.upper()}...")
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        fp = None
        try:
            fp = await download_video(link, plat)
        except Exception as e:
            log.error(f"download_video erro: {e}")

        if fp:
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
            try: await status.edit_text("⚠️ Não consegui baixar. Envie /debug para ver os detalhes técnicos.")
            except: pass

        # Gerar legenda sempre
        try:
            data = generate(link)
            ctx.user_data["v1"] = data["shopee"]
            ctx.user_data["v2"] = data["tiktok"]
            ctx.user_data["v3"] = data["insta"]
            ctx.user_data["src"] = link
            log.info(f"Caption gerada (cat={data.get('category','?')})")
            await update.message.reply_text(data["full"], reply_markup=_kb())
        except Exception as e:
            log.error(f"Legenda erro: {e}")

    else:
        await update.message.reply_chat_action(ChatAction.TYPING)
        try:
            data = generate(link or text)
            ctx.user_data["v1"] = data["shopee"]
            ctx.user_data["v2"] = data["tiktok"]
            ctx.user_data["v3"] = data["insta"]
            ctx.user_data["src"] = link or text
            log.info(f"Caption gerada por texto (cat={data.get('category','?')})")
            await update.message.reply_text(data["full"], reply_markup=_kb())
            track(uid)
        except Exception as e:
            log.error(f"Legenda texto erro: {e}")
            await update.message.reply_text(f"⚠️ Erro: {str(e)[:100]}")


async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try: await q.answer()
    except: pass

    action = q.data
    log.info(f"CALLBACK: {action}")

    if action in ("cp_v1","cp_v2","cp_v3"):
        key = action.replace("cp_", "")
        text = ctx.user_data.get(key, "")
        if text:
            await q.message.reply_text(text)
        else:
            await q.message.reply_text("⚠️ Envie o link ou produto novamente.")

    elif action == "regen":
        src = ctx.user_data.get("src", "")
        if src:
            try:
                data = generate(src)
                ctx.user_data["v1"] = data["shopee"]
                ctx.user_data["v2"] = data["tiktok"]
                ctx.user_data["v3"] = data["insta"]
                await q.message.reply_text(data["full"], reply_markup=_kb())
            except Exception as e:
                log.error(f"Regen erro: {e}")
                await q.message.reply_text(f"⚠️ {str(e)[:80]}")
        else:
            await q.message.reply_text("⚠️ Envie um link primeiro.")


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
