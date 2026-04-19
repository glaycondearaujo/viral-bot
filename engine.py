"""
engine.py — Motor viral inteligente.
Usa o TÍTULO REAL do vídeo + nome do produto para gerar hashtags precisas.
Zero hashtags de plataforma.
"""

import random
import re
from urllib.parse import urlparse, unquote


# ══════════════════════════════════════════════════════════════
# HASHTAGS POR CATEGORIA — 100% focadas no produto
# ══════════════════════════════════════════════════════════════

TAGS_CAT = {
    "fone_audio": [
        "#fone", "#fonebluetooth", "#fonedeouvido", "#audio", "#som",
        "#musica", "#grave", "#bass", "#tecnologia", "#gadgets",
        "#caixadesom", "#podcast", "#acessorios", "#wireless",
    ],
    "smartwatch": [
        "#smartwatch", "#relogio", "#relogiodigital", "#smartband",
        "#fitness", "#saude", "#tecnologia", "#wearable", "#gadgets",
        "#estilo", "#acessorios", "#esporte",
    ],
    "eletronicos": [
        "#tecnologia", "#gadgets", "#tech", "#eletronicos", "#acessorios",
        "#inovacao", "#setup", "#workspace", "#produtividade",
        "#conectividade", "#wireless", "#qualidadepremium",
    ],
    "lingerie": [
        "#lingerie", "#modaintima", "#autoestima", "#empoderamento",
        "#sensualidade", "#feminina", "#delicada", "#renda", "#tule",
        "#conjunto", "#intimo", "#charme", "#confianca",
    ],
    "moda_feminina": [
        "#modafeminina", "#roupafeminina", "#estilofeminino", "#look",
        "#outfit", "#tendencia", "#elegante", "#delicado", "#feminina",
        "#lookdodia", "#inspiracao",
    ],
    "moda": [
        "#moda", "#estilo", "#look", "#outfit", "#lookdodia",
        "#tendencia", "#style", "#streetwear", "#inspiracao",
    ],
    "perfume": [
        "#perfume", "#perfumaria", "#fragrance", "#fragrancia",
        "#cheirogostoso", "#aroma", "#autoestima", "#body", "#colonia",
    ],
    "maquiagem": [
        "#maquiagem", "#makeup", "#batom", "#base", "#sombra",
        "#delineador", "#rimel", "#blush", "#beautyhacks",
        "#maquiagembrasileira", "#mua",
    ],
    "skincare": [
        "#skincare", "#beleza", "#rotinadebeleza", "#cuidados",
        "#peleperfeita", "#glowup", "#autoestima", "#belezanatural",
        "#acido", "#hidratacao", "#protetorsolar",
    ],
    "cabelo": [
        "#cabelo", "#hair", "#hairstyle", "#cabeloperfeito",
        "#cachos", "#hidratacao", "#crescimentocapilar",
        "#cuidadoscomocabelo",
    ],
    "casa": [
        "#casa", "#decoracao", "#organizacao", "#home", "#homedecor",
        "#casaorganizada", "#decor", "#interiordesign", "#utilidades",
        "#praticidade", "#diy", "#transformacao",
    ],
    "cozinha": [
        "#cozinha", "#utensilioscozinha", "#kitchen", "#cozinhapratica",
        "#receitas", "#chef", "#cozinhafuncional", "#organizacao",
    ],
    "esporte": [
        "#fitness", "#treino", "#academia", "#saude", "#vidasaudavel",
        "#gym", "#workout", "#motivacao", "#esporte", "#bemestar",
        "#foco", "#disciplina",
    ],
    "bebe": [
        "#bebe", "#maternidade", "#mae", "#mamae", "#enxoval",
        "#maedemenino", "#maedemenina", "#dicasdemae", "#mundomaterno",
    ],
    "pet": [
        "#pet", "#cachorro", "#gato", "#petlover", "#animais",
        "#amorpeludos", "#petmom", "#petdad",
    ],
    "bolsa_mochila": [
        "#bolsa", "#mochila", "#bolsafeminina", "#acessorios",
        "#estilo", "#pratica", "#espacosa", "#organizada",
    ],
    "bolsa_termica": [
        "#bolsatermica", "#marmita", "#fitness", "#vidasaudavel",
        "#dieta", "#marmitafit", "#trabalho", "#viagem", "#pratica",
        "#funcional", "#organizacao", "#rotina",
    ],
    "geral": [
        "#dica", "#recomendacao", "#indicacao", "#testei", "#aprovado",
        "#resenha", "#produtosbons", "#achadosdodia", "#compreiamei",
        "#valepena", "#custobeneficio", "#qualidade",
    ],
}

