"""
bot.py — Viral Engine Telegram Bot

Cola um link → baixa o vídeo sem marca d'água → gera legendas e hashtags.
Suporta: TikTok, Instagram, YouTube, Kwai, Pinterest, Shopee Video,
         Facebook, Twitter/X, Threads, Mercado Livre.

Uso: TELEGRAM_BOT_TOKEN=xxx python bot.py
"""

import os, re, logging, asyncio, subprocess, tempfile, time, json
from pathlib import Path
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction

from engine import generate, detect_platform, is_link, PLAT_NAMES, PLAT_EMOJI

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
log = logging.getLogger("bot")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TMPDIR = Path(tempfile.gettempdir()) / "viralbot"
TMPDIR.mkdir(exist_ok=True)
STATS_FILE = TMPDIR / "stats.json"
MAX_TG_SIZE = 49 * 1024 * 1024  # 49MB

# Plataformas que suportam download de vídeo
VIDEO_PLATFORMS = {"tiktok","instagram","youtube","kwai","pinterest","facebook","twitter","threads"}


# ═══════════════════════════════════════════════════════════
# STATS — contagem de downloads e usuários
# ═══════════════════════════════════════════════════════════
def load_stats() -> dict:
    try:
        return json.loads(STATS_FILE.read_text()) if STATS_FILE.exists() else {"downloads": 0, "users": []}
    except:
        return {"downloads": 0, "users": []}

def save_stats(stats: dict):
    try:
        STATS_FILE.write_text(json.dumps(stats))
    except:
        pass

def track(user_id: int):
    s = load_stats()
    s["downloads"] = s.get("downloads", 0) + 1
    if user_id not in s.get("users", []):
        s.setdefault("users", []).append(user_id)
    save_stats(s)


# ═══════════════════════════════════════════════════════════
# DOWNLOAD + LIMPEZA
# ═══════════════════════════════════════════════════════════
async def download_video(url: str, platform: str | None = None) -> str | None:
    """Baixa vídeo com yt-dlp. Retorna path ou None."""
    uid = f"{int(time.time())}_{os.getpid()}"
    out = str(TMPDIR / f"{uid}.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-warnings", "--no-playlist", "--no-check-certificates",
        "--max-filesize", "49m",
        "--socket-timeout", "30",
        "--retries", "3",
        "-f", "best[ext=mp4][filesize<49M]/best[ext=mp4]/best[filesize<49M]/best",
        "--merge-output-format", "mp4",
        "-o", out,
        "--print", "after_move:filepath",
    ]

    # Flags específicas por plataforma
    if platform == "tiktok":
        cmd += ["--add-header", "Referer:https://www.tiktok.com/"]
    elif platform == "instagram":
        cmd += ["--add-header", "Referer:https://www.instagram.com/"]

    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)

        if proc.returncode == 0:
            filepath = stdout.decode().strip().split("\n")[-1].strip()
            if filepath and os.path.exists(filepath):
                log.info(f"Download OK: {filepath} ({os.path.getsize(filepath)} bytes)")
                return filepath

        log.warning(f"yt-dlp falhou ({proc.returncode}): {stderr.decode()[:300]}")
        return None
    except asyncio.TimeoutError:
        log.error("Download timeout (180s)")
        return None
    except Exception as e:
        log.error(f"Download erro: {e}")
        return None


def strip_metadata(src: str) -> str:
    """Remove metadados com ffmpeg. Retorna path do arquivo limpo."""
    dst = src.rsplit(".", 1)[0] + "_clean.mp4"
    try:
        r = subprocess.run([
            "ffmpeg", "-y", "-i", src,
            "-map_metadata", "-1",
            "-fflags", "+bitexact",
            "-flags:v", "+bitexact",
            "-flags:a", "+bitexact",
            "-c", "copy",
            dst
        ], capture_output=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst):
            return dst
    except Exception as e:
        log.warning(f"ffmpeg falhou: {e}")
    return src  # retorna original se falhar


async def extract_audio(src: str) -> str | None:
    """Extrai áudio MP3 do vídeo."""
    dst = src.rsplit(".", 1)[0] + ".mp3"
    try:
        r = subprocess.run([
            "ffmpeg", "-y", "-i", src,
            "-vn", "-acodec", "libmp3lame", "-q:a", "2",
            "-map_metadata", "-1",
            dst
        ], capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.exists(dst):
            return dst
    except:
        pass
    return None


def cleanup(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except:
            pass


# ═══════════════════════════════════════════════════════════
# TELEGRAM FORMATTING
# ═══════════════════════════════════════════════════════════
def esc(text: str) -> str:
    """Escapa MarkdownV2."""
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\\-])', r'\\\1', str(text))


