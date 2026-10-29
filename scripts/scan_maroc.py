#!/usr/bin/env python3
"""Scan quotidien du marché marocain pour l'appli Radar Emploi.

Lit les pages publiques d'offres de ReKrute, Exekutive et Michael Page Africa (dans le respect
de leur robots.txt), puis met à jour data/maroc.json (onglet Maroc) et data/offres.json (Mes offres).

- Les offres déjà évaluées à la main gardent leur estimation ("auto" absent ou faux).
- Les nouvelles offres reçoivent une estimation automatique d'après l'annonce complète ("auto": true).
- Les offres closes, retirées du site ou trop anciennes sont retirées.

Usage : python3 scripts/scan_maroc.py            (lecture des sites)
        python3 scripts/scan_maroc.py --offline DIR   (pages déjà enregistrées, pour les tests)
Bibliothèque standard uniquement.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAROC = os.path.join(ROOT, "data", "maroc.json")
OFFRES = os.path.join(ROOT, "data", "offres.json")
UA = "Mozilla/5.0 (compatible; RadarEmploi/1.0; +https://github.com/aminebenkhadra-dotcom/Job-search)"

REKRUTE_KEYWORDS = [
    "Trade-Marketing-Manager", "trade-marketing", "responsable-trade-marketing",
    "Marketing%20Manager", "responsable-marketing", "directeur-marketing", "Marketing-op%C3%A9rationnel",
    "brand-manager", "chef-de-produit", "chef-de-groupe", "category-manager",
    "Key%20Account%20Manager", "grands-comptes", "directeur-commercial", "responsable-commerciale",
    "directeur-des-ventes", "chef-des-ventes", "business-development-manager", "country-manager",
    "FMCG", "grande-consommation", "CHR",
]
PAGES = (
    [("ReKrute", "https://www.rekrute.com/emploi-" + k) for k in REKRUTE_KEYWORDS]
    + [("Exekutive", "https://exekutive.biz/offres-emploi-afrique.html")]
    + [("Michael Page", "https://www.michaelpageafrica.com/fr/jobs/" + p)
       for p in ("marketing-agences", "ventes", "marketing-director", "directeur-commercial/africa")]
)

MAX_MAROC = 80
MAX_OFFRES = 25
SEUIL_SELECTION = 55  # une offre marocaine entre dans « Mes offres » à partir de ce niveau

MA_CITIES = [
    "casablanca", "rabat", "marrakech", "tanger", "agadir", "fes", "meknes", "kenitra", "tetouan", "oujda",
    "nador", "el jadida", "mohammedia", "bouskoura", "temara", "sale", "laayoune", "dakhla", "settat",
    "berrechid", "beni mellal", "safi", "essaouira", "ifrane", "tit mellil", "had soualem", "larache",
    "khouribga", "skhirate", "ain sebaa", "sidi maarouf", "nouaceur", "maroc", "morocco",
]


# ---------------------------------------------------------------- outils
def norm(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def text(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", norm(s)).strip("-")[:n].strip("-")


def ddmmyyyy(s):
    try:
        return dt.datetime.strptime(s, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return ""


def days_since(iso, today):
    try:
        return (today - dt.date.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return None


def city_case(c):
    c = c.strip()
    return c.title() if c.isupper() or c.islower() else c


def offer_key(url):
    """Identifiant de l'annonce chez le site d'origine, pour éviter les doublons."""
    m = re.search(r"(?:rekrute\.com|exekutive\.biz)/.*?-(\d{5,})\.html", url or "")
    if m:
        return "rk:" + m.group(1)
    m = re.search(r"michaelpageafrica\.com/.*?/ref/(jn-\d{6}-\d+)", url or "")
    if m:
        return "mp:" + m.group(1)
    return ""


GENERIC_WORDS = {"groupe", "group", "societe", "ste", "les", "la", "le", "l", "the", "ets", "cie"}
NO_DEDUPE = {"", "confidentiel", "confidential", "michael"}


def first_word(company):
    w = [x for x in re.split(r"[^a-z0-9]+", norm(company)) if x and x not in GENERIC_WORDS]
    return w[0] if w else ""


def same_offer_signature(o):
    title = re.sub(r"\(?\b[hf] ?/ ?[hfx]\b\)?", "", norm(o.get("title", "")))
    title = re.sub(r"[^a-z0-9]+", " ", title).strip()
    return title + "|" + slug(o.get("place", ""))


# ---------------------------------------------------------------- lecture des sites
_robots = {}


def allowed(url):
    parts = urlsplit(url)
    host = parts.scheme + "://" + parts.netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except Exception:
            rp.parse([])
        _robots[host] = rp
    # Les pages de résultats filtrées (offres.html) sont fermées aux robots : on ne les lit jamais.
    if "/offres.html" in parts.path:
        return False
    return _robots[host].can_fetch(UA, url)


def fetch(url, status=False):
    """Contenu de la page (ou None). Avec status=True : (code HTTP, contenu) ; 404 et 410 signalent une annonce retirée."""
    if not allowed(url):
        print("  ignorée (robots.txt) :", url)
        return (None, None) if status else None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read().decode("utf-8", "replace")
                return (r.status, body) if status else body
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return (e.code, None) if status else None
            print(f"  échec ({attempt}) {url} : {e}")
        except Exception as e:  # réseau, délai dépassé…
            print(f"  échec ({attempt}) {url} : {e}")
        time.sleep(5)
    return (0, None) if status else None


# ---------------------------------------------------------------- analyse des pages
def parse_rekrute(page, base, source):
    """Pages ReKrute et Exekutive (même plateforme)."""
    out = []
    start = page.find('<ul class="job-list')
    if start < 0:
        return out
    blocks = re.split(r'<li class="post-id" id="', page[start:])[1:]
    for b in blocks:
        b = b.split('<ul class="pagination')[0]
        m = re.search(r"class='titreJob' href=\"([^\"]+)\">(.*?)</a>", b, re.S)
        if not m:
            continue
        href = m.group(1).split("?")[0].split("#")[0]
        full = text(m.group(2))
        title, _, loc = full.rpartition(" | ")
        if not title:
            title, loc = full, ""
        if loc and "(maroc)" not in norm(loc):
            continue  # offres hors Maroc
        city = city_case(re.sub(r"\s*\(.*?\)\s*$", "", loc)) or "Maroc"
        comp = re.search(r'alt="([^"]*)"\s+title="[^"]*"\s+class="photo"', b)
        company = text(comp.group(1)) if comp else "Confidentiel"
        dates = re.search(r"Publication : du\s*<span>([\d/]+)</span>\s*au\s*<span>([\d/]+)</span>", b)
        exp_block = re.search(r"Exp\S*rience requise :(.*?)</li>", b, re.S)
        exp = [text(x) for x in re.findall(r"<a[^>]*>(.*?)</a>", exp_block.group(1), re.S)] if exp_block else []
        sector = re.search(r"Secteur d'activit\S* : <a[^>]*>(.*?)</a>", b, re.S)
        summary = re.search(r'aiiconrose\.svg"\s*>\s*<span[^>]*>(.*?)</span>', b, re.S)
        out.append({
            "title": title.strip(),
            "company": company,
            "place": city,
            "url": base + href if href.startswith("/") else href,
            "source": source,
            "posted": ddmmyyyy(dates.group(1)) if dates else "",
            "deadline": ddmmyyyy(dates.group(2)) if dates else "",
            "experience": exp,
            "context": " ".join(filter(None, [text(sector.group(1)) if sector else "",
                                              text(summary.group(1)) if summary else ""])),
        })
    return out


def parse_michael_page(page):
    out = []
    tiles = re.findall(r'<div about="(/fr/job-detail/[^"]+)" class="job-tile[^"]*">(.*?)<div class="job-links">', page, re.S)
    for href, body in tiles:
        t = re.search(r"<h3><a[^>]*>(.*?)</a>", body, re.S)
        if not t:
            continue
        title = text(t.group(1))
        loc = re.search(r'job-location">(.*?)</div>', body, re.S)
        loc = text(loc.group(1)) if loc else ""
        summary = re.search(r'job-summary">(.*?)</div>\s*</div>', body, re.S)
        summary = text(summary.group(1)) if summary else ""
        # ville : celle de l'annonce, sinon celle écrite à la fin de l'intitulé (« … - Casablanca »)
        tail = title.rsplit(" - ", 1)[-1] if " - " in title else ""
        place = ""
        for cand in (loc, tail):
            if any(c in norm(cand) for c in MA_CITIES):
                place = city_case(cand)
                break
        if not place:
            continue  # offre hors Maroc
        if norm(place) in ("maroc", "morocco"):
            place = city_case(tail) if any(c in norm(tail) for c in MA_CITIES) else "Maroc"
        ref = re.search(r"/ref/jn-(\d{2})(\d{4})-", href)
        out.append({
            "title": re.sub(r"\s+-\s+[^-]+$", "", title).strip() if tail and norm(tail) in norm(place) else title,
            "company": "Michael Page · cabinet de recrutement",
            "place": place,
            "url": "https://www.michaelpageafrica.com" + href.split("?")[0],
            "source": "Michael Page",
            "posted": "",
            "month": f"{ref.group(2)}-{ref.group(1)}" if ref else "",
            "deadline": "",
            "experience": [],
            "context": summary,
        })
    return out


MIN_YEARS = re.compile(
    r"(?:minimum|minimale?|au moins)\s*(?:de\s*|d.\s*)?(\d{1,2})\s*ans|(\d{1,2})\s*ans\s*(?:d.exp\S*rience\s*)?(?:minimum|au moins)",
    re.I)


def enrich_michael_page(o, page):
    """Ajoute la description complète d'une offre Michael Page (secteur, années d'expérience)."""
    i = page.find("job_advert__job-desc")
    if i < 0:
        return
    end = page.find("Offres similaires", i)
    desc = text(page[i:end if end > i else i + 8000])[:5000]
    o["context"] = (o.get("context", "") + " " + desc).strip()
    m = re.search(r"(\d{1,2})\s*(?:à|a|-)\s*(\d{1,2})\s*ans", desc)
    if m:
        o["experience"] = [f"{m.group(1)} à {m.group(2)} ans"]
    else:
        m = MIN_YEARS.search(desc)
        if m:
            o["min_years"] = int(m.group(1) or m.group(2))



def enrich_rekrute(o, page):
    """Ajoute la description complète d'une offre ReKrute ou Exekutive : missions, profil, années demandées."""
    i = page.find('id="BlocDetailAnnonce"')
    if i < 0:
        return
    j = page.find('class="jo-testCta"', i)
    if j < 0:
        j = page.find('class="jo-applyBar"', i)
    desc = text(page[i:j if j > i else i + 20000])
    k = desc.find("Poste :")
    o["context"] = (o.get("context", "") + " " + desc[max(k, 0):][:5000]).strip()
    m = MIN_YEARS.search(desc[max(k, 0):])
    if m:
        o["min_years"] = int(m.group(1) or m.group(2))


