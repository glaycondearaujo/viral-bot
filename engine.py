"""
engine.py — Motor de viralização.
Hashtags segmentadas por categoria (sem misturar plataformas).
Legendas com gatilhos mentais reais de copywriting.
"""
import random, re
from urllib.parse import urlparse, unquote

# ══════════════════════════════════════════════════════════════
# HASHTAGS — separadas por CATEGORIA, não por plataforma.
# Projetadas para alcance máximo em qualquer rede social.
# ══════════════════════════════════════════════════════════════

TAGS_ALCANCE = [
    "#viral","#fyp","#foryou","#paravoce","#trending","#fypシ",
    "#viralpost","#explore","#descoberta","#paginainicial",
]

TAGS_COMPRAS = [
    "#achados","#achadinhos","#comprinhas","#ofertas","#desconto",
    "#promocao","#recebidos","#unboxing","#valepena","#barato",
    "#custobeneficio","#melhoresprecos","#economize","#ofertadodia",
]

TAGS_CAT = {
    "eletronicos": [
        "#tech","#tecnologia","#gadgets","#eletronicos","#acessorios",
        "#fonebluetooth","#smartwatch","#caixadesom","#techtok",
        "#inovacao","#setup","#review","#resenha","#qualidade",
    ],
    "moda": [
        "#moda","#fashion","#estilo","#look","#lookdodia","#outfit",
        "#tendencia","#roupas","#modafeminina","#modamasculina",
        "#streetwear","#closet","#inspiracao","#estilocasual",
    ],
    "beleza": [
        "#beleza","#skincare","#maquiagem","#makeup","#beauty",
        "#rotinadebeleza","#cuidados","#peleperfeita","#glowup",
        "#autoestima","#dicasdebeleza","#beautyhacks","#produtosdebeleza",
    ],
    "casa": [
        "#casa","#decoracao","#organizacao","#cozinha","#lar",
        "#casaorganizada","#limpeza","#diy","#utilidades","#pratico",
        "#transformacao","#dicasdecasa","#homedesign","#funcional",
    ],
    "esporte": [
        "#fitness","#treino","#academia","#saude","#vidasaudavel",
        "#gym","#workout","#motivacao","#esporte","#corrida",
        "#lifestyle","#bemestar","#foco","#disciplina",
    ],
    "bebe": [
        "#bebe","#maternidade","#mae","#mamae","#filhos",
        "#enxoval","#maedemenino","#maedemenina","#dicasdemae",
        "#mundomaterno","#coisasdebebe","#recemnascido",
    ],
    "pet": [
        "#pet","#cachorro","#gato","#dogsofinstagram","#petlover",
        "#animais","#meupet","#amorpeludos","#viraldog","#catlover",
    ],
    "geral": [
        "#dicas","#recomendacao","#indicacao","#testei","#aprovado",
        "#resenha","#produtosbons","#achadosdodia","#compreiamei",
        "#pegueomeu","#precisodisso","#queromuito",
    ],
}

# ══════════════════════════════════════════════════════════════
# DETECÇÃO DE CATEGORIA
# ══════════════════════════════════════════════════════════════