# Hashtags de alcance — genéricas, sem associação com plataforma
TAGS_ALCANCE = [
    "#viral", "#viralvideo", "#trending", "#tendencia",
    "#achados", "#achadinhos", "#achadosdodia",
    "#recomendado", "#indicacao", "#valepena",
]


# ══════════════════════════════════════════════════════════════
# DETECÇÃO DE CATEGORIA — a partir do TÍTULO REAL do produto
# ══════════════════════════════════════════════════════════════

CAT_RULES = [
    # Ordem: específicos primeiro
    ("fone_audio",      r"fone|bluetooth|caixa\s*de?\s*som|headset|earbuds|headphone|airdopes|jbl|airpods"),
    ("smartwatch",      r"smart\s*watch|smartband|rel[oó]gio\s*digital|rel[oó]gio\s*smart|mi\s*band|xiaomi\s*watch|galaxy\s*watch"),
    ("lingerie",        r"camisola|lingerie|calcinha|sutia|suti[aã]|conjunto\s*[ií]ntimo|baby\s*doll|tule|renda\b"),
    ("perfume",         r"perfume|fragrance|body\s*splash|col[oô]nia|eau\s*de\s*(parfum|toilette)"),
    ("maquiagem",       r"maquiagem|batom|base\b|r[ií]mel|sombra|delineador|blush|iluminador|corretivo|pincel|paleta|labial"),
    ("skincare",        r"skincare|hidratante|protetor\s*solar|s[eé]rum|[aá]cido|retinol|niacinamida|vitamina\s*c|esfoliante"),
    ("cabelo",          r"shampoo|condicionador|escova|chapinha|secador|hidratante\s*capilar|m[aá]scara\s*capilar|creme\s*cabelo|prancha"),
    ("bolsa_termica",   r"bolsa\s*t[eé]rmica|marmita|mochila\s*t[eé]rmica|termo|garrafa\s*t[eé]rmica"),
    ("bolsa_mochila",   r"bolsa\b|mochila|necessaire|pochete|fanny\s*pack|bag\b"),
    ("cozinha",         r"panela|frigideira|utens[ií]lio|talher|prato|copo|x[ií]cara|t[aá]bua|esp[aá]tula|organizador\s*cozinha|airfryer"),
    ("casa",            r"decora[cç][aã]o|tapete|cortina|lumin[aá]ria|banheiro|lixeira|almofada|coberta|edredom|travesseiro|prateleira"),
    ("esporte",         r"fitness|treino|academia|gym|corrida|bicicleta|yoga|haltere|el[aá]stico|squeeze|whey|creatina|caneleira"),
    ("bebe",            r"beb[eê]|infantil|crian[cç]a|fralda|mamadeira|chupeta|ber[cç]o|carrinho|enxoval|macac[aã]o"),
    ("pet",             r"cachorro|gato|petisco|ra[cç][aã]o|coleira|comedouro|bebedouro"),
    ("moda_feminina",   r"vestido|saia\b|shorts\s*feminino|cropped|blusa\s*feminina|conjunto\s*feminino"),
    ("moda",            r"roupa|camiseta|camisa|jaqueta|casaco|moletom|t[eê]nis|bota|sand[aá]lia|chinelo|bon[eé]|[oó]culos|bermuda"),
    ("eletronicos",     r"carregador|cabo\s*usb|cabo\s*tipo\s*c|led|camera|drone|mouse|teclado|powerbank|notebook|tablet|celular|capinha|controle|microfone"),
]