# ---------------------------------------------------------------- estimation automatique
EXCLUDE_TITLE = re.compile(
    r"(?<!en )\bcharge(?:e|s|es)?\b|\bcommerci\w* terrain\b|\battache\w* commercia\w*|\bdelegue\w*|"
    r"\btechnico.commercia\w*|\bsuperviseu\w*|\bmerchandis\w*|\bpromot\w*|\banimat\w*|\bteleven\w*|"
    r"\bcommunication interne\b|"
    r"\b(stagiaire|stage|internship|intern|alternan\w*|apprenti\w*|junior|assistant\w*|"
    r"community|seo|sea|ads|media buyer|content|contenu|graphiste|infographiste|designer|redacteur|"
    r"conseiller\w*|teleconseill\w*|teleprospect\w*|call ?cent\w*|sdr|sales development|formateur|"
    r"formatrice|recouvrement|achats?|acheteur|purchas\w*|procurement|sourcing|supply|logisti\w*|hse|"
    r"ehs|qualite|quality|rh|ressources humaines|recrut\w*|comptab\w*|financ\w*|controle de gestion|"
    r"juriste|developpeur|ingenieur|engineer|technicien|maintenance|production|usine|magasinier|"
    r"caissier\w*|vendeu\w*|store manager|responsable magasin|operations|it)\b")
