"""
shopee_extractor.py — Extração REAL da Shopee Video via Playwright.

Estratégia:
1. Abre a URL no Chromium headless stealth
2. Intercepta TODAS as respostas de rede
3. Filtra requests que contêm vídeo MP4 do CDN Shopee (susercontent.com)
4. Captura:
   - URL do vídeo original SEM marca d'água (do default_format)
   - Título/descrição do vídeo
   - Nome do produto vinculado (para hashtags)
5. Baixa o vídeo direto do CDN com as headers corretas

Por que isso funciona: o player web da Shopee sempre faz uma request
para o CDN de vídeo, e essa request é visível na camada de rede.
"""

import asyncio
import logging
import re
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
import requests as req

log = logging.getLogger("shopee_extractor")

TMP = Path(tempfile.gettempdir()) / "vbot"
TMP.mkdir(exist_ok=True)

# User-Agent realista
UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")


def _is_shopee_video_url(url: str) -> bool:
    """Identifica se uma URL é de vídeo MP4 da Shopee (CDN oficial)."""
    if not url or ".mp4" not in url.lower():
        return False
    # CDNs oficiais da Shopee para vídeo
    shopee_cdns = [
        "susercontent.com",      # CDN principal
        "shopeemobile.com",      # CDN mobile
        "shopee.com",            # direto
        "sv-mms",                # Shopee Video MMS
        "cf-video",              # CloudFlare video
    ]
    ul = url.lower()
    if not any(c in ul for c in shopee_cdns):
        return False
    # Descartar thumbnails
    if any(x in ul for x in ["thumb", "cover", "preview", "poster", "_tn"]):
        return False
    return True