PLAT_RE = {
    "tiktok":    r"tiktok\.com|vm\.tiktok|vt\.tiktok",
    "instagram": r"instagram\.com|instagr\.am",
    "youtube":   r"youtube\.com|youtu\.be",
    "kwai":      r"kwai\.com|kw\.ai",
    "pinterest": r"pinterest\.com|pin\.it",
    "shopee":    r"shopee\.com|shp\.ee|s\.shopee",
    "facebook":  r"facebook\.com|fb\.watch",
    "twitter":   r"twitter\.com|x\.com|t\.co",
    "threads":   r"threads\.net",
}

VIDEO_OK = {"tiktok", "youtube", "twitter", "pinterest", "facebook",
            "kwai", "instagram", "threads", "shopee"}


def detect_platform(url):
    if not url: return None
    for k, p in PLAT_RE.items():
        if re.search(p, url, re.I): return k
    return None


def can_download(plat): return plat in VIDEO_OK


def detect_category(text: str) -> str:
    """Detecta categoria do produto baseado no texto (título ou descrição)."""
    if not text: return "geral"
    t = text.lower()
    for cat, pat in CAT_RULES:
        if re.search(pat, t, re.I):
            return cat
    return "geral"


def extract_product_name(text: str) -> str:
    """Tenta extrair um nome legível do produto, priorizando texto real sobre URL."""
    if not text:
        return "esse produto"
    text = text.strip()

    # Se tem texto legível (não é URL), usar diretamente
    if not re.match(r'https?://', text, re.I):
        # Limpar emojis e pontuação excessiva
        clean = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
        clean = re.sub(r'\s+', ' ', clean).strip()
        # Pegar primeiras palavras úteis (3-6 palavras)
        words = clean.split()[:6]
        if words:
            return " ".join(words)
        return "esse produto"

    # Extrair de URL
    try:
        path = unquote(urlparse(text).pathname)
        stop = {'com', 'br', 'www', 'shopee', 'product', 'item', 'video',
                'html', 'php', 'i', 'p', 'reel', 'watch', 'shorts', 'pin',
                'share', 'universal', 'link', 'redir'}
        words = []
        for w in re.split(r'[-_/.]', path):
            w = w.strip()
            if (len(w) > 2 and not w.isdigit() and
                w.lower() not in stop and
                not re.match(r'^[a-f0-9]{8,}$', w, re.I)):
                words.append(w)
        if words:
            return " ".join(words[:5])
    except: pass
    return "esse produto"


# ══════════════════════════════════════════════════════════════
# LEGENDAS VIRAIS — 12 fórmulas
# ══════════════════════════════════════════════════════════════

CAT_LABEL = {
    "fone_audio": "fone", "smartwatch": "relógio", "lingerie": "peça",
    "perfume": "perfume", "maquiagem": "produto de make", "skincare": "produto de skincare",
    "cabelo": "produto de cabelo", "cozinha": "utensílio", "casa": "item",
    "esporte": "acessório fitness", "bebe": "item de bebê", "pet": "produto pet",
    "bolsa_mochila": "bolsa", "bolsa_termica": "bolsa térmica",
    "moda_feminina": "peça", "moda": "peça", "eletronicos": "gadget",
    "geral": "produto",
}


