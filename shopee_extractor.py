"""
shopee_extractor.py — Extração honesta com 3 estratégias em cascata:

1. API MOBILE com cookies autenticados + headers do app Android
2. Playwright autenticado interceptando requests de vídeo
3. Fallback: Playwright público (última opção)

+ Detecção de marca d'água por análise de pixels
+ Detecção de endcard vermelho + corte automático
"""

import asyncio
import logging
import re
import time
import json
import tempfile
import subprocess
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs, unquote
import requests as req

log = logging.getLogger("shopee_extractor")

TMP = Path(tempfile.gettempdir()) / "vbot"
TMP.mkdir(exist_ok=True)

UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")

UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/131.0.0.0 Mobile Safari/537.36")

# User-Agent que simula o app Shopee Android
UA_SHOPEE_APP = "Android app Shopeee appver=31600 platform=native"


# ══════════════════════════════════════════════════════════════
# GERENCIAMENTO DE COOKIES
# ══════════════════════════════════════════════════════════════

def load_cookies_netscape(path: str) -> List[Dict]:
    """Lê arquivo de cookies no formato Netscape (exportado do navegador)."""
    cookies = []
    if not os.path.exists(path):
        log.warning(f"Arquivo de cookies não existe: {path}")
        return cookies

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            domain, flag, path_c, secure, expires, name, value = parts[:7]
            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path_c,
                "secure": secure == "TRUE",
                "httpOnly": False,
                "sameSite": "Lax",
            }
            try:
                exp = int(expires)
                if exp > 0:
                    cookie["expires"] = float(exp)
            except: pass
            cookies.append(cookie)
    log.info(f"Cookies carregados: {len(cookies)}")
    return cookies


def cookies_to_dict(cookies: List[Dict]) -> Dict[str, str]:
    """Converte lista de cookies para dict simples (nome->valor)."""
    return {c["name"]: c["value"] for c in cookies}


def cookies_to_header(cookies: List[Dict]) -> str:
    """Converte cookies para string de header HTTP."""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


# ══════════════════════════════════════════════════════════════
# EXTRAÇÃO DE VIDEO ID
# ══════════════════════════════════════════════════════════════

