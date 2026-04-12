"""
viral_engine.py — Motor de conteúdo viral para afiliados Shopee.
Gera legendas, hashtags e hooks a partir do nome/categoria do produto.
"""

import random, re
from urllib.parse import urlparse, unquote

# ══════════════════════════════════════════════════════════════
# HASHTAGS — banco curado por categoria
# ══════════════════════════════════════════════════════════════
H = {
    "eletronicos": {
        "v": ["#achados","#achadosshopee","#shopee","#shopeebrasil","#comprinhas","#comprinhasshopee","#recebidos","#viral","#fyp","#foryou","#paravoce","#tiktokbrasil","#trending","#desconto","#oferta"],
        "n": ["#tech","#tecnologia","#gadgets","#eletronicos","#fonebluetooth","#caixadesom","#smartwatch","#acessoriostech","#geek","#setup","#unboxing","#review","#techtok"],
        "p": ["#resenha","#testando","#valepena","#baratinho","#qualidade","#custobeneficio","#achado","#compreinotiktok"],
        "t": ["#tiktokshop","#achadosdatiktok","#produtosvirais","#tiktokmefezcomprar","#coisaslegais","#shopeevideo"]
    },
    "moda": {
        "v": ["#moda","#fashion","#outfit","#ootd","#look","#lookdodia","#estilo","#tendencia","#shopee","#shopeebrasil","#achadosshopee","#viral","#fyp","#tiktokbrasil","#comprinhas"],
        "n": ["#modafeminina","#modamasculina","#streetwear","#modaacessivel","#roupabarata","#lookbaratinho","#fashiontiktok","#closet","#guardaroupa","#inspiracao"],
        "p": ["#haul","#provador","#experimentando","#favoritos","#wishlist","#combinacoes","#dica","#tendencia2026"],
        "t": ["#getreadywithme","#grwm","#transicao","#antesedepois","#styleinspo","#outfitideas","#fashionhacks"]
    },
    "beleza": {
        "v": ["#beleza","#beauty","#skincare","#maquiagem","#makeup","#cuidados","#rotina","#shopee","#shopeebrasil","#achadosshopee","#viral","#fyp","#tiktokbrasil","#beautyfinds"],
        "n": ["#peleperfeita","#cuidadoscomapele","#hidratante","#protetor","#rotinadebeleza","#skincarerotina","#makes","#tutorial","#resenha","#dica"],
        "p": ["#testando","#antesedepois","#resultados","#funciona","#aprovado","#recomendo","#favoritos","#empties"],
        "t": ["#beautytok","#beautyhacks","#glowup","#selfcare","#cleanbeauty","#kbeauty","#glassskin"]
    },
    "casa": {
        "v": ["#casa","#decoracao","#decor","#organizacao","#limpeza","#shopee","#shopeebrasil","#achadosshopee","#viral","#fyp","#tiktokbrasil","#comprinhas","#lar","#home"],
        "n": ["#casaorganizada","#cozinha","#banheiro","#quarto","#diy","#homeoffice","#apartamento","#primeiroape","#casanova","#decoracaobarata"],
        "p": ["#achados","#utilidades","#pratico","#truques","#dicas","#hacks","#transformacao","#antesedepois"],
        "t": ["#hometok","#cleantok","#asmrcleaning","#organizetok","#satisfying","#restockingasmr","#rotinadalimpeza"]
    },
    "geral": {
        "v": ["#shopee","#shopeebrasil","#achadosshopee","#comprinhas","#recebidos","#viral","#fyp","#foryou","#paravoce","#tiktokbrasil","#trending","#ofertas","#desconto","#promocao"],
        "n": ["#dicas","#recomendacao","#resenha","#favoritos","#testei","#valepena","#barato","#achado","#indicacao","#review"],
        "p": ["#unboxing","#abrindopacote","#chegou","#novidades","#haul","#compreinotiktok","#tiktokmefezcomprar"],
        "t": ["#tiktokshop","#achadosdatiktok","#produtosvirais","#coisaslegais","#produtosincriveis","#produtosbons"]
    }
}