CAT_RULES = {
    "eletronicos": r"fone|bluetooth|caixa.?de.?som|smart.?watch|relogio|carregador|cabo|usb|led|luz|camera|drone|mouse|teclado|headset|earbuds|powerbank|celular|tablet|notebook|gamer|monitor|microfone|capinha|controle|pendrive|hd|ssd|wifi|roteador|ring.?light|tripe",
    "moda": r"roupa|vestido|calca|blusa|camiseta|camisa|jaqueta|casaco|saia|shorts|conjunto|moletom|cropped|lingerie|pijama|tenis|bota|sandalia|chinelo|bone|oculos|bolsa|mochila|carteira|cinto|regata|bermuda",
    "beleza": r"maquiagem|batom|base|rimel|sombra|skincare|hidratante|protetor|serum|perfume|creme|shampoo|escova|chapinha|secador|esmalte|pincel|demaquilante|mascara|cilios|tonico",
    "casa": r"cozinha|organizador|prateleira|decoracao|tapete|cortina|luminaria|banheiro|lixeira|suporte|panela|frigideira|almofada|coberta|edredom|travesseiro|dispenser|jogo.?americano|porta.?copos",
    "esporte": r"fitness|treino|academia|gym|esporte|corrida|bicicleta|yoga|haltere|elastico|caneleira|squeeze|garrafa|suplemento|whey|creatina|luva",
    "bebe": r"bebe|infantil|crianca|fraldas|mamadeira|chupeta|berco|carrinho|enxoval|body|macacao",
    "pet": r"cachorro|gato|pet|racao|coleira|brinquedo.?pet|cama.?pet|comedouro|bebedouro.?pet",
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
    for k,p in CAT_RULES.items():
        if re.search(p, t, re.I): return k
    return "geral"

def _name(text):
    if re.match(r'https?://', text, re.I):
        try:
            path = unquote(urlparse(text).pathname)
            words = [w for w in re.split(r'[-_/.]', path)
                     if len(w)>2 and not re.match(
                         r'^(com|br|www|shopee|product|item|video|html|php|i|p|reel|watch|shorts|pin|\d+)$',w,re.I)]
            return " ".join(words[:4]).strip() or "Produto"
        except: return "Produto"
    return text[:50]


# ══════════════════════════════════════════════════════════════
# GERAÇÃO DE HASHTAGS INTELIGENTES
# ══════════════════════════════════════════════════════════════

def _gen_hashtags(cat: str) -> str:
    """Monta bloco de hashtags otimizado: alcance + compras + categoria."""
    alcance = random.sample(TAGS_ALCANCE, 5)
    compras = random.sample(TAGS_COMPRAS, 5)
    categoria = random.sample(TAGS_CAT.get(cat, TAGS_CAT["geral"]), min(8, len(TAGS_CAT.get(cat, TAGS_CAT["geral"]))))

    # Ordem: categoria primeiro (mais relevante), depois compras, depois alcance
    todos = categoria + compras + alcance
    return " ".join(todos)


# ══════════════════════════════════════════════════════════════
# LEGENDAS VIRAIS — 12 fórmulas de copywriting
# ══════════════════════════════════════════════════════════════

def _gen_caption(nome: str, cat: str) -> str:
    """Gera UMA legenda viral usando gatilhos mentais reais."""

    cat_labels = {
        "eletronicos":"eletrônico","moda":"roupa","beleza":"produto de beleza",
        "casa":"item de casa","esporte":"acessório fitness","bebe":"item de bebê",
        "pet":"produto pet","geral":"produto"
    }
    label = cat_labels.get(cat, "produto")

    formulas = [
        # ESCASSEZ + URGÊNCIA
        f"⚠️ ÚLTIMAS UNIDADES\n\n"
        f"{nome} com desconto absurdo.\n"
        f"Quando acaba, acaba. Não volta nesse preço.\n\n"
        f"🔗 Link na bio — corre!",

        # CURIOSIDADE
        f"Ninguém me contou sobre esse {nome}...\n\n"
        f"Descobri sozinha e precisava dividir com vocês.\n"
        f"Assiste até o final pra entender 👀\n\n"
        f"Quer o link? Comenta 💬",

        # PROVA SOCIAL
        f"+10.000 avaliações e nota 4.9 ⭐\n\n"
        f"Esse {nome} não tá viralizando à toa.\n"
        f"Qualidade real pelo melhor preço.\n\n"
        f"Link nos comentários 👇",

        # ANTES E DEPOIS
        f"ANTES: sem esse {nome}\n"
        f"DEPOIS: vida transformada 🔥\n\n"
        f"Sério, como eu vivia sem isso?\n\n"
        f"Salva pra não esquecer 🔖",

        # POLÊMICA / OPINIÃO FORTE
        f"Esse {nome} DESTRUIU todos os concorrentes.\n\n"
        f"Testei 5 opções diferentes.\n"
        f"Esse ganhou de lavada. Sem nem pensar.\n\n"
        f"Quer saber qual é? Link na bio 🔗",

        # STORYTELLING
        f"Eu tava procurando um {label} bom há meses...\n\n"
        f"Tentei vários, gastei dinheiro à toa.\n"
        f"Até que achei esse {nome}.\n\n"
        f"Melhor decisão. Link nos comentários 🔗",

        # DESAFIO
        f"Te DESAFIO a achar um {label} melhor que esse.\n\n"
        f"{nome} — qualidade premium, preço justo.\n\n"
        f"Quem achou melhor? Manda nos comentários 👇",

        # REVELAÇÃO
        f"O {label} que os influenciadores não mostram 👀\n\n"
        f"{nome}\n"
        f"Sem publi, sem parceria. Comprei e amei.\n\n"
        f"Comenta \"QUERO\" que mando o link 💬",

        # IDENTIFICAÇÃO
        f"Se você também procura {label} bom e barato...\n\n"
        f"Para de sofrer. Achei esse {nome}.\n"
        f"Qualidade que surpreende.\n\n"
        f"🔗 Link na bio",

        # GATILHO DE PERDA
        f"Você VAI se arrepender de não comprar isso agora.\n\n"
        f"{nome} — preço mais baixo que já vi.\n"
        f"Não sei até quando fica assim.\n\n"
        f"Link nos comentários 👇",

        # AUTORIDADE
        f"Como {label}, já testei MUITA coisa.\n\n"
        f"Esse {nome} é o melhor custo-benefício que já encontrei.\n"
        f"Ponto final.\n\n"
        f"🔗 Link na bio",

        # DIRETO E SIMPLES
        f"Achado do dia 🔥\n\n"
        f"{nome}\n"
        f"✅ Qualidade real\n"
        f"✅ Preço justo\n"
        f"✅ Entrega rápida\n\n"
        f"Salva e agradece depois 🔖",
    ]

    return random.choice(formulas)


# ══════════════════════════════════════════════════════════════
# GERADOR PRINCIPAL
# ══════════════════════════════════════════════════════════════

def generate(text: str) -> dict:
    """Gera legenda + hashtags a partir de link ou nome de produto."""
    nome = _name(text.strip())
    cat = _cat(nome)
    plat = detect_platform(text) if re.match(r'https?://', text.strip(), re.I) else None

    caption = _gen_caption(nome, cat)
    hashtags = _gen_hashtags(cat)

    return {
        "caption": caption,
        "hashtags": hashtags,
        "full": f"{caption}\n\n{hashtags}",
        "platform": plat,
    }