async def extract_shopee_video(share_url: str, timeout: int = 45) -> Dict[str, Any]:
    """
    Extrai vídeo + metadados de um link Shopee Video.

    Retorna dict com:
        - video_url: URL direta do MP4 sem marca d'água (ou None)
        - title: título do vídeo
        - caption: legenda original
        - username: @criador
        - product_name: nome do produto vinculado (para hashtags)
        - product_link: link da loja do produto (se houver)
        - all_requests: lista de URLs interceptadas (debug)
    """
    from playwright.async_api import async_playwright

    result = {
        "video_url": None,
        "title": None,
        "caption": None,
        "username": None,
        "product_name": None,
        "product_link": None,
        "duration": None,
        "all_requests": [],
        "error": None,
    }

    video_candidates = []  # lista de (url, size, headers)
    api_responses = []     # respostas JSON capturadas

    log.info(f"PW: iniciando extração para {share_url[:100]}")

    browser = None
    try:
        async with async_playwright() as p:
            # Args otimizados para baixo consumo de RAM (Render Starter 512MB)
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--disable-translate",
                    "--no-first-run",
                    "--single-process",  # economiza ~200MB (Render Starter)
                    "--renderer-process-limit=1",
                ]
            )

            context = await browser.new_context(
                user_agent=UA_DESKTOP,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 390, "height": 844},  # mobile viewport
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
            )

            # Esconder sinais de automação
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en'] });
            """)

            page = await context.new_page()

            # ==== INTERCEPTADORES ====

            def on_response(response):
                """Captura todas as respostas."""
                try:
                    url = response.url
                    result["all_requests"].append(url[:200])

                    # Vídeo MP4 do CDN
                    if _is_shopee_video_url(url):
                        content_length = 0
                        try:
                            content_length = int(response.headers.get("content-length", "0"))
                        except: pass
                        video_candidates.append({
                            "url": url,
                            "size": content_length,
                            "status": response.status,
                        })
                        log.info(f"PW: 🎯 vídeo MP4 detectado: {url[:100]} ({content_length//1024}KB)")

                    # Respostas JSON da API Shopee (metadados)
                    elif ("shopee.com" in url or "susercontent.com" in url):
                        ct = response.headers.get("content-type", "")
                        if "json" in ct.lower():
                            api_responses.append(response)

                except Exception as e:
                    log.debug(f"on_response: {e}")

            page.on("response", on_response)

            # Bloquear recursos pesados (imagens, fontes) para acelerar
            async def block_heavy(route):
                rt = route.request.resource_type
                if rt in ("image", "font", "stylesheet"):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", block_heavy)

            # ==== NAVEGAÇÃO ====

            try:
                log.info(f"PW: navegando para {share_url}")
                await page.goto(share_url, wait_until="domcontentloaded", timeout=timeout * 1000)
            except Exception as e:
                log.warning(f"PW goto: {e}")

            # Aguardar o vídeo aparecer ou timeout
            deadline = time.time() + 20
            while time.time() < deadline:
                if video_candidates:
                    # Deu match, aguarda mais 2s pra pegar versão em melhor qualidade
                    await asyncio.sleep(2)
                    break
                await asyncio.sleep(0.5)

            # Tentar extrair metadados do DOM
            try:
                # Título/caption do vídeo
                meta = await page.evaluate("""() => {
                    const og = (prop) => {
                        const el = document.querySelector(`meta[property="${prop}"]`) ||
                                   document.querySelector(`meta[name="${prop}"]`);
                        return el ? el.content : null;
                    };
                    return {
                        title: og('og:title') || document.title,
                        description: og('og:description'),
                        video_url: og('og:video:url') || og('og:video'),
                        image: og('og:image'),
                    };
                }""")
                if meta:
                    result["title"] = meta.get("title")
                    result["caption"] = meta.get("description")
                    if meta.get("video_url") and not result["video_url"]:
                        result["video_url"] = meta["video_url"]
                    log.info(f"PW: meta title={meta.get('title','?')[:80]}")
            except Exception as e:
                log.warning(f"PW meta extract: {e}")

            # Extrair username, nome do produto etc do DOM
            try:
                info = await page.evaluate("""() => {
                    const text = document.body.innerText || '';
                    // Username geralmente aparece com @
                    const userMatch = text.match(/@([a-zA-Z0-9._]{3,30})/);
                    return {
                        body_text: text.slice(0, 2000),
                        username: userMatch ? userMatch[1] : null,
                    };
                }""")
                if info:
                    result["username"] = info.get("username")
            except Exception as e:
                log.warning(f"PW info extract: {e}")

            # Tentar ler resposta JSON da API (onde estão os metadados estruturados)
            for resp in api_responses[:20]:
                try:
                    url = resp.url
                    if any(k in url for k in ["video", "feed", "item", "detail"]):
                        data = await resp.json()
                        # Busca recursiva por campos úteis
                        _dig_metadata(data, result)
                except: pass

            await browser.close()
            browser = None

    except Exception as e:
        log.error(f"PW erro geral: {e}")
        result["error"] = str(e)
        return result
    finally:
        # Garantir que o browser SEMPRE feche (crítico pra RAM no Render)
        if browser:
            try: await browser.close()
            except: pass

    # Escolher o melhor candidato de vídeo (maior tamanho = melhor qualidade)
    if video_candidates:
        video_candidates.sort(key=lambda x: x["size"], reverse=True)
        best = video_candidates[0]
        result["video_url"] = best["url"]
        log.info(f"PW: ✅ melhor vídeo: {best['url'][:100]} ({best['size']//1024}KB)")

    log.info(f"PW: capturados {len(result['all_requests'])} requests, "
             f"{len(video_candidates)} vídeos")

    return result


def _dig_metadata(obj: Any, result: Dict, depth: int = 0):
    """Busca recursiva por metadados em JSON."""
    if depth > 8 or not obj:
        return
    if isinstance(obj, dict):
        # Campos úteis
        if not result.get("title"):
            for k in ("title", "video_title", "name", "caption"):
                v = obj.get(k)
                if isinstance(v, str) and len(v) > 3:
                    result["title"] = v
                    break
        if not result.get("caption"):
            for k in ("description", "desc", "text", "content"):
                v = obj.get(k)
                if isinstance(v, str) and len(v) > 5:
                    result["caption"] = v
                    break
        if not result.get("product_name"):
            p = obj.get("product") or obj.get("item") or obj.get("product_info")
            if isinstance(p, dict):
                n = p.get("name") or p.get("title")
                if n: result["product_name"] = n
            for k in ("product_name", "item_name"):
                v = obj.get(k)
                if isinstance(v, str) and len(v) > 3:
                    result["product_name"] = v
                    break
        if not result.get("duration"):
            for k in ("duration", "video_duration"):
                v = obj.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    result["duration"] = v

        for v in obj.values():
            _dig_metadata(v, result, depth + 1)

    elif isinstance(obj, list):
        for item in obj[:50]:
            _dig_metadata(item, result, depth + 1)


async def download_shopee_video(share_url: str) -> Optional[Dict[str, Any]]:
    """
    Baixa vídeo Shopee SEM marca d'água.
    Retorna dict com 'filepath', 'metadata' ou None se falhou.
    """
    log.info(f"━━━ SHOPEE PLAYWRIGHT: {share_url}")

    # 1. Extrair URL do vídeo via Playwright
    extracted = await extract_shopee_video(share_url)

    if not extracted.get("video_url"):
        log.warning(f"━━━ SHOPEE: Playwright não capturou vídeo. "
                    f"Primeiros requests: {extracted['all_requests'][:10]}")
        return None

    video_url = extracted["video_url"]

    # 2. Baixar o MP4 com headers da Shopee
    try:
        log.info(f"━━━ Baixando: {video_url[:120]}")
        headers = {
            "User-Agent": UA_DESKTOP,
            "Referer": "https://sv.shopee.com.br/",
            "Accept": "*/*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        r = req.get(video_url, headers=headers, timeout=180, allow_redirects=True, stream=True)
        log.info(f"━━━ Download status={r.status_code}, "
                 f"content-length={r.headers.get('content-length','?')}, "
                 f"content-type={r.headers.get('content-type','?')}")

        if r.status_code != 200:
            log.warning(f"━━━ Status não-200: {r.status_code}")
            return None

        # Salvar em arquivo
        fp = str(TMP / f"shopee_{int(time.time())}.mp4")
        total = 0
        with open(fp, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        if total < 50000:
            log.warning(f"━━━ Arquivo muito pequeno: {total} bytes")
            return None

        log.info(f"━━━ ✅ Download OK: {total//1024}KB")

        return {
            "filepath": fp,
            "metadata": {
                "title": extracted.get("title"),
                "caption": extracted.get("caption"),
                "username": extracted.get("username"),
                "product_name": extracted.get("product_name"),
                "duration": extracted.get("duration"),
            }
        }

    except Exception as e:
        log.error(f"━━━ Download erro: {e}")
        return None