# ══════════════════════════════════════════════════════════════
# DETECÇÃO
# ══════════════════════════════════════════════════════════════
CAT_RE = {
    "eletronicos": r"fone|bluetooth|caixa.?de.?som|smart.?watch|relogio|carregador|cabo|usb|led|luz|lampada|camera|drone|mouse|teclado|headset|earbuds|powerbank|celular|tablet|notebook|gamer|rgb|monitor|microfone|ring.?light|tripé|pelicula|capinha|case|controle|pendrive|hd|ssd|roteador|wifi",
    "moda": r"roupa|vestido|calca|calça|blusa|camiseta|camisa|jaqueta|casaco|saia|shorts|conjunto|moletom|cropped|body|lingerie|cueca|meia|pijama|tenis|tênis|bota|sandalia|chinelo|bone|boné|oculos|óculos|bolsa|mochila|carteira|cinto",
    "beleza": r"maquiagem|batom|base|corretivo|rimel|sombra|skincare|hidratante|protetor|serum|perfume|creme|shampoo|condicionador|escova|chapinha|secador|unha|esmalte|pincel|esponja|mascara|cilios",
    "casa": r"cozinha|organizador|prateleira|decoracao|tapete|cortina|luminaria|banheiro|lixeira|suporte|gancho|dispenser|toalha|panela|frigideira|copo|prato|talher|almofada|coberta|edredom|travesseiro",
}

PLAT_RE = {
    "tiktok":     r"tiktok\.com|vm\.tiktok|vt\.tiktok",
    "instagram":  r"instagram\.com|instagr\.am",
    "youtube":    r"youtube\.com|youtu\.be|youtube\.shorts",
    "kwai":       r"kwai\.com|kwai-video|kw\.ai",
    "pinterest":  r"pinterest\.com|pin\.it",
    "shopee":     r"shopee\.com|shp\.ee|s\.shopee",
    "facebook":   r"facebook\.com|fb\.watch|fb\.com",
    "twitter":    r"twitter\.com|x\.com|t\.co",
    "threads":    r"threads\.net",
    "mercadolivre": r"mercadolivre\.com|produto\.mercadolivre",
}

PLAT_NAMES = {
    "tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube",
    "kwai": "Kwai", "pinterest": "Pinterest", "shopee": "Shopee",
    "facebook": "Facebook", "twitter": "X/Twitter", "threads": "Threads",
    "mercadolivre": "Mercado Livre",
}

PLAT_EMOJI = {
    "tiktok": "🎵", "instagram": "📸", "youtube": "▶️",
    "kwai": "🎬", "pinterest": "📌", "shopee": "🛒",
    "facebook": "📘", "twitter": "🐦", "threads": "🧵",
    "mercadolivre": "🤝",
}


def detect_platform(url: str) -> str | None:
    for key, pattern in PLAT_RE.items():
        if re.search(pattern, url, re.I):
            return key
    return None


def detect_category(text: str) -> tuple[str, str]:
    t = text.lower()
    for key, pattern in CAT_RE.items():
        if re.search(pattern, t, re.I):
            labels = {"eletronicos":"eletrônico","moda":"moda","beleza":"beleza","casa":"casa"}
            return key, labels.get(key, key)
    return "geral", "produto"


def extract_name(text: str) -> str:
    text = text.strip()
    if re.match(r'https?://', text, re.I):
        try:
            path = unquote(urlparse(text).pathname)
            parts = re.split(r'[-_/.]', path)
            words = [p for p in parts if len(p) > 2 and not re.match(r'^(com|br|www|shopee|product|item|video|html|php|i|p|reel|watch|shorts|pin|\d+)$', p, re.I)]
            return " ".join(words[:6]).strip() or "Produto"
        except:
            return "Produto"
    return text[:80]