def _gen_caption(nome: str, cat: str) -> str:
    label = CAT_LABEL.get(cat, "produto")

    formulas = [
        f"⚠️ ÚLTIMAS UNIDADES\n\n{nome} com desconto absurdo.\nQuando acaba, acaba.\n\n🔗 Link na bio — corre!",
        f"Ninguém me contou sobre esse {nome}...\n\nDescobri sozinha e precisava dividir 👀\nAssiste até o final.\n\nQuer o link? Comenta 💬",
        f"+10.000 avaliações e nota 4.9 ⭐\n\nEsse {nome} não tá viralizando à toa.\nQualidade real pelo melhor preço.\n\n🔗 Link nos comentários",
        f"ANTES: sem {nome}\nDEPOIS: vida transformada 🔥\n\nSério, como eu vivia sem isso?\n\nSalva pra não esquecer 🔖",
        f"Esse {nome} DESTRUIU todos os concorrentes.\n\nTestei 5 opções. Esse ganhou de lavada.\n\nLink na bio 🔗",
        f"Tava procurando {label} bom há meses...\n\nGastei dinheiro à toa em outros.\nAté que achei {nome}.\n\nMelhor decisão 🔗",
        f"Te DESAFIO a achar melhor que {nome}.\n\nQualidade premium, preço justo.\n\nQuem achou melhor? Comenta 👇",
        f"O {label} que ninguém mostra 👀\n\n{nome}\nSem publi, sem parceria. Comprei e amei.\n\nComenta \"QUERO\" 💬",
        f"Se você procura {label} bom e barato...\n\nPara de sofrer. Achei {nome}.\nQualidade que surpreende.\n\n🔗 Link na bio",
        f"Você VAI se arrepender de não comprar isso.\n\n{nome} — menor preço que já vi.\nNão sei até quando fica assim.\n\n🔗 Link nos comentários",
        f"Já testei MUITO {label}.\n\n{nome} é o melhor custo-benefício.\nPonto final.\n\n🔗 Link na bio",
        f"Achado do dia 🔥\n\n{nome}\n✅ Qualidade real\n✅ Preço justo\n✅ Entrega rápida\n\nSalva e agradece depois 🔖",
    ]
    return random.choice(formulas)


def _gen_hashtags(cat: str, extra_words: list = None) -> str:
    """Gera hashtags da categoria + palavras extras relevantes do título."""
    cat_tags = TAGS_CAT.get(cat, TAGS_CAT["geral"])
    cat_selected = random.sample(cat_tags, min(10, len(cat_tags)))

    general = TAGS_CAT["geral"]
    general_sel = random.sample(general, 3) if cat != "geral" else []

    alcance = random.sample(TAGS_ALCANCE, 5)

    # Hashtags extras do título (palavras reais do produto)
    extra_tags = []
    if extra_words:
        for word in extra_words:
            w = re.sub(r'[^a-z0-9]', '', word.lower())
            if 3 <= len(w) <= 20 and w not in {
                "com", "para", "que", "esse", "essa", "este", "esta",
                "produto", "link", "bio", "comenta", "shopee", "tiktok",
                "instagram", "video", "novo", "nova"
            }:
                tag = f"#{w}"
                if tag not in extra_tags:
                    extra_tags.append(tag)
        extra_tags = extra_tags[:4]

    all_tags = extra_tags + cat_selected + general_sel + alcance
    seen = set()
    unique = []
    for t in all_tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return " ".join(unique)


# ══════════════════════════════════════════════════════════════
# GERADOR PRINCIPAL
# ══════════════════════════════════════════════════════════════

def generate(text: str, metadata: dict = None) -> dict:
    """
    Gera legenda + hashtags.

    Args:
        text: URL ou texto livre
        metadata: dict opcional com 'title', 'caption', 'product_name',
                  'username' (extraídos do Playwright pra Shopee)
    """
    # Priorizar metadata real do vídeo sobre URL
    source_text = ""
    extra_words = []

    if metadata:
        for key in ("product_name", "title", "caption"):
            v = metadata.get(key)
            if v and len(str(v)) > 3:
                source_text = str(v)
                # Extrair palavras significativas para hashtags extras
                words = re.findall(r'\b[a-záéíóúãõâêôç]{3,20}\b',
                                   source_text.lower())
                extra_words = words[:8]
                break

    if not source_text:
        source_text = extract_product_name(text or "")

    cat = detect_category(source_text)
    nome = source_text if len(source_text) < 80 else source_text[:80]

    caption = _gen_caption(nome, cat)

    # 3 variações de hashtags
    h1 = _gen_hashtags(cat, extra_words)
    h2 = _gen_hashtags(cat, extra_words)
    h3 = _gen_hashtags(cat, extra_words)

    return {
        "caption": caption,
        "v1": f"{caption}\n\n{h1}",
        "v2": f"{caption}\n\n{h2}",
        "v3": f"{caption}\n\n{h3}",
        "full": f"{caption}\n\n{h1}",
        "category": cat,
        "product_name": nome,
    }