# Secteur que le candidat veut quitter : ces offres ne sont pas retenues.
EXCLUDE_SECTOR = re.compile(
    r"\b(vins?|spiritueux|wines?|spirits|brasseries?|bieres?|beers?|caviste|sommelier)\b|(?<!sans )\balcool\w*")
GOOD_SECTOR = re.compile(
    r"\b(fmcg|grande consommation|biens de consommation|agro\w*|alimentaire|food|boissons|beverages?|"
    r"cosmeti\w*|beaute|beauty|hygiene|retail|grande distribution|gms|horeca|chr|hotellerie|luxe|luxury|premium)\b")
FAR_SECTOR = re.compile(
    r"\b(pharma\w*|medical\w*|sante|clinique|automobile|automotive|informatique|logiciel|saas|software|"
    r"telecom\w*|technolog\w*|banque|bancaire|assurance\w*|immobilier|real estate|petrol\w*|carburants?|"
    r"energie|energy|btp|construction|aeronautique|education|ecole|universite|centre d.appel|presse|media|"
    r"securite|security|industri\w*|equipements?|vehicules?|camions?|trucks?|mobilite|transport|textile)\b")
PROCUREMENT = re.compile(r"\b(procurement|sourcing|matieres premieres|strategies? achats|achats (industriels|indirects|directs))\b")
GAMING = re.compile(
    r"\b(loterie|lottery|gaming|betting|casino|sorec|paris (?:sportifs|hippiques)|hippiques?|"
    r"jeux (?:de hasard|d.argent|en ligne)|marocaine des jeux)\b")