def is_link(text: str) -> bool:
    return bool(re.match(r'https?://\S+', text.strip(), re.I))


# ══════════════════════════════════════════════════════════════
# GERAÇÃO DE CONTEÚDO
# ══════════════════════════════════════════════════════════════

def gen_hashtags(cat: str) -> dict[str, list[str]]:
    db = H.get(cat, H["geral"])
    return {
        "🔥 Virais": random.sample(db["v"], min(12, len(db["v"]))),
        "🎯 Nicho":  random.sample(db["n"], min(10, len(db["n"]))),
        "📦 Produto": random.sample(db["p"], min(8, len(db["p"]))),
        "📈 Trends": random.sample(db["t"], min(6, len(db["t"]))),
    }


def all_tags(hashtags: dict) -> str:
    return " ".join(t for tags in hashtags.values() for t in tags)


def gen_legendas(nome: str, cat_label: str) -> dict[str, str]:
    return {
        "📌 Principal": (
            f"🔥 {nome} — achado da Shopee!\n\n"
            f"Achei esse {cat_label} incrível e precisava compartilhar.\n\n"
            f"✅ Qualidade surreal pelo preço\n✅ Entrega rápida\n✅ Milhares de vendidos\n\n"
            f"⏰ Corre que tá com desconto!\n\n🔗 Link na bio\n\nSalva esse post! 🔖"
        ),
        "👀 Curiosidade": (
            f"Vocês NÃO vão acreditar no que achei na Shopee 👀\n\n"
            f"Esse {nome} tá dando o que falar.\n\n"
            f"Assiste até o final 😱\n\nComenta \"EU QUERO\" que mando o link 💬"
        ),
        "⚠️ Urgência": (
            f"⚠️ ALERTA DE OFERTA\n\n{nome} com desconto absurdo 🤯\n\n"
            f"Últimas unidades. Quando acaba, acaba.\n\n"
            f"🔗 Link nos comentários — corre! 🏃‍♂️"
        ),
        "👥 Prova Social": (
            f"+5.000 pessoas já compraram esse {nome} ⭐\n\n"
            f"Comprei também. Qualidade? Surpreendente.\n\n"
            f"Quer o link? Comenta 👇"
        ),
    }


def gen_hooks(nome: str, cat_label: str) -> list[str]:
    pool = [
        f"PARA de comprar {cat_label} sem ver isso antes",
        f"Achei o melhor {cat_label} da Shopee e ninguém fala sobre",
        f"3 motivos pra comprar esse {nome} AGORA",
        f"Testei esse {nome} e o resultado me CHOCOU",
        f"TODO MUNDO tá comprando isso e eu entendi porquê",
        f"O {cat_label} que VIRALIZOU na Shopee — vale a pena?",
        f"Comprei o {nome} mais vendido da Shopee",
        f"Esse {nome} é bom demais pra custar tão barato",
        f"POV: você descobre o melhor {cat_label} da Shopee",
        f"Se você não conhece esse {nome}, tá perdendo",
    ]
    random.shuffle(pool)
    return pool


def generate(text: str) -> dict:
    """Entrada principal — texto ou link → conteúdo viral completo."""
    nome = extract_name(text)
    nome_curto = " ".join(nome.split()[:5])
    cat, cat_label = detect_category(nome)
    platform = detect_platform(text) if is_link(text) else None

    hashtags = gen_hashtags(cat)
    legendas = gen_legendas(nome_curto, cat_label)
    hooks = gen_hooks(nome_curto, cat_label)

    return {
        "nome": nome_curto,
        "cat": cat,
        "cat_label": cat_label,
        "platform": platform,
        "platform_name": PLAT_NAMES.get(platform, ""),
        "platform_emoji": PLAT_EMOJI.get(platform, "🔗"),
        "hashtags": hashtags,
        "all_tags": all_tags(hashtags),
        "legendas": legendas,
        "hooks": hooks,
        "link": text.strip() if is_link(text) else None,
    }
