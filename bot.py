"""
Viral Engine Bot

Shopee: 4 camadas (API/HTML/og:video/mobile)
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
UA_M = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
def start_http(): HTTPServer(("0.0.0.0", PORT), Health).serve_forever()

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
    try: subprocess.run(["pip","install","--upgrade","--break-system-packages","yt-dlp"], capture_output=True, timeout=120)
    except: pass

def _save(data, prefix="vid"):
    fp = str(TMP / f"{prefix}_{int(time.time())}_{os.getpid()}.mp4")
    with open(fp, "wb") as f: f.write(data)
    return fp

def _dl(url, headers=None):
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        r = req.get(url, headers=h, timeout=120, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > 50000: return r.content
    except: pass
    return None

# ════════════════════════════════════════════════════
# SHOPEE — 4 CAMADAS
# ════════════════════════════════════════════════════

def _resolve(url):
    try: return req.get(url, headers={"User-Agent": UA_M}, allow_redirects=True, timeout=15).url
    except: return url

def _shopee_api(url):
    m = re.search(r'i\.(\d+)\.(\d+)', url)
    if not m:
        m = re.search(r'/product/(\d+)/(\d+)', url)
    if not m: return None
    sid, iid = m.group(1), m.group(2)
    log.info(f"Shopee API: shop={sid} item={iid}")
    try:
        r = req.get(f"https://shopee.com.br/api/v4/pdp/get_pc?shop_id={sid}&item_id={iid}",
            headers={"User-Agent":UA,"Referer":url,"x-shopee-language":"pt-BR"}, timeout=15)
        if r.status_code == 200:
            item = r.json().get("data",{}).get("item",{})
            for v in item.get("video_info_list",[]):
                for k in ["video_url","url","default_format"]:
                    u = v.get(k)
                    if isinstance(u,dict): u = u.get("url")
                    if u and ("mp4" in u or "video" in u):
                        log.info(f"Shopee API OK: {u[:60]}"); return u
            vid = item.get("video")
            if vid:
                u = vid if isinstance(vid,str) else vid.get("video_url","")
                if u: return u
    except Exception as e: log.warning(f"Shopee API: {e}")
    return None

def _shopee_html(url, html):
    pats = [
        r'"(?:video_url|videoUrl|playUrl|play_url)"\s*:\s*"(https?://[^"]+)"',
        r'(https?://(?:cf|cv|down)[^"\'\\\s]+shopee[^"\'\\\s]*\.mp4[^"\'\\\s]*)',
        r'(https?://[^"\'\\\s]*susercontent\.com[^"\'\\\s]*\.mp4[^"\'\\\s]*)',
        r'"(https?://[^"]+\.mp4(?:\?[^"]*)?)"',
        r'<video[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+\.mp4[^"\']*)["\']',
    ]
    for p in pats:
        for m in re.findall(p, html, re.I):
            c = m.replace("\\u002F","/").replace("\\/","/").replace("\\u0026","&")
            if len(c)<20: continue
            if any(x in c.lower() for x in ["thumb","image","jpg","png","gif","webp"]): continue
            log.info(f"Shopee HTML: {c[:60]}"); return c
    return None

def _shopee_og(html):
    m = re.search(r'<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if not m: m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video', html, re.I)
    if m:
        u = m.group(1).replace("&amp;","&")
        log.info(f"Shopee OG: {u[:60]}"); return u
    return None

def _shopee_mobile(url):
    try:
        r = req.get(url, headers={"User-Agent":UA_M,"Accept-Language":"pt-BR"}, timeout=15, allow_redirects=True)
        for p in [r'"(?:video_url|videoUrl|playUrl)"\s*:\s*"(https?://[^"]+)"', r'"(https?://[^"]+\.mp4[^"]*)"']:
            for m in re.findall(p, r.text, re.I):
                c = m.replace("\\u002F","/").replace("\\/","/").replace("\\u0026","&")
                if len(c)<20 or any(x in c.lower() for x in ["thumb","jpg","png"]): continue
                log.info(f"Shopee Mobile: {c[:60]}"); return c
    except: pass
    return None

async def dl_shopee(url):
    resolved = _resolve(url)
    log.info(f"Shopee: {url} → {resolved}")
    html = ""
    try: html = req.get(resolved, headers={"User-Agent":UA}, timeout=15).text
    except: pass

    for layer_fn, args in [
        (_shopee_api, (resolved,)),
        (_shopee_html, (resolved, html)),
        (_shopee_og, (html,)),
        (_shopee_mobile, (resolved,)),
    ]:
        if not args[-1]: continue  # skip if no html
        vurl = layer_fn(*args)
        if vurl:
            content = _dl(vurl, {"Referer": resolved})
            if content:
                log.info(f"Shopee download OK: {len(content)//1024}KB")
                return _save(content, "shopee")
    log.warning("Shopee: todas as camadas falharam")
    return None

# ════════════════════════════════════════════════════
# OUTROS
# ════════════════════════════════════════════════════

async def dl_tiktok(url):
    try:
        r = req.post("https://www.tikwm.com/api/", data={"url":url,"hd":1}, headers={"User-Agent":UA}, timeout=30)
        d = r.json()
        if d.get("code")==0 and d.get("data"):
            u = d["data"].get("hdplay") or d["data"].get("play")
            if u:
                c = _dl(u, {"User-Agent":"okhttp"})
                if c: return _save(c, "tt")
    except: pass
    return await dl_ytdlp(url, "tiktok")

async def dl_instagram(url):
    try:
        m = re.search(r'/(p|reel|reels)/([A-Za-z0-9_-]+)', url)
        if m:
            r = req.get(f"https://www.instagram.com/p/{m.group(2)}/embed/", headers={"User-Agent":UA}, timeout=15)
            vm = re.search(r'"video_url"\s*:\s*"([^"]+)"', r.text)
            if not vm: vm = re.search(r'<video[^>]+src="([^"]+)"', r.text)
            if vm:
                u = vm.group(1).replace("\\u0026","&").replace("\\/","/")
                c = _dl(u, {"Referer":"https://www.instagram.com/"})
                if c: return _save(c, "ig")
    except: pass
    return await dl_ytdlp(url, "instagram")

async def dl_ytdlp(url, plat=""):
    out = str(TMP / f"dl_{int(time.time())}_{os.getpid()}.%(ext)s")
    cmd = ["yt-dlp","--no-warnings","--no-playlist","--no-check-certificates",
        "--socket-timeout","30","--retries","5","--extractor-retries","3",
        "-f","best[ext=mp4]/best","--merge-output-format","mp4",
        "-o",out,"--print","after_move:filepath","--user-agent",UA]
    refs = {"tiktok":"https://www.tiktok.com/","instagram":"https://www.instagram.com/",
            "twitter":"https://twitter.com/","pinterest":"https://www.pinterest.com/"}
    if plat in refs: cmd += ["--add-header",f"Referer:{refs[plat]}"]
    cmd.append(url)
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0:
            fp = stdout.decode().strip().split("\n")[-1].strip()
            if fp and os.path.exists(fp): return fp
    except: pass
    return None

async def download_video(url, plat):
    if plat == "shopee":
        fp = await dl_shopee(url)
        if not fp:  # fallback: yt-dlp
            fp = await dl_ytdlp(url, "shopee")
        return fp
    if plat == "tiktok": return await dl_tiktok(url)
    if plat == "instagram": return await dl_instagram(url)
    return await dl_ytdlp(url, plat)

def strip_meta(src):
    dst = src.rsplit(".",1)[0] + "_c.mp4"
    try:
        r = subprocess.run(["ffmpeg","-y","-i",src,"-map_metadata","-1","-fflags","+bitexact","-flags:v","+bitexact","-flags:a","+bitexact","-c","copy",dst], capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst): return dst
    except: pass
    return src

def _detect_shopee_endcard(src: str, duration: float) -> float:
    """Detecta quando o endcard vermelho da Shopee começa. Retorna duração real do conteúdo."""
    # Endcard aparece nos últimos 2-5 segundos geralmente
    check_points = []
    for offset in [5, 4, 3, 2, 1]:
        t = duration - offset
        if t > 1:
            check_points.append(t)

    real_duration = duration
    for t in check_points:
        try:
            # Extrair frame naquele ponto e analisar se é vermelho
            tmp_frame = src.rsplit(".",1)[0] + f"_f{int(t)}.png"
            r = subprocess.run([
                "ffmpeg","-y","-ss",str(t),"-i",src,
                "-vf","crop=100:100:iw/2-50:ih/2-50",
                "-frames:v","1",tmp_frame
            ], capture_output=True, timeout=10)

            if r.returncode == 0 and os.path.exists(tmp_frame):
                # Checar média de cor com ffmpeg signalstats
                stats = subprocess.run([
                    "ffmpeg","-i",tmp_frame,"-vf","signalstats",
                    "-f","null","-"
                ], capture_output=True, timeout=10)
                stderr = stats.stderr.decode()
                # Extrair médias RGB do output
                import re
                m_r = re.search(r'YAVG:([\d.]+)', stderr)
                m_u = re.search(r'UAVG:([\d.]+)', stderr)
                m_v = re.search(r'VAVG:([\d.]+)', stderr)

                os.remove(tmp_frame)

                if m_v:
                    v_avg = float(m_v.group(1))
                    # V (chroma red) alto = vermelho
                    if v_avg > 170:  # threshold para vermelho Shopee
                        real_duration = t
                        log.info(f"Endcard vermelho detectado em t={t:.1f}s (V={v_avg:.0f})")
                    else:
                        break  # não é vermelho, conteúdo real
        except Exception as e:
            log.debug(f"Detect endcard t={t}: {e}")

    return real_duration


def _detect_red_endcard(src: str, total_duration: float) -> float:
    """Detecta onde começa o card vermelho final da Shopee.
    Retorna a duração do vídeo útil (sem o endcard)."""
    try:
        # Shopee sempre adiciona 3-5 segundos de endcard vermelho no final
        # Amostra 3 frames no final (85%, 90%, 95%) para detectar cor predominante
        check_points = [
            max(0, total_duration - 5),
            max(0, total_duration - 3),
            max(0, total_duration - 1),
        ]

        red_start = None
        for t in check_points:
            r = subprocess.run([
                "ffmpeg", "-y", "-ss", str(t), "-i", src,
                "-vframes", "1", "-vf", "scale=50:50",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"
            ], capture_output=True, timeout=15)

            if r.returncode == 0 and r.stdout:
                pixels = r.stdout
                # Calcular cor média dos pixels
                total_r, total_g, total_b = 0, 0, 0
                count = len(pixels) // 3
                for i in range(0, len(pixels), 3):
                    total_r += pixels[i]
                    total_g += pixels[i+1]
                    total_b += pixels[i+2]
                avg_r = total_r // count
                avg_g = total_g // count
                avg_b = total_b // count

                # Shopee red: R alto (200+), G/B baixos (<120)
                is_shopee_red = avg_r > 180 and avg_g < 130 and avg_b < 120

                if is_shopee_red:
                    if red_start is None or t < red_start:
                        red_start = t
                    log.info(f"Endcard vermelho detectado em t={t:.1f}s (RGB {avg_r},{avg_g},{avg_b})")

        if red_start is not None:
            # Cortar 0.5s antes pra garantir
            return max(1.0, red_start - 0.5)
    except Exception as e:
        log.warning(f"Detect endcard erro: {e}")

    return total_duration


def remove_watermark(src: str, platform: str) -> str:
    """Remove marca d'água Shopee + corta endcard vermelho final.
    Coordenadas testadas e validadas com vídeos reais."""
    if platform != "shopee":
        return src

    dst = src.rsplit(".",1)[0] + "_nowm.mp4"
    try:
        # 1. Dimensões + duração
        probe = subprocess.run([
            "ffprobe","-v","quiet","-select_streams","v:0",
            "-show_entries","stream=width,height:format=duration",
            "-of","json",src
        ], capture_output=True, timeout=15)
        info = json.loads(probe.stdout.decode())
        stream = info.get("streams",[{}])[0]
        w = int(stream.get("width", 0))
        h = int(stream.get("height", 0))
        duration = float(info.get("format",{}).get("duration", 0))

        if w < 100 or h < 100 or duration < 2:
            return src

        # 2. Detectar endcard vermelho
        useful_duration = _detect_red_endcard(src, duration)

        # 3. Coordenadas validadas (testadas com vídeo real 480x854)
        # Logo ShopeeVideo: ocupa ~35% largura, altura 6% — posição y=43%
        # Username @xxx: ocupa ~27% largura, altura 5% — posição y=50%
        # IMPORTANTE: delogo exige x >= 1 e y >= 1 (NÃO aceita 0)

        # Região 1: Logo "ShopeeVideo" (linha superior)
        r1_x = max(1, int(w * 0.01))
        r1_y = int(h * 0.43)
        r1_w = int(w * 0.36)
        r1_h = int(h * 0.065)

        # Região 2: Username (@xxxxxx) (linha inferior)
        r2_x = max(1, int(w * 0.01))
        r2_y = int(h * 0.505)
        r2_w = int(w * 0.28)
        r2_h = int(h * 0.055)

        # Garantir que estão dentro do frame
        for (x, y, rw, rh) in [(r1_x, r1_y, r1_w, r1_h), (r2_x, r2_y, r2_w, r2_h)]:
            if x + rw >= w or y + rh >= h or rw < 10 or rh < 10:
                log.warning(f"Coordenadas inválidas, pulando delogo")
                return src

        log.info(f"Shopee: {w}x{h} {duration:.1f}s → watermark removal; útil={useful_duration:.1f}s")

        # 4. Filtro combinado: 2 delogos em cascata
        vf = (
            f"delogo=x={r1_x}:y={r1_y}:w={r1_w}:h={r1_h},"
            f"delogo=x={r2_x}:y={r2_y}:w={r2_w}:h={r2_h}"
        )

        # 5. Comando ffmpeg — corta o endcard se detectado
        cmd = ["ffmpeg","-y","-i",src]
        if useful_duration < duration - 0.5:
            cmd += ["-t", f"{useful_duration:.2f}"]
        cmd += [
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-map_metadata", "-1",
            "-movflags", "+faststart",
            dst
        ]

        r = subprocess.run(cmd, capture_output=True, timeout=300)

        if r.returncode == 0 and os.path.exists(dst):
            new_sz = os.path.getsize(dst)
            if new_sz > 50000:
                log.info(f"✅ Watermark removida + endcard cortado: {os.path.getsize(src)//1024}KB → {new_sz//1024}KB")
                return dst

        err = r.stderr.decode()[:300]
        log.warning(f"❌ delogo falhou: {err}")
    except Exception as e:
        log.warning(f"Watermark removal erro: {e}")

    return src


def compress(src, target=45):
    sz = os.path.getsize(src)/(1024*1024)
    if sz <= target: return src
    dst = src.rsplit(".",1)[0] + "_comp.mp4"
    try:
        p = subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0",src], capture_output=True, timeout=30)
        dur = float(p.stdout.decode().strip() or "60")
        vbr = max(int((target*8*1024*1024/dur)*0.85), 500000)
        subprocess.run(["ffmpeg","-y","-i",src,"-c:v","libx264","-b:v",str(vbr),"-preset","fast","-crf","28","-c:a","aac","-b:a","128k","-movflags","+faststart","-map_metadata","-1",dst], capture_output=True, timeout=300)
        if os.path.exists(dst): return dst
    except: pass
    return src

def cleanup(*p):
    for f in p:
        try:
            if f and os.path.exists(f): os.remove(f)
        except: pass

# ════════════════════════════════════════════════════
# HANDLERS
# ════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_s()
    await update.message.reply_text(
        f"🚀 *Viral Engine*\n\n"
        f"Cole o link do vídeo\\.\n"
        f"Eu baixo sem marca d'água e gero legenda \\+ hashtags\\.\n\n"
        f"🛒 Shopee · 🎵 TikTok · ▶️ YouTube · 🐦 X\n"
        f"📌 Pinterest · 📘 Facebook · 🎬 Kwai · 📸 Instagram\n\n"
        f"_{s.get('d',0)} downloads_\n\n"
        f"👇 Manda o link",
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
            # REMOVER MARCA D'ÁGUA (Shopee)
            if plat == "shopee":
                try: await status.edit_text("🧹 Removendo marca d'água...")
                except: pass
            nowm = remove_watermark(fp, plat)
            src = nowm if nowm != fp else fp

            cleaned = strip_meta(src)
            final = cleaned if cleaned != src else src
            sz = os.path.getsize(final)/(1024*1024)
            if sz > 49:
                try: await status.edit_text(f"🗜 Comprimindo ({sz:.0f}MB)...")
                except: pass
                final = compress(final)
            sz = os.path.getsize(final)/(1024*1024)
            if sz <= 49:
                try: await status.delete()
                except: pass
                try:
                    with open(final,"rb") as f:
                        await update.message.reply_video(video=f, caption="✅ Sem marca d'água · HD", read_timeout=300, write_timeout=300)
                    track(uid)
                except:
                    try: await status.edit_text("⚠️ Erro ao enviar. Tente novamente.")
                    except: pass
            else:
                try: await status.edit_text(f"⚠️ Vídeo muito grande ({sz:.0f}MB).")
                except: pass
            cleanup(fp)
            if nowm and nowm != fp: cleanup(nowm)
            if cleaned and cleaned != fp and cleaned != nowm: cleanup(cleaned)
            if final != fp and final != nowm and final != cleaned: cleanup(final)
        else:
            try: await status.edit_text("⚠️ Não consegui baixar. Verifique se o vídeo é público.")
            except: pass

        # Legenda + hashtags por plataforma
        data = generate(link)
        ctx.user_data.update({"shopee":data["shopee"],"tiktok":data["tiktok"],"insta":data["insta"],"src":link})

        await update.message.reply_text(data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
                [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
                [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ]))
    else:
        await update.message.reply_chat_action(ChatAction.TYPING)
        data = generate(link or text)
        ctx.user_data.update({"shopee":data["shopee"],"tiktok":data["tiktok"],"insta":data["insta"],"src":link or text})

        await update.message.reply_text(data["full"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
                [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
                [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
                [InlineKeyboardButton("🔄 Nova legenda", callback_data="regen")],
            ]))
        track(uid)

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "cp_shopee":
        t = ctx.user_data.get("shopee","")
        if t: await q.message.reply_text(t)
    elif q.data == "cp_tiktok":
        t = ctx.user_data.get("tiktok","")
        if t: await q.message.reply_text(t)
    elif q.data == "cp_insta":
        t = ctx.user_data.get("insta","")
        if t: await q.message.reply_text(t)
    elif q.data == "regen":
        src = ctx.user_data.get("src","")
        if src:
            data = generate(src)
            ctx.user_data.update({"shopee":data["shopee"],"tiktok":data["tiktok"],"insta":data["insta"]})
            await q.message.reply_text(data["full"],
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 Copiar p/ Shopee", callback_data="cp_shopee")],
                    [InlineKeyboardButton("🎵 Copiar p/ TikTok", callback_data="cp_tiktok")],
                    [InlineKeyboardButton("📸 Copiar p/ Instagram", callback_data="cp_insta")],
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