FAMILY_RULES = [
    ("Trade marketing", re.compile(r"\btrade\b"), 60),
    # « Directeur commercial et marketing » : un poste de direction, pas un poste marketing
    ("Direction", re.compile(r"\b(directeur|directrice|director|head)\b.*\b(commercia\w*|ventes?|sales)\b"), 40),
    ("Category", re.compile(r"\bcateg\w*\b"), 40),
    ("Marque & produit", re.compile(r"\b(brand|marques?|chef de produit|product manager|chef de groupe)\b"), 45),
    ("Marketing", re.compile(r"\bmarketing\b"), 45),
    ("Marketing", re.compile(r"\b(e-?commerce|digital|omnicanal|crm)\b"), 35),
    ("Marketing", re.compile(r"\bcommunication\b"), 30),
]
SALES = re.compile(
    r"\b(key account|kam|grands? comptes?|comptes? cles?|commercia\w*|ventes?|sales|business develop\w*|"
    r"account manager|chef de secteur|area manager|export)\b")
LEADER = re.compile(r"\b(directeur|directrice|director|head|national|country)\b")
GENERAL = re.compile(r"\b(directeur general|directrice generale|country manager|general manager|managing director|business unit manager)\b")
FAMILY_LABEL = {
    "Trade marketing": "Trade marketing", "Category": "Category management", "Marque & produit": "Marque et produit",
    "Marketing": "Marketing", "Vente & comptes clés": "Vente et comptes clés", "Direction": "Direction",
}


def family_of(title):
    t = norm(title)
    for fam, rx, base in FAMILY_RULES:
        if rx.search(t):
            return fam, base
    if GENERAL.search(t):
        return "Direction", 30
    if SALES.search(t):
        return ("Direction", 40) if LEADER.search(t) else ("Vente & comptes clés", 30)
    return None, 0


def years(labels):
    """« Confirmé (5 à 10 ans) », « Expert (10 à 20 ans) » → (5, 20)."""
    nums = [int(n) for lab in labels for n in re.findall(r"\d+", lab)]
    return (min(nums), max(nums)) if nums else None


def estimate(o):
    """Renvoie (famille, chances, explication) ou None si l'offre sort du domaine recherché."""
    t = norm(o["title"])
    ctx = norm(" ".join([o["title"], o.get("company", ""), o.get("context", "")]))
    if EXCLUDE_TITLE.search(t) or EXCLUDE_SECTOR.search(ctx):
        return None
    fam, score = family_of(o["title"])
    if not fam:
        return None
    if fam == "Category" and PROCUREMENT.search(ctx):
        return None  # category management côté achats
    parts = [FAMILY_LABEL[fam]]
    yr = years(o.get("experience") or [])
    mn = o.get("min_years")
    if mn and 1 <= mn <= 25:
        # le minimum écrit dans l'annonce est plus précis que la tranche du site
        yr = (mn, max(mn, yr[1]) if yr else mn)
    if yr:
        lo, hi = yr
        if hi <= 3:
            score -= 25
        elif hi <= 5:
            score -= 10
        elif hi >= 20 or lo >= 10:
            score += 10
        elif lo >= 8:
            score += 5
        parts.append(f"{lo} ans minimum demandés" if mn and lo == mn else f"{lo} à {hi} ans d'expérience demandés")
    if GOOD_SECTOR.search(ctx):
        score += 10
        parts.append("secteur proche de votre parcours")
    elif FAR_SECTOR.search(ctx):
        score -= 15
        parts.append("secteur éloigné de votre parcours")
    if GAMING.search(ctx):
        score += 10  # univers déjà pratiqué
        parts.append("univers des jeux, déjà pratiqué")
    score = max(5, min(70, score))
    why = ", ".join(parts) + ". Estimation automatique d'après l'annonce, à affiner."
    return fam, score, why[0].upper() + why[1:]


