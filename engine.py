"""
engine.py — Legendas virais + hashtags ESPECÍFICAS do produto.
SEM nomes de plataforma nas hashtags (#shopee, #tiktok, etc removidos).
Apenas hashtags relacionadas ao produto + alcance orgânico.
"""
import random, re
from urllib.parse import urlparse, unquote


# ══════════════════════════════════════════════════════════════
# HASHTAGS POR CATEGORIA DE PRODUTO
# Focadas em: o que o produto É, para quem SERVE, como se USA.
# Zero menção a Shopee / TikTok / Instagram.
# ══════════════════════════════════════════════════════════════

TAGS_CAT = {
    "eletronicos": [
        "#tecnologia", "#gadgets", "#tech", "#eletronicos", "#acessorios",
        "#inovacao", "#techreview", "#setup", "#workspace", "#produtividade",
        "#conectividade", "#bluetooth", "#wireless", "#semfio",
        "#qualidadepremium", "#custobeneficio", "#facildeusar",
    ],
    "fone_caixa_som": [
        "#fonebluetooth", "#fonedeouvido", "#caixadesom", "#audio",
        "#musica", "#som", "#grave", "#bass", "#tecnologia", "#gadgets",
        "#podcast", "#fitness", "#treino", "#acessorios",
    ],
    "smartwatch": [
        "#smartwatch", "#relogio", "#relogiodigital", "#smartband",
        "#fitness", "#saude", "#tecnologia", "#wearable", "#gadgets",
        "#estilo", "#acessorios", "#esporte",
    ],
    "moda": [
        "#moda", "#fashion", "#estilo", "#look", "#lookdodia", "#outfit",
        "#tendencia", "#fashionstyle", "#style", "#ootd", "#streetstyle",
        "#inspiracao", "#modafeminina", "#modamasculina", "#closet",
    ],
    "feminino": [
        "#modafeminina", "#roupafeminina", "#estilofeminino", "#look",
        "#fashion", "#outfit", "#ootd", "#grwm", "#getreadywithme",
        "#tendencia", "#elegante", "#delicado", "#feminina",
    ],
    "lingerie": [
        "#lingerie", "#modaintima", "#autoestima", "#empoderamento",
        "#sensualidade", "#feminina", "#delicada", "#renda", "#tule",
        "#conjunto", "#intimo", "#charme", "#confianca",
    ],
    "perfumaria": [
        "#perfume", "#perfumaria", "#fragrance", "#fragrancia",
        "#perfumefeminino", "#perfumemasculino", "#cheirogostoso",
        "#aroma", "#luxury", "#autoestima", "#body",
    ],
    "beleza": [
        "#beleza", "#beauty", "#skincare", "#rotinadebeleza", "#cuidados",
        "#peleperfeita", "#glowup", "#autoestima", "#dicasdebeleza",
        "#beautyhacks", "#antesedepois", "#resultado", "#belezanatural",
    ],
    "maquiagem": [
        "#maquiagem", "#makeup", "#maquiagembrasileira", "#batom",
        "#base", "#sombra", "#delineador", "#rimel", "#blush",
        "#maquiagemdodia", "#beautyhacks", "#tutorial", "#mua",
    ],
    "cabelo": [
        "#cabelo", "#cabelos", "#hair", "#hairstyle", "#cabeloperfeito",
        "#cachos", "#liso", "#ondulado", "#hidratacao", "#crescimentocapilar",
        "#cuidadoscomocabelo", "#beautyhacks",
    ],
    "casa": [
        "#casa", "#decoracao", "#organizacao", "#home", "#homedecor",
        "#casaorganizada", "#cozinha", "#hometok", "#cleantok", "#diy",
        "#utilidades", "#decor", "#interiordesign", "#inspiracao",
        "#dicasdecasa", "#transformacao",
    ],
    "cozinha": [
        "#cozinha", "#cozinhar", "#utensilioscozinha", "#kitchen",
        "#kitchentools", "#cozinhapratica", "#receitas", "#chef",
        "#cozinhafuncional", "#organizacao", "#praticidade",
    ],
    "esporte": [
        "#fitness", "#treino", "#academia", "#saude", "#vidasaudavel",
        "#gym", "#workout", "#motivacao", "#esporte", "#corrida",
        "#bemestar", "#foco", "#disciplina", "#resultado",
    ],
    "bebe": [
        "#bebe", "#maternidade", "#mae", "#mamae", "#filhos", "#enxoval",
        "#maedemenino", "#maedemenina", "#dicasdemae", "#mundomaterno",
        "#gravidez", "#maedeprimeiraviagem", "#cuidadoscomobebe",
    ],
    "pet": [
        "#pet", "#cachorro", "#gato", "#petlover", "#animais", "#meupet",
        "#amorpeludos", "#dogsofinstagram", "#catlover", "#doglover",
        "#petmom", "#petdad", "#cuidadoscompet",
    ],
    "automotivo": [
        "#carro", "#auto", "#automotivo", "#acessoriosautomotivos",
        "#carangas", "#carlover", "#tuning", "#motorista",
    ],
    "bolsa_mochila": [
        "#bolsa", "#mochila", "#bolsafeminina", "#bolsadecouro",
        "#acessorios", "#estilo", "#fashion", "#outfit", "#pratica",
        "#espacosa", "#organizada",
    ],
    "termico_viagem": [
        "#bolsatermica", "#marmita", "#fitness", "#vidasaudavel", "#dieta",
        "#marmitafit", "#trabalho", "#viagem", "#pratica", "#funcional",
        "#organizacao", "#rotina",
    ],
    "geral": [
        "#dicas", "#recomendacao", "#indicacao", "#testei", "#aprovado",
        "#resenha", "#produtosbons", "#achadosdodia", "#compreiamei",
        "#valepena", "#custobeneficio", "#qualidade", "#promocao",
    ],
}