def build_content_msg(data: dict) -> list[str]:
    """Monta as mensagens de conteúdo viral. Retorna lista de strings."""
    msgs = []

    # ── MSG 1: Legendas ──
    lines = [f"📝 *LEGENDAS VIRAIS*"]
    if data["platform_name"]:
        lines.append(f"{esc(data['platform_emoji'])} Plataforma: {esc(data['platform_name'])}")
    lines.append(f"📁 Categoria: {esc(data['cat_label'])}")
    lines.append("─" * 25)

    for titulo, legenda in data["legendas"].items():
        lines.append(f"\n*{esc(titulo)}*")
        lines.append(esc(legenda))

    msgs.append("\n".join(lines))

    # ── MSG 2: Hashtags ──
    lines = ["🏷 *HASHTAGS*\n"]
    for grupo, tags in data["hashtags"].items():
        lines.append(f"*{esc(grupo)}*")
        lines.append(esc(" ".join(tags)))
        lines.append("")

    lines.append("📋 *COPIAR TUDO:*")
    lines.append(esc(data["all_tags"]))
    msgs.append("\n".join(lines))

    # ── MSG 3: Hooks ──
    lines = ["⚡ *HOOKS*\n"]
    for i, h in enumerate(data["hooks"]):
        lines.append(f"*{i+1}\\.* {esc(h)}")
    msgs.append("\n".join(lines))

    return msgs


def build_quick_copy(data: dict) -> str:
    """Texto pronto pra colar: legenda + hashtags."""
    legenda = list(data["legendas"].values())[0]
    return f"{legenda}\n\n{data['all_tags']}"


