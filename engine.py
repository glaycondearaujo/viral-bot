"""
engine.py — Motor viral com legendas e hashtags otimizadas POR PLATAFORMA.
"""
import random, re
from urllib.parse import urlparse, unquote

# ══════════════════════════════════════════════════════════════
# HASHTAGS — BLOCOS POR CATEGORIA + BLOCOS POR PLATAFORMA
# Nunca mistura plataformas. Cada post tem hashtags do produto
# + hashtags específicas da rede onde vai ser postado.
# ══════════════════════════════════════════════════════════════

TAGS_PLAT = {
    "shopee": [
        "#shopee","#shopeebrasil","#shopeevideo","#achadosshopee","#achadinhosdashopee",
        "#compreinashopee","#shopeeachados","#shopeebr","#shopeeafiliado","#ofertashopee",
    ],
    "tiktok": [
        "#fyp","#foryou","#paravoce","#tiktokbrasil","#viral","#viralvideo",
        "#tiktokmefezcomprar","#tiktokshop","#achadosdatiktok","#trending","#fypシ",
    ],
    "insta": [
        "#reels","#reelsinstagram","#explore","#explorar","#viral","#trending",
        "#reelsbrasil","#instareels","#reelsvideo","#explorepage","#fy",
    ],
}

TAGS_COMPRAS = [
    "#achados","#achadinhos","#comprinhas","#ofertas","#desconto","#promocao",
    "#recebidos","#unboxing","#valepena","#custobeneficio","#ofertadodia","#economize",
]

TAGS_CAT = {
    "eletronicos": [
        "#tech","#tecnologia","#gadgets","#eletronicos","#acessorios",
        "#fonebluetooth","#smartwatch","#caixadesom","#setup","#inovacao",
        "#review","#resenha","#qualidade","#techreview",
    ],
    "moda": [
        "#moda","#fashion","#estilo","#look","#lookdodia","#outfit",
        "#tendencia","#roupas","#modafeminina","#modamasculina",
        "#streetwear","#closet","#inspiracao",
    ],
    "beleza": [
        "#beleza","#skincare","#maquiagem","#makeup","#beauty",
        "#rotinadebeleza","#cuidados","#peleperfeita","#glowup",
        "#autoestima","#dicasdebeleza","#beautyhacks","#kbeauty",
    ],
    "casa": [
        "#casa","#decoracao","#organizacao","#cozinha","#lar",
        "#casaorganizada","#limpeza","#diy","#utilidades","#pratico",
        "#transformacao","#dicasdecasa","#homedesign",
    ],
    "esporte": [
        "#fitness","#treino","#academia","#saude","#vidasaudavel",
        "#gym","#workout","#motivacao","#esporte","#corrida","#bemestar",
    ],
    "bebe": [
        "#bebe","#maternidade","#mae","#mamae","#filhos","#enxoval",
        "#maedemenino","#maedemenina","#dicasdemae","#mundomaterno",
    ],
    "pet": [
        "#pet","#cachorro","#gato","#petlover","#animais","#meupet",
        "#amorpeludos","#dogsofinstagram","#catlover",
    ],
    "lingerie": [
        "#lingerie","#modaintima","#camisola","#pijama","#sensualidade",
        "#autoestima","#empoderamento","#feminina","#sexy","#charme",
    ],
    "geral": [
        "#dicas","#recomendacao","#indicacao","#testei","#aprovado",
        "#resenha","#produtosbons","#achadosdodia","#compreiamei",
    ],
}

CAT_RULES = {
    "eletronicos": r"fone|bluetooth|caixa.?de.?som|smart.?watch|relogio|carregador|cabo|usb|led|luz|camera|drone|mouse|teclado|headset|earbuds|powerbank|celular|tablet|notebook|gamer|monitor|microfone|capinha|controle|pendrive|wifi|ring.?light|tripe",
    "lingerie": r"camisola|lingerie|pijama|calcinha|sutia|conjunto.?intimo|baby.?doll|tule|renda",
    "moda": r"roupa|vestido|calca|blusa|camiseta|camisa|jaqueta|casaco|saia|shorts|moletom|cropped|tenis|bota|sandalia|chinelo|bone|oculos|bolsa|mochila|carteira|cinto|regata|bermuda",
    "beleza": r"maquiagem|batom|base|rimel|sombra|skincare|hidratante|protetor|serum|perfume|creme|shampoo|escova|chapinha|secador|esmalte|pincel|demaquilante|mascara",
    "casa": r"cozinha|organizador|prateleira|decoracao|tapete|cortina|luminaria|banheiro|lixeira|panela|frigideira|almofada|coberta|edredom|travesseiro|dispenser",
    "esporte": r"fitness|treino|academia|gym|esporte|corrida|bicicleta|yoga|haltere|elastico|squeeze|whey|creatina|luva",
    "bebe": r"bebe|infantil|crianca|fraldas|mamadeira|chupeta|berco|carrinho|enxoval|body|macacao",
    "pet": r"cachorro|gato|pet|racao|coleira|brinquedo.?pet|cama.?pet|comedouro",
}

PLAT_RE = {
    "tiktok":r"tiktok\.com|vm\.tiktok|vt\.tiktok",
    "instagram":r"instagram\.com|instagr\.am",
    "youtube":r"youtube\.com|youtu\.be",
    "kwai":r"kwai\.com|kw\.ai",
    "pinterest":r"pinterest\.com|pin\.it",
    "shopee":r"shopee\.com|shp\.ee|s\.shopee",
    "facebook":r"facebook\.com|fb\.watch",
    "twitter":r"twitter\.com|x\.com|t\.co",
    "threads":r"threads\.net",
}