def excluded_sector(o):
    return bool(EXCLUDE_SECTOR.search(norm(" ".join([o.get("title", ""), o.get("company", ""), o.get("why", "")]))))


# ---------------------------------------------------------------- mise à jour des listes
def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("offers"), list) else {"offers": []}
    except (OSError, ValueError):
        return {"offers": []}


def save(path, d):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")


def still_open(o, today, max_age):
    if o.get("deadline") and (days_since(o["deadline"], today) or 0) > 0:
        return False
    age = days_since(o.get("posted"), today)
    if age is None:
        age = days_since(o.get("first_seen"), today)
        return age is None or age <= 60
    return age <= max_age


def merge(maroc, scraped, today, now_iso, sources, closed=frozenset()):
    iso = today.isoformat()
    offers = [o for o in maroc.get("offers", []) if isinstance(o, dict) and o.get("id")]
    by_key = {offer_key(o.get("url")): o for o in offers if offer_key(o.get("url"))}
    by_sig = {same_offer_signature(o): o for o in offers}
    ids = {o["id"] for o in offers}
    added = 0
    for s in scraped:
        key = offer_key(s["url"])
        cur = by_key.get(key) if key else None
        if cur is None:
            # même intitulé, même ville et même entreprise, sur un autre site : c'est la même offre
            twin = by_sig.get(same_offer_signature(s))
            # (une même entreprise publie parfois la même offre sur ReKrute et sur Exekutive, avec deux numéros)
            if twin and first_word(twin.get("company")) == first_word(s["company"]) \
                    and first_word(s["company"]) not in NO_DEDUPE:
                cur = twin
        if cur is not None:
            if s.get("deadline") and not cur.get("deadline"):
                cur["deadline"] = s["deadline"]
            if cur.get("auto"):
                # L'estimation du premier jour, faite avec l'annonce complète, est gardée.
                # On vérifie seulement que l'offre n'est pas sortie du domaine recherché.
                ctx = norm(" ".join([s["title"], s.get("company", ""), s.get("context", "")]))
                if EXCLUDE_TITLE.search(norm(s["title"])) or EXCLUDE_SECTOR.search(ctx):
                    cur["drop"] = True
            continue
        est = estimate(s)
        if not est:
            continue
        fam, chances, why = est
        month = (s.get("posted") or s.get("month") or iso)[:7]
        base_id = "-".join(filter(None, [slug(s["company"], 24), slug(s["title"], 44), slug(s["place"], 16), month]))
        oid, n = base_id, 2
        while oid in ids:
            oid, n = f"{base_id}-{n}", n + 1
        ids.add(oid)
        o = {"id": oid, "title": s["title"], "company": s["company"], "place": s["place"], "family": fam,
             "chances": chances, "why": why, "url": s["url"], "source": s["source"], "posted": s.get("posted", ""),
             "first_seen": iso, "auto": True}
        if s.get("deadline"):
            o["deadline"] = s["deadline"]
        offers.append(o)
        if key:
            by_key[key] = o
        by_sig[same_offer_signature(o)] = o
        added += 1
    before = len(offers)
    offers = [o for o in offers if not o.pop("drop", False)
              and offer_key(o.get("url")) not in closed
              and not (o.get("auto") and EXCLUDE_TITLE.search(norm(o.get("title", ""))))]
    offers = [o for o in dedupe(offers) if still_open(o, today, 90) and not excluded_sector(o)]
    removed = before - len(offers)
    offers.sort(key=lambda o: (-int(o.get("chances") or 0), o.get("posted") or "", o.get("id")))
    offers = offers[:MAX_MAROC]
    maroc.update({"updated": now_iso, "sources": sources, "offers": offers})
    return added, removed


