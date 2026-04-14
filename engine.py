import random, re
from urllib.parse import urlparse, unquote

H = {
    "eletronicos": ["#achados","#achadosshopee","#shopee","#shopeebrasil","#comprinhas","#recebidos","#viral","#fyp","#tiktokbrasil","#trending","#tech","#tecnologia","#gadgets","#unboxing","#review","#techtok","#valepena","#custobeneficio","#tiktokmefezcomprar","#produtosvirais","#tiktokshop","#achadosdatiktok","#shopeevideo","#achadinhos"],
    "moda": ["#moda","#fashion","#outfit","#lookdodia","#estilo","#shopee","#shopeebrasil","#achadosshopee","#viral","#fyp","#tiktokbrasil","#modafeminina","#roupabarata","#lookbaratinho","#fashiontiktok","#grwm","#getreadywithme","#outfitideas","#tiktokmefezcomprar","#haul","#comprinhas","#trending","#shopeevideo","#achadinhos"],
    "beleza": ["#beleza","#beauty","#skincare","#maquiagem","#makeup","#shopee","#shopeebrasil","#achadosshopee","#viral","#fyp","#tiktokbrasil","#rotinadebeleza","#beautytok","#beautyhacks","#glowup","#kbeauty","#testando","#recomendo","#antesedepois","#cuidados","#tiktokmefezcomprar","#trending","#shopeevideo","#achadinhos"],
    "casa": ["#casa","#decoracao","#organizacao","#limpeza","#shopee","#shopeebrasil","#achadosshopee","#viral","#fyp","#tiktokbrasil","#casaorganizada","#cozinha","#hometok","#cleantok","#diy","#achados","#utilidades","#hacks","#satisfying","#comprinhas","#tiktokmefezcomprar","#trending","#shopeevideo","#achadinhos"],
    "geral": ["#shopee","#shopeebrasil","#achadosshopee","#comprinhas","#recebidos","#viral","#fyp","#foryou","#paravoce","#tiktokbrasil","#trending","#ofertas","#desconto","#valepena","#achado","#unboxing","#tiktokmefezcomprar","#produtosvirais","#tiktokshop","#achadosdatiktok","#resenha","#testei","#shopeevideo","#achadinhos"],
}

CAT_RE = {
    "eletronicos": r"fone|bluetooth|caixa.?de.?som|smart.?watch|relogio|carregador|cabo|usb|led|luz|camera|drone|mouse|teclado|headset|earbuds|powerbank|celular|tablet|notebook|gamer|monitor|microfone|capinha",
    "moda": r"roupa|vestido|calca|blusa|camiseta|camisa|jaqueta|casaco|saia|shorts|conjunto|moletom|cropped|lingerie|pijama|tenis|bota|sandalia|chinelo|bone|oculos|bolsa|mochila",
    "beleza": r"maquiagem|batom|base|rimel|sombra|skincare|hidratante|protetor|serum|perfume|creme|shampoo|escova|chapinha|secador|esmalte",
    "casa": r"cozinha|organizador|prateleira|decoracao|tapete|cortina|luminaria|banheiro|lixeira|suporte|panela|frigideira|almofada|coberta|edredom|travesseiro",
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

PLAT_EMOJI = {"tiktok":"🎵","instagram":"📸","youtube":"▶️","kwai":"🎬","pinterest":"📌","shopee":"🛒","facebook":"📘","twitter":"🐦","threads":"🧵"}
VIDEO_OK = {"tiktok","youtube","twitter","pinterest","facebook","kwai","instagram","threads","shopee"}

def detect_platform(url):
    if not url: return None
    for k,p in PLAT_RE.items():
        if re.search(p, url, re.I): return k
    return None

def can_download(plat): return plat in VIDEO_OK

def _cat(text):
    for k,p in CAT_RE.items():
        if re.search(p, text.lower(), re.I): return k
    return "geral"

def _name(text):
    if re.match(r'https?://', text, re.I):
        try:
            path = unquote(urlparse(text).pathname)
            words = [w for w in re.split(r'[-_/.]', path) if len(w)>2 and not re.match(r'^(com|br|www|shopee|product|item|video|html|php|i|p|reel|watch|shorts|pin|\d+)$',w,re.I)]
            return " ".join(words[:4]).strip() or "Produto"
        except: return "Produto"
    return text[:50]

def generate(text):
    nome = _name(text.strip())
    cat = _cat(nome)
    plat = detect_platform(text) if re.match(r'https?://', text.strip(), re.I) else None
    tags = " ".join(random.sample(H.get(cat, H["geral"]), min(20, len(H.get(cat, H["geral"])))))
    captions = [
        f"🔥 {nome} — achado INCRÍVEL da Shopee!\n\n✅ Qualidade surreal\n✅ Entrega rápida\n⏰ Corre antes que acabe!\n\n🔗 Link na bio",
        f"👀 Olha o que achei na Shopee!\n\n{nome} com preço ABSURDO 🤯\n\nComenta \"QUERO\" que mando o link 💬",
        f"⚠️ ACHADO DO DIA\n\n{nome} — qualidade premium, preço de Shopee 🔥\n\nSalva esse post! 🔖\n🔗 Link nos comentários",
        f"TODO MUNDO comprando esse {nome} 🛒\n\n+5.000 vendidos ⭐\n\nQuer o link? Comenta 👇",
    ]
    cap = random.choice(captions)
    return {"caption": cap, "hashtags": tags, "full": f"{cap}\n\n{tags}", "platform": plat, "emoji": PLAT_EMOJI.get(plat,"🔗")}