# Hashtags de alcance orgânico — apenas termos genéricos que funcionam em TODAS as redes,
# sem nomes de plataforma nem termos exclusivos de alguma delas (#fyp é do TikTok, #reels é do IG, etc)
TAGS_ALCANCE = [
    "#viral", "#viralvideo", "#trending", "#tendencia",
    "#achados", "#achadinhos", "#achadosdodia", "#dica",
    "#recomendado", "#indicacao", "#valepena",
]


# ══════════════════════════════════════════════════════════════
# DETECÇÃO DE CATEGORIA — regras refinadas
# ══════════════════════════════════════════════════════════════

CAT_RULES = [
    # Ordem importa: específicos primeiro, genéricos depois
    ("fone_caixa_som",  r"fone|bluetooth|caixa.?de.?som|headset|earbuds|headphone|airdopes|jbl"),
    ("smartwatch",      r"smart.?watch|smartband|relogio.?digital|relogio.?smart|mi.?band|xiaomi.?watch"),
    ("lingerie",        r"camisola|lingerie|calcinha|sutia|conjunto.?intimo|baby.?doll|tule|renda"),
    ("perfumaria",      r"perfume|fragrance|body.?splash|colonia|desodorante.?perfume"),
    ("maquiagem",       r"maquiagem|batom|base|rimel|sombra|delineador|blush|iluminador|corretivo|pincel|paleta"),
    ("cabelo",          r"shampoo|condicionador|escova|chapinha|secador|hidratante.?capilar|mascara.?capilar|creme.?cabelo"),
    ("beleza",          r"skincare|hidratante|protetor.?solar|serum|acido|retinol|niacinamida|vitamina.?c|esfoliante"),
    ("cozinha",         r"cozinha|panela|frigideira|utensilio|talher|prato|copo|xicara|tabua|espatula|organizador.?cozinha"),
    ("casa",            r"decoracao|tapete|cortina|luminaria|banheiro|lixeira|almofada|coberta|edredom|travesseiro|prateleira"),
    ("esporte",         r"fitness|treino|academia|gym|corrida|bicicleta|yoga|haltere|elastico|squeeze|whey|creatina|caneleira"),
    ("bebe",            r"bebe|infantil|crianca|fraldas|mamadeira|chupeta|berco|carrinho|enxoval|macacao|body.?infantil"),
    ("pet",             r"cachorro|gato|petis|racao|coleira|brinquedo.?pet|comedouro|bebedouro"),
    ("automotivo",      r"carro|automotivo|pneu|bateria|oleo.?motor|limpa.?vidro|cera.?carro"),
    ("termico_viagem",  r"bolsa.?termica|marmita|mochila.?termica|termo|garrafa.?termica"),
    ("bolsa_mochila",   r"bolsa|mochila|necessaire|pochete|fanny.?pack|bag"),
    ("smartwatch",      r"watch|relogio"),
    ("feminino",        r"vestido|saia|shorts|cropped|blusa.?feminina"),
    ("moda",            r"roupa|camiseta|camisa|jaqueta|casaco|moletom|tenis|bota|sandalia|chinelo|bone|oculos"),
    ("eletronicos",     r"carregador|cabo|usb|led|luz|camera|drone|mouse|teclado|powerbank|notebook|tablet|celular|capinha|controle|microfone"),
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

VIDEO_OK = {"tiktok","youtube","twitter","pinterest","facebook","kwai","instagram","threads","shopee"}


def detect_platform(url):
    if not url: return None
    for k, p in PLAT_RE.items():
        if re.search(p, url, re.I): return k
    return None


def can_download(plat): return plat in VIDEO_OK


def _detect_cat(text):
    """Detecta categoria do produto baseado em palavras-chave."""
    t = text.lower() if text else ""
    for cat, pat in CAT_RULES:
        if re.search(pat, t, re.I):
            return cat
    return "geral"


def _extract_name(text):
    """Extrai nome do produto de uma URL ou texto."""
    if not text:
        return "esse produto"
    text = text.strip()
    if re.match(r'https?://', text, re.I):
        try:
            path = unquote(urlparse(text).pathname)
            # Filtrar palavras irrelevantes
            stop = {'com','br','www','shopee','product','item','video','html','php',
                    'i','p','reel','watch','shorts','pin','share','universal','link',
                    'redir','deep','and','web','smtt','uls','trackid','mercadolivre',
                    'sec','amzn','youtu','be','be','c','sv'}
            words = []
            for w in re.split(r'[-_/.]', path):
                w = w.strip()
                if (len(w) > 2 and
                    not w.isdigit() and
                    w.lower() not in stop and
                    not re.match(r'^[a-f0-9]{8,}$', w, re.I) and  # hashes
                    not re.match(r'^\d', w)):  # começa com número
                    words.append(w)
            if words:
                return " ".join(words[:4])
            return "esse produto"
        except:
            return "esse produto"
    return text[:60]


# ══════════════════════════════════════════════════════════════
# LEGENDAS VIRAIS — 12 fórmulas de copywriting testadas
# ══════════════════════════════════════════════════════════════

CAT_LABELS = {
    "fone_caixa_som": "fone",
    "smartwatch": "relógio",
    "lingerie": "peça",
    "perfumaria": "perfume",
    "maquiagem": "produto",
    "cabelo": "produto pra cabelo",
    "beleza": "produto de skincare",
    "cozinha": "utensílio",
    "casa": "item",
    "esporte": "acessório fitness",
    "bebe": "item de bebê",
    "pet": "produto pet",
    "automotivo": "acessório",
    "termico_viagem": "bolsa",
    "bolsa_mochila": "bolsa",
    "feminino": "peça",
    "moda": "peça",
    "eletronicos": "gadget",
    "geral": "produto",
}


def _gen_caption(nome: str, cat: str) -> str:
    label = CAT_LABELS.get(cat, "produto")

    formulas = [
        # Escassez
        f"⚠️ ÚLTIMAS UNIDADES\n\n{nome} com desconto absurdo.\nQuando acaba, acaba.\n\n🔗 Link na bio — corre!",
        # Curiosidade
        f"Ninguém me contou sobre esse {nome}...\n\nDescobri sozinha e precisava dividir 👀\nAssiste até o final.\n\nQuer o link? Comenta 💬",
        # Prova social
        f"+10.000 avaliações e nota 4.9 ⭐\n\nEsse {nome} não tá viralizando à toa.\nQualidade real pelo melhor preço.\n\n🔗 Link nos comentários",
        # Antes/depois
        f"ANTES: sem esse {nome}\nDEPOIS: vida transformada 🔥\n\nSério, como eu vivia sem isso?\n\nSalva pra não esquecer 🔖",
        # Polêmica
        f"Esse {nome} DESTRUIU todos os concorrentes.\n\nTestei 5 opções. Esse ganhou de lavada.\n\nLink na bio 🔗",
        # Storytelling
        f"Eu tava procurando um {label} bom há meses...\n\nGastei dinheiro à toa em outros.\nAté que achei esse {nome}.\n\nMelhor decisão 🔗",
        # Desafio
        f"Te DESAFIO a achar melhor que esse {nome}.\n\nQualidade premium, preço justo.\n\nQuem achou melhor? Comenta 👇",
        # Revelação
        f"O {label} que ninguém mostra 👀\n\n{nome}\nSem publi, sem parceria. Comprei e amei.\n\nComenta \"QUERO\" 💬",
        # Identificação
        f"Se você também procura {label} bom e barato...\n\nPara de sofrer. Achei esse {nome}.\nQualidade que surpreende.\n\n🔗 Link na bio",
        # Gatilho de perda
        f"Você VAI se arrepender de não comprar isso.\n\n{nome} — menor preço que já vi.\nNão sei até quando fica assim.\n\n🔗 Link nos comentários",
        # Autoridade
        f"Já testei MUITO {label}.\n\nEsse {nome} é o melhor custo-benefício.\nPonto final.\n\n🔗 Link na bio",
        # Direto
        f"Achado do dia 🔥\n\n{nome}\n✅ Qualidade real\n✅ Preço justo\n✅ Entrega rápida\n\nSalva e agradece depois 🔖",
    ]
    return random.choice(formulas)


# ══════════════════════════════════════════════════════════════
# GERADOR DE HASHTAGS
# Sem menção a plataformas. Apenas produto + alcance.
# ══════════════════════════════════════════════════════════════

def _gen_hashtags(cat: str) -> str:
    """Monta 20 hashtags: 12 específicas do produto + 8 de alcance."""
    cat_tags = TAGS_CAT.get(cat, TAGS_CAT["geral"])
    cat_selected = random.sample(cat_tags, min(14, len(cat_tags)))

    general = TAGS_CAT["geral"]
    # Se não for "geral", adicionar algumas gerais também pra reforçar conversão
    if cat != "geral":
        general_selected = random.sample(general, 3)
    else:
        general_selected = []

    alcance = random.sample(TAGS_ALCANCE, min(6, len(TAGS_ALCANCE)))

    # Ordem: produto → geral → alcance
    all_tags = cat_selected + general_selected + alcance
    # Garantir unicidade preservando ordem
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

def generate(text: str) -> dict:
    """Gera legenda + hashtags do produto (3 versões para copiar em plataformas distintas)."""
    if not text:
        text = ""
    nome = _extract_name(text.strip())
    cat = _detect_cat(nome)

    caption = _gen_caption(nome, cat)

    # Geramos 3 variações DE HASHTAGS — cada uma com tags diferentes aleatorizadas
    # mas TODAS focadas no produto. Isso dá ao usuário 3 opções ao invés de 1.
    hashtags_v1 = _gen_hashtags(cat)
    hashtags_v2 = _gen_hashtags(cat)
    hashtags_v3 = _gen_hashtags(cat)

    return {
        "caption": caption,
        "shopee": f"{caption}\n\n{hashtags_v1}",
        "tiktok": f"{caption}\n\n{hashtags_v2}",
        "insta":  f"{caption}\n\n{hashtags_v3}",
        "full":   f"{caption}\n\n{hashtags_v1}",  # versão exibida no chat
        "category": cat,
    }