def dedupe(offers):
    """Une même offre publiée deux fois (ou sur deux sites) n'apparaît qu'une fois ; l'évaluation à la main l'emporte."""
    seen, out = set(), []
    for o in sorted(offers, key=lambda o: (bool(o.get("auto")), o.get("first_seen") or "")):
        fw = first_word(o.get("company"))
        sig = (same_offer_signature(o), fw)
        if fw not in NO_DEDUPE and sig in seen:
            continue
        seen.add(sig)
        out.append(o)
    return out


def sync_selection(sel, maroc, today, now_iso):
    """« Mes offres » : les meilleures offres marocaines + les offres d'ailleurs déjà retenues."""
    mar = {o["id"]: o for o in maroc["offers"]}
    keep = []
    for o in sel.get("offers", []):
        if not isinstance(o, dict) or not o.get("id"):
            continue
        if o.get("country") == "Maroc":
            m = mar.get(o["id"])
            if not m or int(m.get("chances") or 0) < SEUIL_SELECTION:
                continue
            for k in ("chances", "why", "deadline", "url", "title", "company", "place"):
                if k in m:
                    o[k] = m[k]
        keep.append(o)
    have = {o["id"] for o in keep}
    for m in maroc["offers"]:
        if m["id"] not in have and int(m.get("chances") or 0) >= SEUIL_SELECTION:
            o = {k: v for k, v in m.items() if k not in ("family",)}
            o["country"] = "Maroc"
            keep.append(o)
    keep = [o for o in keep if still_open(o, today, 60) and not excluded_sector(o)]
    keep.sort(key=lambda o: (-int(o.get("chances") or 0), o.get("posted") or ""))
    sel.update({"updated": now_iso, "offers": keep[:MAX_OFFRES]})


def main():
    offline = None
    if "--offline" in sys.argv:
        offline = sys.argv[sys.argv.index("--offline") + 1]
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    today, now_iso = now.date(), now.strftime("%Y-%m-%dT%H:%M:%SZ")

    scraped, ok_sources = [], []
    for source, url in PAGES:
        if offline:
            name = os.path.join(offline, slug(url, 120) + ".html")
            page = open(name, encoding="utf-8", errors="replace").read() if os.path.exists(name) else None
        else:
            page = fetch(url)
            time.sleep(2.5)
        if not page:
            continue
        found = parse_michael_page(page) if source == "Michael Page" else parse_rekrute(
            page, "https://exekutive.biz" if source == "Exekutive" else "https://www.rekrute.com", source)
        print(f"{source:12} {len(found):3} offres au Maroc · {url}")
        scraped.extend(found)
        if source not in ok_sources:
            ok_sources.append(source)

    def detail(url):
        """(code HTTP, page) d'une annonce ; hors ligne : la page enregistrée, sinon (None, None)."""
        if offline:
            name = os.path.join(offline, slug(url, 120) + ".html")
            return (200, open(name, encoding="utf-8", errors="replace").read()) if os.path.exists(name) else (None, None)
        res = fetch(url, status=True)
        time.sleep(2.5)
        return res

    # pages de détail des nouvelles offres (le résumé des listes ne suffit pas pour estimer)
    current = load(MAROC)["offers"]
    known = {offer_key(o.get("url")) for o in current}
    for o in scraped:
        key = offer_key(o["url"])
        if not key or key in known:
            continue
        known.add(key)
        code, page = detail(o["url"])
        if page:
            if o["source"] == "Michael Page":
                enrich_michael_page(o, page)
            else:
                enrich_rekrute(o, page)

    # annonces Michael Page déjà listées : sans date de clôture, on vérifie qu'elles sont toujours en ligne
    closed = set()
    seen_now = {offer_key(o["url"]) for o in scraped}
    for o in current:
        key = offer_key(o.get("url"))
        if key.startswith("mp:") and key not in seen_now:
            code, _ = detail(o["url"])
            if code in (404, 410):
                closed.add(key)
                print("  annonce retirée :", o["url"])

    if not ok_sources:
        print("Aucun site n'a pu être lu : listes inchangées.")
        return 1

    maroc = load(MAROC)
    added, removed = merge(maroc, scraped, today, now_iso, ok_sources, closed)
    sel = load(OFFRES)
    sync_selection(sel, maroc, today, now_iso)
    save(MAROC, maroc)
    save(OFFRES, sel)
    print(f"Maroc : {len(maroc['offers'])} offres ({added} nouvelles, {removed} retirées) · Mes offres : {len(sel['offers'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