VIDEO_OK = {"tiktok","youtube","twitter","pinterest","facebook","kwai","instagram","threads","shopee"}

def detect_platform(url):
    if not url: return None
    for k,p in PLAT_RE.items():
        if re.search(p, url, re.I): return k
    return None

def can_download(plat): return plat in VIDEO_OK

def _cat(text):
    t = text.lower()
    # lingerie tem prioridade sobre moda
    if re.search(CAT_RULES["lingerie"], t, re.I): return "lingerie"
    for k,p in CAT_RULES.items():
        if k == "lingerie": continue
        if re.search(p, t, re.I): return k
    return "geral"

def _name(text):
    if re.match(r'https?://', text, re.I):
        try:
            path = unquote(urlparse(text).pathname)
            words = [w for w in re.split(r'[-_/.]', path)
                     if len(w)>2 and not re.match(
                         r'^(com|br|www|shopee|product|item|video|html|php|i|p|reel|watch|shorts|pin|\d+)$',w,re.I)]
            return " ".join(words[:4]).strip() or "esse produto"
        except: return "esse produto"
    return text[:50] if text else "esse produto"


# ══════════════════════════════════════════════════════════════
# LEGENDAS — 12 fórmulas de copywriting
# ══════════════════════════════════════════════════════════════

def _caption(nome: str, cat: str) -> str:
    labels = {
        "eletronicos":"eletrônico","moda":"peça","beleza":"produto de beleza",
        "casa":"item","esporte":"acessório","bebe":"item de bebê",
        "pet":"produto pet","lingerie":"peça","geral":"produto"
    }
    label = labels.get(cat, "produto")

    formulas = [
        f"⚠️ ÚLTIMAS UNIDADES\n\n{nome} com desconto absurdo.\nQuando acaba, acaba.\n\n🔗 Link na bio — corre!",
        f"Ninguém me contou sobre esse {nome}...\n\nDescobri sozinha e precisava dividir 👀\nAssiste até o final.\n\nQuer o link? Comenta 💬",
        f"+10.000 avaliações e nota 4.9 ⭐\n\nEsse {nome} não tá viralizando à toa.\nQualidade real pelo melhor preço.\n\n🔗 Link nos comentários",
        f"ANTES: sem esse {nome}\nDEPOIS: vida transformada 🔥\n\nSério, como eu vivia sem isso?\n\nSalva pra não esquecer 🔖",
        f"Esse {nome} DESTRUIU todos os concorrentes.\n\nTestei 5 opções. Esse ganhou de lavada.\n\nLink na bio 🔗",
        f"Eu tava procurando um {label} bom há meses...\n\nGastei dinheiro à toa em outros.\nAté que achei esse {nome}.\n\nMelhor decisão 🔗",
        f"Te DESAFIO a achar melhor que esse {nome}.\n\nQualidade premium, preço justo.\n\nQuem achou melhor? Comenta 👇",
        f"O {label} que ninguém mostra 👀\n\n{nome}\nSem publi, sem parceria. Comprei e amei.\n\nComenta \"QUERO\" 💬",
        f"Se você também procura {label} bom e barato...\n\nPara de sofrer. Achei esse {nome}.\nQualidade que surpreende.\n\n🔗 Link na bio",
        f"Você VAI se arrepender de não comprar isso.\n\n{nome} — menor preço que já vi.\nNão sei até quando fica assim.\n\n🔗 Link nos comentários",
        f"Já testei MUITO {label}.\n\nEsse {nome} é o melhor custo-benefício.\nPonto final.\n\n🔗 Link na bio",
        f"Achado do dia 🔥\n\n{nome}\n✅ Qualidade real\n✅ Preço justo\n✅ Entrega rápida\n\nSalva e agradece depois 🔖",
    ]
    return random.choice(formulas)


# ══════════════════════════════════════════════════════════════
# HASHTAGS POR PLATAFORMA
# Cada bloco é específico para a rede onde vai ser postado.
# ══════════════════════════════════════════════════════════════

def _tags_for(platform: str, cat: str) -> str:
    plat_tags = random.sample(TAGS_PLAT[platform], min(6, len(TAGS_PLAT[platform])))
    cat_tags = random.sample(TAGS_CAT.get(cat, TAGS_CAT["geral"]), min(8, len(TAGS_CAT.get(cat, TAGS_CAT["geral"]))))
    compras_tags = random.sample(TAGS_COMPRAS, min(4, len(TAGS_COMPRAS)))
    # Ordem: categoria → compras → plataforma
    return " ".join(cat_tags + compras_tags + plat_tags)


# ══════════════════════════════════════════════════════════════
# GERADOR PRINCIPAL
# ══════════════════════════════════════════════════════════════

def generate(text: str) -> dict:
    """Gera 3 versões de legenda + hashtags (Shopee, TikTok, Instagram)."""
    nome = _name(text.strip() if text else "")
    cat = _cat(nome)

    # Uma legenda para todos (mesmo texto funciona em qualquer plataforma)
    caption = _caption(nome, cat)

    # Hashtags separadas por plataforma
    tags_shopee = _tags_for("shopee", cat)
    tags_tiktok = _tags_for("tiktok", cat)
    tags_insta = _tags_for("insta", cat)

    full_shopee = f"{caption}\n\n{tags_shopee}"
    full_tiktok = f"{caption}\n\n{tags_tiktok}"
    full_insta = f"{caption}\n\n{tags_insta}"

    # "full" = versão exibida no chat (TikTok por padrão, mais viral)
    return {
        "caption": caption,
        "shopee": full_shopee,
        "tiktok": full_tiktok,
        "insta": full_insta,
        "full": full_tiktok,
        "category": cat,
    }