def extract_vid(url: str) -> Optional[str]:
    """Extrai o video ID (base64 ou numérico) da URL Shopee."""
    ID_PAT = r'([A-Za-z0-9+/=_\-]{8,})'
    patterns = [
        rf'share-video/{ID_PAT}(?:[?&#]|$)',
        rf'/video/{ID_PAT}(?:[?&#]|$)',
        rf'videoId={ID_PAT}',
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m and len(m.group(1)) >= 8:
            return m.group(1)

    # Procurar dentro de redir=
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "redir" in qs:
            redir = unquote(qs["redir"][0])
            for pat in patterns:
                m = re.search(pat, redir)
                if m and len(m.group(1)) >= 8:
                    return m.group(1)
    except: pass

    return None


def resolve_short_link(url: str, cookies_dict: Dict[str, str] = None) -> str:
    """Resolve link curto shp.ee → universal-link → share-video."""
    try:
        r = req.get(url, headers={
            "User-Agent": UA_MOBILE,
            "Accept-Language": "pt-BR"
        }, cookies=cookies_dict or {}, allow_redirects=True, timeout=20)
        return r.url
    except Exception as e:
        log.warning(f"Resolve erro: {e}")
        return url


def get_real_share_url(resolved_url: str) -> str:
    """Desembrulha o universal-link?redir=... para pegar a URL real do share-video."""
    try:
        parsed = urlparse(resolved_url)
        qs = parse_qs(parsed.query)
        if "redir" in qs:
            return unquote(qs["redir"][0])
    except: pass
    return resolved_url


# ══════════════════════════════════════════════════════════════
# ESTRATÉGIA 1: API MOBILE AUTENTICADA
# ══════════════════════════════════════════════════════════════

async def strategy_mobile_api(vid: str, cookies: List[Dict]) -> Optional[Dict]:
    """
    Tenta múltiplos endpoints mobile da Shopee com cookies autenticados.
    Essa é a melhor chance de pegar vídeo sem marca d'água.
    """
    log.info(f"STRAT1[mobile-api]: vid={vid}")

    cookies_dict = cookies_to_dict(cookies)
    cookie_header = cookies_to_header(cookies)

    # Headers simulando app mobile + autenticação
    headers_variants = [
        {
            "User-Agent": UA_MOBILE,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": f"https://sv.shopee.com.br/share-video/{vid}",
            "Origin": "https://sv.shopee.com.br",
            "X-Shopee-Language": "pt-BR",
            "X-API-SOURCE": "pc",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": cookies_dict.get("csrftoken", ""),
            "Cookie": cookie_header,
        },
        {
            "User-Agent": UA_SHOPEE_APP,
            "Accept": "application/json",
            "X-Shopee-Language": "pt-BR",
            "Referer": "https://shopee.com.br/",
            "Cookie": cookie_header,
        },
    ]

    # Lista de endpoints a tentar
    endpoints = [
        f"https://sv.shopee.com.br/api/v1/share/video/{vid}",
        f"https://sv.shopee.com.br/api/v1/video/detail?video_id={vid}",
        f"https://sv.shopee.com.br/api/v1/video/{vid}",
        f"https://shopee.com.br/api/v4/sv/video_detail?video_id={vid}",
        f"https://shopee.com.br/api/v4/shop_video/get_video_info?video_id={vid}",
        f"https://sv-mms-live-br.shopee.com.br/api/v1/video/{vid}",
    ]

    for headers in headers_variants:
        for ep in endpoints:
            try:
                log.info(f"STRAT1[try]: {ep[:70]}")
                r = req.get(ep, headers=headers, cookies=cookies_dict, timeout=15)
                log.info(f"STRAT1[resp]: {r.status_code} ({len(r.text) if r.text else 0}b)")

                if r.status_code == 200 and r.text:
                    try:
                        data = r.json()
                        vurl, meta = _extract_from_api_response(data)
                        if vurl:
                            log.info(f"STRAT1[✅]: vídeo encontrado via {ep[:60]}")
                            return {"video_url": vurl, "meta": meta, "source": ep}
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                log.debug(f"STRAT1[err] {ep[:50]}: {e}")

    return None


def _extract_from_api_response(data: Any) -> tuple:
    """Busca URL de vídeo e metadados em resposta JSON da API."""
    meta = {"title": None, "product_name": None, "username": None, "caption": None}

    def dig(obj, depth=0):
        if depth > 10:
            return None
        if isinstance(obj, str):
            if obj.startswith("http") and (".mp4" in obj.lower() or "/mms/" in obj):
                low = obj.lower()
                if not any(x in low for x in ["thumb", "cover", "preview", ".jpg", ".png"]):
                    return obj
            return None
        if isinstance(obj, dict):
            # Capturar metadados
            for k in ("title", "video_title", "name"):
                v = obj.get(k)
                if isinstance(v, str) and len(v) > 3 and not meta["title"]:
                    meta["title"] = v
            for k in ("description", "caption", "desc"):
                v = obj.get(k)
                if isinstance(v, str) and len(v) > 3 and not meta["caption"]:
                    meta["caption"] = v
            for k in ("product_name", "item_name"):
                v = obj.get(k)
                if isinstance(v, str) and not meta["product_name"]:
                    meta["product_name"] = v

            # Prioridade por chaves conhecidas
            priority = ["default_format", "video_url", "play_url", "playUrl",
                        "playAddr", "url", "download_url", "hd_url", "video",
                        "mms_url", "cdn_url", "src"]
            for k in priority:
                if k in obj:
                    found = dig(obj[k], depth + 1)
                    if found: return found
            for v in obj.values():
                found = dig(v, depth + 1)
                if found: return found
        if isinstance(obj, list):
            for item in obj:
                found = dig(item, depth + 1)
                if found: return found
        return None

    return dig(data), meta


# ══════════════════════════════════════════════════════════════
# ESTRATÉGIA 2: PLAYWRIGHT AUTENTICADO + INTERCEPTAÇÃO
# ══════════════════════════════════════════════════════════════

async def strategy_playwright(share_url: str, cookies: List[Dict],
                              timeout: int = 40) -> Optional[Dict]:
    """
    Abre Playwright com cookies autenticados e intercepta requests de vídeo.
    """
    from playwright.async_api import async_playwright

    log.info(f"STRAT2[playwright]: {share_url[:80]}")

    result = {
        "video_url": None,
        "meta": {"title": None, "caption": None, "username": None, "product_name": None},
        "source": "playwright",
    }
    video_candidates = []
    browser = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--single-process",
                ]
            )

            context = await browser.new_context(
                user_agent=UA_MOBILE,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
            )

            # Injetar cookies autenticados
            try:
                await context.add_cookies(cookies)
                log.info(f"STRAT2: {len(cookies)} cookies injetados")
            except Exception as e:
                log.warning(f"STRAT2 cookies: {e}")

            # Esconder sinais de automação
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en'] });
                window.chrome = { runtime: {} };
            """)

            page = await context.new_page()

            # Interceptador de respostas
            def on_response(response):
                try:
                    url = response.url
                    if ".mp4" in url.lower():
                        low = url.lower()
                        if any(x in low for x in ["thumb", "cover", "preview", ".jpg", ".png"]):
                            return
                        if any(c in low for c in ["susercontent.com", "shopee", "mms"]):
                            try:
                                cl = int(response.headers.get("content-length", "0"))
                            except: cl = 0
                            video_candidates.append({
                                "url": url, "size": cl, "status": response.status
                            })
                            log.info(f"STRAT2[🎯]: {url[:100]} ({cl//1024}KB)")
                except: pass

            page.on("response", on_response)

            # Bloquear recursos pesados para acelerar
            async def block_heavy(route):
                rt = route.request.resource_type
                if rt in ("image", "font", "stylesheet"):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", block_heavy)

            # Navegar
            try:
                await page.goto(share_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except Exception as e:
                log.warning(f"STRAT2 goto: {e}")

            # Esperar por vídeo interceptado (até 15s)
            deadline = time.time() + 15
            while time.time() < deadline:
                if video_candidates:
                    await asyncio.sleep(2)
                    break
                await asyncio.sleep(0.5)

            # Extrair metadata do DOM
            try:
                meta = await page.evaluate("""() => {
                    const og = (prop) => {
                        const el = document.querySelector(`meta[property="${prop}"]`) ||
                                   document.querySelector(`meta[name="${prop}"]`);
                        return el ? el.content : null;
                    };
                    const body = (document.body ? document.body.innerText : '').slice(0, 3000);
                    const userMatch = body.match(/@([a-zA-Z0-9._]{3,30})/);
                    return {
                        title: og('og:title') || document.title,
                        description: og('og:description'),
                        username: userMatch ? userMatch[1] : null,
                        body_preview: body.slice(0, 500),
                    };
                }""")
                if meta:
                    result["meta"]["title"] = meta.get("title")
                    result["meta"]["caption"] = meta.get("description")
                    result["meta"]["username"] = meta.get("username")
            except Exception as e:
                log.warning(f"STRAT2 meta: {e}")

            await browser.close()
            browser = None

    except Exception as e:
        log.error(f"STRAT2 erro: {e}")
        return None
    finally:
        if browser:
            try: await browser.close()
            except: pass

    # Escolher melhor candidato
    if video_candidates:
        video_candidates.sort(key=lambda x: x["size"], reverse=True)
        result["video_url"] = video_candidates[0]["url"]
        return result

    log.warning("STRAT2: nenhum vídeo interceptado")
    return None


# ══════════════════════════════════════════════════════════════
# DOWNLOAD + DETECÇÃO DE MARCA D'ÁGUA + CORTE DE ENDCARD
# ══════════════════════════════════════════════════════════════

def download_url(url: str, referer: str = "https://sv.shopee.com.br/",
                 cookies_dict: Dict = None) -> Optional[str]:
    """Baixa o vídeo da URL direta."""
    try:
        headers = {
            "User-Agent": UA_MOBILE,
            "Referer": referer,
            "Accept": "*/*",
            "Accept-Language": "pt-BR",
        }
        log.info(f"DL: {url[:100]}")
        r = req.get(url, headers=headers, cookies=cookies_dict or {},
                    timeout=180, allow_redirects=True, stream=True)

        if r.status_code != 200:
            log.warning(f"DL: status {r.status_code}")
            return None

        fp = str(TMP / f"shopee_{int(time.time())}_{os.getpid()}.mp4")
        total = 0
        with open(fp, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        if total < 50000:
            log.warning(f"DL: muito pequeno ({total}b)")
            os.remove(fp)
            return None

        log.info(f"DL OK: {total//1024}KB → {fp}")
        return fp
    except Exception as e:
        log.error(f"DL erro: {e}")
        return None


def detect_watermark(video_path: str) -> bool:
    """
    Detecta se o vídeo tem marca d'água ShopeeVideo usando análise de pixels.
    A marca aparece no meio-esquerdo da tela em ~39% da altura.
    Retorna True se detectar marca d'água.
    """
    try:
        # Extrair frame intermediário (t=2s)
        frame_path = video_path.rsplit(".", 1)[0] + "_check.png"
        r = subprocess.run([
            "ffmpeg", "-y", "-ss", "2", "-i", video_path,
            "-vf", "crop=iw*0.5:ih*0.1:iw*0.01:ih*0.39",
            "-frames:v", "1", frame_path
        ], capture_output=True, timeout=20)

        if r.returncode != 0 or not os.path.exists(frame_path):
            return False

        # Analisar dimensões
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0", frame_path
        ], capture_output=True, timeout=10)

        if probe.returncode != 0:
            os.remove(frame_path)
            return False

        # Detectar presença de pixels muito claros (branco do logo ShopeeVideo)
        stats = subprocess.run([
            "ffmpeg", "-i", frame_path, "-vf", "signalstats",
            "-f", "null", "-"
        ], capture_output=True, timeout=10)
        stderr = stats.stderr.decode()

        os.remove(frame_path)

        # Se YMAX >= 250 e YAVG está numa faixa específica → provavelmente tem texto branco
        m_ymax = re.search(r"YMAX:(\d+)", stderr)
        m_yavg = re.search(r"YAVG:([\d.]+)", stderr)
        if m_ymax and m_yavg:
            ymax = int(m_ymax.group(1))
            yavg = float(m_yavg.group(1))
            # Marca d'água tem pixels muito claros (>240) mesclados com escuros
            # Sem marca d'água, o crop seria mais uniforme
            has_bright = ymax >= 240
            log.info(f"WATERMARK[detect]: YMAX={ymax} YAVG={yavg} has_bright={has_bright}")
            return has_bright
    except Exception as e:
        log.warning(f"Detect watermark erro: {e}")

    return False


def detect_and_trim_endcard(video_path: str) -> str:
    """
    Detecta se há endcard vermelho da Shopee no final e corta.
    Retorna o caminho do vídeo (novo ou original).
    """
    try:
        # Pegar duração
        p = subprocess.run([
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "csv=p=0", video_path
        ], capture_output=True, timeout=15)
        duration = float(p.stdout.decode().strip() or "0")
        if duration < 3:
            return video_path

        # Verificar últimos 5 segundos em steps de 1s
        endcard_start = duration
        for offset in range(5, 0, -1):
            t = duration - offset
            if t < 1: continue

            # Extrair frame e verificar se é vermelho
            fp = video_path.rsplit(".", 1)[0] + f"_t{int(t)}.png"
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(t), "-i", video_path,
                "-vf", "crop=100:100:iw/2-50:ih/2-50",
                "-frames:v", "1", fp
            ], capture_output=True, timeout=10)

            if os.path.exists(fp):
                stats = subprocess.run([
                    "ffmpeg", "-i", fp, "-vf", "signalstats",
                    "-f", "null", "-"
                ], capture_output=True, timeout=10)
                os.remove(fp)
                m_v = re.search(r"VAVG:([\d.]+)", stats.stderr.decode())
                if m_v and float(m_v.group(1)) > 170:  # muito vermelho
                    endcard_start = t
                    log.info(f"ENDCARD: detectado em t={t:.1f}s")
                else:
                    break  # conteúdo real → para busca

        if endcard_start < duration - 0.5:
            # Cortar
            dst = video_path.rsplit(".", 1)[0] + "_trimmed.mp4"
            r = subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-t", str(endcard_start),
                "-c", "copy", "-movflags", "+faststart", dst
            ], capture_output=True, timeout=60)
            if r.returncode == 0 and os.path.exists(dst):
                log.info(f"ENDCARD: cortado {duration:.1f}s → {endcard_start:.1f}s")
                return dst
    except Exception as e:
        log.warning(f"Endcard trim erro: {e}")

    return video_path


# ══════════════════════════════════════════════════════════════
# ORQUESTRADOR PRINCIPAL
# ══════════════════════════════════════════════════════════════

async def download_shopee(share_url: str, cookies_path: str = None) -> Dict:
    """
    Orquestra as 3 estratégias em cascata.

    Retorna:
        {
            "filepath": str ou None,
            "metadata": dict,
            "watermark_detected": bool,
            "endcard_trimmed": bool,
            "strategy_used": str,  # qual estratégia funcionou
            "debug": list de strings
        }
    """
    debug = []
    result = {
        "filepath": None,
        "metadata": {},
        "watermark_detected": False,
        "endcard_trimmed": False,
        "strategy_used": None,
        "debug": debug,
    }

    # Carregar cookies
    cookies = []
    if cookies_path and os.path.exists(cookies_path):
        cookies = load_cookies_netscape(cookies_path)
        debug.append(f"Cookies carregados: {len(cookies)}")
    else:
        debug.append("⚠️ Sem cookies — usando modo anônimo (qualidade pior)")

    cookies_dict = cookies_to_dict(cookies)

    # 1. Resolver link curto e extrair vid
    resolved = resolve_short_link(share_url, cookies_dict)
    real_share = get_real_share_url(resolved)
    vid = extract_vid(real_share) or extract_vid(resolved) or extract_vid(share_url)
    debug.append(f"resolved: {resolved[:80]}")
    debug.append(f"real_share: {real_share[:80]}")
    debug.append(f"vid: {vid}")

    if not vid:
        debug.append("❌ Não foi possível extrair vid")
        return result

    # ESTRATÉGIA 1: API mobile autenticada
    if cookies:
        api_result = await strategy_mobile_api(vid, cookies)
        if api_result and api_result.get("video_url"):
            debug.append(f"✅ STRAT1 OK: {api_result.get('source', '?')[:60]}")
            fp = download_url(api_result["video_url"],
                              referer=real_share, cookies_dict=cookies_dict)
            if fp:
                result["filepath"] = fp
                result["metadata"] = api_result.get("meta", {})
                result["strategy_used"] = "mobile_api"
                debug.append(f"   download OK: {os.path.getsize(fp)//1024}KB")
    else:
        debug.append("⏭️ STRAT1 pulada (sem cookies)")

    # ESTRATÉGIA 2: Playwright com cookies autenticados
    if not result["filepath"]:
        pw_result = await strategy_playwright(real_share, cookies)
        if pw_result and pw_result.get("video_url"):
            debug.append(f"✅ STRAT2 OK: vídeo interceptado")
            fp = download_url(pw_result["video_url"],
                              referer=real_share, cookies_dict=cookies_dict)
            if fp:
                result["filepath"] = fp
                result["metadata"] = pw_result.get("meta", {})
                result["strategy_used"] = "playwright_auth" if cookies else "playwright"
                debug.append(f"   download OK: {os.path.getsize(fp)//1024}KB")

    if not result["filepath"]:
        debug.append("❌ Todas as estratégias falharam")
        return result

    # PÓS-PROCESSAMENTO
    fp = result["filepath"]

    # Detectar e cortar endcard vermelho
    trimmed = detect_and_trim_endcard(fp)
    if trimmed != fp:
        try: os.remove(fp)
        except: pass
        result["filepath"] = trimmed
        result["endcard_trimmed"] = True
        debug.append("✂️ Endcard vermelho cortado")

    # Detectar marca d'água
    has_wm = detect_watermark(result["filepath"])
    result["watermark_detected"] = has_wm
    if has_wm:
        debug.append("⚠️ Marca d'água detectada no vídeo baixado")
    else:
        debug.append("✅ Sem marca d'água detectada")

    return result