# ═══════════════════════════════════════════════════════════
# HANDLERS
# ═══════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = load_stats()
    n_users = len(stats.get("users", []))
    n_down = stats.get("downloads", 0)

    await update.message.reply_text(
        f"🚀 *Viral Engine Bot*\n\n"
        f"Baixe vídeos sem marca d'água \\+ legendas e hashtags virais\\.\n\n"
        f"*Como usar:*\n\n"
        f"1️⃣ Envie um *link de vídeo*\n"
        f"   TikTok \\| Reels \\| YouTube \\| Kwai \\| Pinterest \\| X\n"
        f"   → Baixo o vídeo limpo \\+ gero conteúdo viral\n\n"
        f"2️⃣ Envie um *link de produto* \\(Shopee\\)\n"
        f"   → Gero legendas, hashtags e hooks\n\n"
        f"3️⃣ Envie o *nome de qualquer produto*\n"
        f"   → Gero conteúdo viral completo\n\n"
        f"📊 {esc(str(n_down))} downloads \\| {esc(str(n_users))} usuários\n\n"
        f"Manda o primeiro link\\! 👇",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Comandos*\n\n"
        "/start \\— Iniciar\n"
        "/help \\— Ajuda\n"
        "/plataformas \\— Plataformas suportadas\n"
        "/stats \\— Estatísticas\n\n"
        "Ou envie qualquer *link* ou *nome de produto*\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def cmd_plataformas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["🌐 *Plataformas Suportadas*\n"]
    for k, name in PLAT_NAMES.items():
        emoji = PLAT_EMOJI.get(k, "🔗")
        dl = "✅ Download" if k in VIDEO_PLATFORMS else "📝 Conteúdo"
        lines.append(f"{emoji} *{esc(name)}* — {dl}")
    lines.append(f"\n_Download via yt\\-dlp \\+ limpeza de metadados via ffmpeg_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = load_stats()
    await update.message.reply_text(
        f"📊 *Estatísticas*\n\n"
        f"⬇️ Downloads: *{esc(str(s.get('downloads',0)))}*\n"
        f"👥 Usuários: *{esc(str(len(s.get('users',[]))))}*",
        parse_mode=ParseMode.MARKDOWN_V2
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handler principal — detecta link, baixa, gera conteúdo."""
    text = (update.message.text or "").strip()
    if not text or len(text) < 2:
        return

    user_id = update.effective_user.id

    # Extrair link se houver
    link_match = re.search(r'https?://\S+', text)
    link = link_match.group(0) if link_match else None
    platform = detect_platform(link) if link else None
    can_download = platform in VIDEO_PLATFORMS

    # ═══════════════════════════════════════════════════════
    # FLUXO: Link de vídeo → Download + Conteúdo
    # ═══════════════════════════════════════════════════════
    if link and can_download:
        plat_name = PLAT_NAMES.get(platform, "plataforma")
        plat_emoji = PLAT_EMOJI.get(platform, "🔗")

        status = await update.message.reply_text(
            f"{plat_emoji} *{esc(plat_name)}* detectado\\.\n\n"
            f"⏳ Baixando vídeo sem marca d'água\\.\\.\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        await update.message.reply_chat_action(ChatAction.UPLOAD_VIDEO)

        # Download
        filepath = await download_video(link, platform)
        raw_path = filepath
        clean_path = None
        audio_path = None

        if filepath:
            # Limpar metadados
            await status.edit_text(
                f"🧹 Removendo metadados e marca d'água\\.\\.\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            clean_path = strip_metadata(filepath)
            final = clean_path if clean_path != filepath else filepath

            # Checar tamanho
            size = os.path.getsize(final)
            if size > MAX_TG_SIZE:
                await status.edit_text(
                    "⚠️ Vídeo muito grande \\(\\>50MB\\)\\.\n"
                    "Gerando conteúdo viral\\.\\.\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                # Enviar vídeo
                await status.edit_text(
                    f"📤 Enviando vídeo limpo\\.\\.\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                try:
                    with open(final, "rb") as f:
                        await update.message.reply_video(
                            video=f,
                            caption=f"✅ Vídeo baixado — sem marca d'água, sem metadados\n{plat_emoji} {plat_name}",
                            read_timeout=120, write_timeout=120,
                        )
                    track(user_id)
                except Exception as e:
                    log.error(f"Erro envio: {e}")
                    await update.message.reply_text("⚠️ Erro ao enviar vídeo. Tente novamente.")

            # Extrair áudio
            audio_path = await extract_audio(filepath)
        else:
            await status.edit_text(
                f"⚠️ Não consegui baixar este vídeo\\.\n\n"
                f"Possíveis motivos:\n"
                f"• Vídeo privado ou restrito\n"
                f"• Plataforma bloqueou o acesso\n"
                f"• Link expirado\n\n"
                f"Gerando conteúdo viral mesmo assim\\.\\.\\. 👇",
                parse_mode=ParseMode.MARKDOWN_V2
            )

        # Gerar e enviar conteúdo viral
        data = generate(link)
        msgs = build_content_msg(data)
        for msg in msgs:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
            await asyncio.sleep(0.3)

        # Botões
        quick = build_quick_copy(data)
        ctx.user_data["quick"] = quick
        ctx.user_data["last"] = text

        buttons = [[InlineKeyboardButton("📋 Copiar Legenda + Hashtags", callback_data="copy")]]
        if audio_path and os.path.exists(audio_path):
            ctx.user_data["audio"] = audio_path
            buttons.append([InlineKeyboardButton("🎵 Baixar Áudio MP3", callback_data="audio")])
        buttons.append([InlineKeyboardButton("🔄 Gerar Novamente", callback_data="regen")])

        await update.message.reply_text(
            "✅ *Pronto\\!*",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.MARKDOWN_V2
        )

        # Limpar (exceto áudio temporário)
        if clean_path and clean_path != raw_path:
            cleanup(raw_path)
        # clean_path será limpo depois do callback de áudio ou após timeout

    # ═══════════════════════════════════════════════════════
    # FLUXO: Link de produto ou texto → Só conteúdo
    # ═══════════════════════════════════════════════════════
    else:
        await update.message.reply_chat_action(ChatAction.TYPING)

        data = generate(link or text)
        msgs = build_content_msg(data)
        for msg in msgs:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
            await asyncio.sleep(0.3)

        quick = build_quick_copy(data)
        ctx.user_data["quick"] = quick
        ctx.user_data["last"] = text

        await update.message.reply_text(
            "✅ *Pronto\\!*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copiar Legenda + Hashtags", callback_data="copy")],
                [InlineKeyboardButton("🔄 Gerar Novamente", callback_data="regen")],
            ]),
            parse_mode=ParseMode.MARKDOWN_V2
        )
        track(user_id)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "copy":
        quick = ctx.user_data.get("quick", "")
        if quick:
            await q.message.reply_text(quick)

    elif q.data == "audio":
        audio = ctx.user_data.get("audio")
        if audio and os.path.exists(audio):
            try:
                with open(audio, "rb") as f:
                    await q.message.reply_audio(audio=f, caption="🎵 Áudio extraído (MP3)")
            except Exception as e:
                await q.message.reply_text(f"⚠️ Erro ao enviar áudio: {e}")
            finally:
                cleanup(audio)
                ctx.user_data.pop("audio", None)
        else:
            await q.message.reply_text("⚠️ Áudio não disponível.")

    elif q.data == "regen":
        last = ctx.user_data.get("last", "")
        if last:
            data = generate(last)
            quick = build_quick_copy(data)
            await q.message.reply_text(quick)


async def post_init(app):
    """Configura comandos visíveis no menu do bot."""
    await app.bot.set_my_commands([
        BotCommand("start", "Iniciar o bot"),
        BotCommand("help", "Ver ajuda"),
        BotCommand("plataformas", "Plataformas suportadas"),
        BotCommand("stats", "Ver estatísticas"),
    ])


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    if not TOKEN:
        print("=" * 50)
        print("❌ Token não configurado!")
        print("")
        print("Configure a variável de ambiente:")
        print("  Linux/Mac: export TELEGRAM_BOT_TOKEN='seu_token'")
        print("  Windows:   set TELEGRAM_BOT_TOKEN=seu_token")
        print("")
        print("Obtenha o token com @BotFather no Telegram.")
        print("=" * 50)
        return

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("plataformas", cmd_plataformas))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("🚀 Viral Engine Bot rodando!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
