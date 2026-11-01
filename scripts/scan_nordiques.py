#!/usr/bin/env python3
"""Scan quotidien des pays nordiques pour l'appli Radar Emploi.

Sources publiques, sans clé :
- Suède : JobTech JobSearch (Arbetsförmedlingen / Platsbanken), quelques recherches ciblées.
- Norvège : flux public des offres de NAV (arbeidsplassen.no), jeton public.
- Danemark : pages de recherche de Jobindex (dans le respect de son robots.txt).
La Finlande (Duunitori refuse les robots) et l'Islande n'ont pas de source ouverte : l'appli ouvre leurs sites.

Met à jour data/nordiques.json (onglet Marchés) et ajoute les meilleures offres à data/offres.json (Mes offres).
- Les offres déjà évaluées à la main gardent leur estimation ("auto" absent ou faux).
- Les nouvelles offres reçoivent une estimation automatique ("auto": true), plafonnée à 70 % :
  sans la langue du pays et avec un permis de travail à obtenir, une estimation plus haute ne serait pas honnête.

Usage : python3 scripts/scan_nordiques.py [--dump DIR]   (DIR : exemples bruts enregistrés, pour mise au point)
Bibliothèque standard uniquement.
"""
import datetime as dt
import email.utils
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote_plus, urljoin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_maroc as mx  # outils communs : norm, slug, robots.txt, secteurs, familles de métiers

ROOT = mx.ROOT
NORD = os.path.join(ROOT, "data", "nordiques.json")
OFFRES = mx.OFFRES
UA = mx.UA
MAX_NORD = 150
MAX_AUTO = 70
SEUIL_SELECTION = 45  # une offre nordique entre dans « Mes offres » à partir de ce niveau
COUNTRY = {"SE": "Suède", "NO": "Norvège", "DK": "Danemark", "FI": "Finlande", "IS": "Islande"}

SE_QUERIES = ["marketing manager", "trade marketing", "brand manager", "category manager", "key account manager",
              "head of marketing", "marketing director", "export manager", "commercial director", "marknadschef",
              "sales director", "country manager"]
DK_QUERIES = ["marketing manager", "trade marketing", "brand manager", "category manager", "key account manager",
              "head of marketing", "export manager", "commercial director"]


# ---------------------------------------------------------------- outils
def nn(s):
    """norm() après conversion des lettres nordiques que la décomposition Unicode ne ramène pas à l'ASCII."""
    s = (s or "").replace("ø", "o").replace("Ø", "O").replace("æ", "ae").replace("Æ", "AE")
    return mx.norm(s)


def get(url, headers=None, as_json=False, check_robots=True):
    if check_robots and not mx.allowed(url):
        print("  ignorée (robots.txt) :", url)
        return None
    h = {"User-Agent": UA, "Accept-Language": "en,sv;q=0.8,no;q=0.7,da;q=0.6"}
    h.update(headers or {})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=45) as r:
                body = r.read().decode("utf-8", "replace")
                return json.loads(body) if as_json else body
        except urllib.error.HTTPError as e:
            print(f"  échec ({attempt}) {url[:120]} : {e}")
            if e.code in (400, 401, 403, 404, 410):
                return None
        except Exception as e:
            print(f"  échec ({attempt}) {url[:120]} : {e}")
        time.sleep(5)
    return None


def day(s):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------- langue de l'annonce
EN_WORDS = {"the", "and", "you", "with", "our", "will", "are", "of", "to", "we", "your", "is", "as", "be", "this", "have"}
LOCAL_WORDS = {"och", "att", "är", "för", "som", "har", "på", "till", "inom", "kommer", "og", "er", "til", "innen",
               "skal", "ikke", "deg", "dig", "være", "vara", "oss", "jeg", "eller", "også", "också", "af", "hos",
               "ja", "että", "sekä", "tai", "ovat", "sinä", "meillä", "du", "vi", "med", "ett", "det", "av"}
LOCAL_REQ = re.compile(
    r"(fluent|native|excellent|strong|good|very good|professional|business|full)[^.\n]{0,40}\b"
    r"(swedish|norwegian|danish|finnish|icelandic|scandinavian)\b|"
    r"\b(swedish|norwegian|danish|finnish|scandinavian)\b[^.\n]{0,40}\b(required|is a must|mandatory|fluent|fluency|"
    r"native|essential|necessary)\b|"
    r"\b(swedish|norwegian|danish|finnish) and english\b|"
    r"svenska (i tal och skrift|och engelska)|flytande svenska|goda kunskaper i svenska|behärska\w* svenska|"
    r"norsk (muntlig|skriftlig|og engelsk)|beherske\w* norsk|flytende norsk|god norsk|"
    r"dansk (i skrift og tale|og engelsk)|taler og skriver dansk|flydende dansk|perfekt dansk|skandinavisk|"
    r"sujuva suomi|suomen kiel", re.I)
ENGLISH_OK = re.compile(
    r"english is (our|the) (corporate|company|working|official|business|group) language|working language is english|"
    r"no (swedish|norwegian|danish|finnish) (is )?(required|needed)|"
    r"(swedish|norwegian|danish|finnish|scandinavian)( language)?( skills)? (is|are|would be) (a plus|an advantage|"
    r"nice to have|beneficial|not required|a bonus)", re.I)


def language(txt):
    """'en', 'local' ou '' (mélange ou texte trop court)."""
    w = re.findall(r"[a-zåäöæøéü]+", (txt or "").lower())
    en = sum(1 for x in w if x in EN_WORDS)
    loc = sum(1 for x in w if x in LOCAL_WORDS)
    if en + loc < 6:
        return ""
    r = en / (en + loc)
    return "en" if r >= 0.62 else ("local" if r <= 0.35 else "")


# ---------------------------------------------------------------- métiers et estimation
# Les intitulés suédois, norvégiens et danois sont ramenés aux mots anglais compris par les règles du scan marocain.
LOCAL_TITLES = [
    (r"\b(marknadschef|marknadsdirektor|marknadsansvarig|marknadsforingschef|markedssjef|markedsdirektor|"
     r"markedsansvarlig|markedschef|marketingchef|marketingdirektor|marketingansvarlig|markedsforingsleder|"
     r"marknadsforing\w*|markedsforing\w*)\b", " marketing manager "),
    (r"\b(forsaljningschef|forsaljningsdirektor|saljchef|saljdirektor|salgssjef|salgsdirektor|salgschef|"
     r"kommersiell direktor|kommersiell chef|kommerciel direktor|salgsleder)\b", " sales director "),
    (r"\b(kategori\w*)\b", " category "),
    (r"\b(varumarkes\w*|varumarke|merkevare\w*|brandansvarig|brand ansvarlig)\b", " brand "),
    (r"\b(nyckelkundsansvarig|nyckelkund\w*|kundansvarig|key account\w*|kam)\b", " key account "),
    (r"\b(exportchef|eksportsjef|eksportchef|exportansvarig|eksportansvarlig)\b", " export manager "),
    (r"\b(landschef|adm\.? direktor|administrerende direktor|vd)\b", " country manager "),
]
EXCLUDE_NORD = re.compile(
    r"\b(praktik\w*|praksis\w*|trainee\w*|sommar\w*|sommer\w*|assistent\w*|koordinator\w*|coordinator|saljare|"
    r"selger|saelger|butik\w*|butikk\w*|kundservice|kundtjanst|kundeservice|studentjobb?|student|deltid|"
    r"timvikarie|vikariat|vikar|telemarketing|innesalj\w*|telefon\w*|lager\w*|chauffor|sjafor|"
    r"specialist|analyst|analytiker|automation|performance|growth|product marketing|"
    r"marketing operations|marketing technolog\w*|martech|web|developer|utvecklare|utvikler|ux|ui|"
    r"compliance|legal|counsel|controller|control|phd|candidate|researcher|postdoc|internal communications?|"
    r"parental|maternity|cover|studenter\w*|medhjaelper|advisor|adviser|art director|creative|designer)\b")
NORDIC_GOOD = re.compile(
    r"\b(dagligvar\w*|livsmedel\w*|dagligvaruhandel|matvar\w*|konsumentvar\w*|forbrugsvar\w*|naeringsmiddel\w*|"
    r"arla|fazer|paulig|orkla|cloetta|oatly|essity|valio|tine|nortura|mills|lantmannen|scandi standard|atria|hkscan|"
    r"ica|axfood|coop|norgesgruppen|rema|salling|kesko|s.group|dagrofa|kiwi|meny|willys|hemkop|lidl|"
    r"procter|unilever|nestle|danone|mondelez|ferrero|coca.cola|pepsico|kellogg|l.oreal|beiersdorf|henkel|"
    r"colgate|reckitt|haleon|kenvue|estrella|olw|marabou|freia|toms|haribo|felix|abba|kavli|bama|findus)\b")
NORDIC_FAR = re.compile(
    r"\b(it.?konsult\w*|programvar\w*|mjukvar\w*|bank\w*|forsakring\w*|forsikring\w*|fastighet\w*|eiendom\w*|"
    r"bygg\w*|entreprenad\w*|lakemedel\w*|legemiddel\w*|medtech|biotech|halsa|sjukvard\w*|helse|tech|"
    r"industri\w*|maskin\w*|elektronik\w*|energi\w*|kraft|olje|gas|shipping|rederi\w*|konsult\w*|byra|reklambyra|"
    r"defen[cs]e|military|weapons?|drones?|surveillance|mobility|emobility|charging|consultancy|"
    r"kommun\w*|myndighet\w*|forening\w*|forbund\w*|universitet\w*|hogskola|skola|fagforbund)\b")
NORDIC_ALCOHOL = re.compile(
    r"\b(carlsberg|heineken|royal unibrew|systembolaget|vinmonopolet|alko|altia|anora|pernod|diageo|arcus|"
    r"brewdog|bryggeri\w*|brygghus|vin|viner|vine|sprit|spritt|brennevin|akevitt|cider)\b|\bol\b|\bøl\b")
GAMING_NORD = re.compile(
    r"\b(svenska spel|atg|veikkaus|norsk tipping|danske spil|kindred|betsson|leovegas|kambi|unibet|"
    r"lotteri\w*|lottery|lotto|betting|igaming|gaming|casino|spelbolag\w*|pengespill|tipping)\b")
EDGE = re.compile(
    r"\b(mena|middle east|north africa|africa|african|francophone|french|arabic|morocco|maghreb|emerging markets|"
    r"franska|fransk|arabiska|arabisk|afrika|mellanostern|midtosten|nordafrika)\b")
YEARS_RX = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs|ars|år|års|aars)\b", re.I)
SENIOR = re.compile(r"\b(director|direktor|head|senior|chef|sjef|lead|leder|vp|vice president|country)\b")
FAMILY_BASE = {"Trade marketing": 50, "Category": 42, "Marque & produit": 42, "Marketing": 40, "Direction": 38,
               "Vente & comptes clés": 28, "Export": 48}


def title_en(title):
    t = nn(title)
    for rx, rep in LOCAL_TITLES:
        t = re.sub(rx, rep, t)
    return re.sub(r"\s+", " ", t).strip()


def years_asked(txt):
    nums = [int(n) for n in YEARS_RX.findall(txt or "") if 1 <= int(n) <= 15]  # au-delà : souvent l'âge de l'entreprise
    return max(nums) if nums else None


def estimate(o):
    """(famille, chances, explication, langue, langue exigée) ou None si l'offre sort du domaine recherché."""
    t = title_en(o["title"])
    desc = o.get("desc", "")
    ctx = nn(" ".join([o["title"], o.get("company", ""), desc]))
    raw = " ".join([o["title"], o.get("company", ""), desc]).lower()
    if mx.EXCLUDE_TITLE.search(t) or EXCLUDE_NORD.search(nn(o["title"])):
        return None
    if mx.EXCLUDE_SECTOR.search(ctx) or NORDIC_ALCOHOL.search(nn(o["title"] + " " + o.get("company", ""))):
        return None  # secteur que le candidat quitte
    if re.search(r"\bexport\b", t) or (EDGE.search(nn(o["title"])) and re.search(r"\b(manager|director|head|lead)\b", t)):
        fam, score = "Export", FAMILY_BASE["Export"]
    else:
        fam, _ = mx.family_of(t)
        if not fam:
            return None
        if fam == "Category" and mx.PROCUREMENT.search(ctx):
            return None
        score = FAMILY_BASE.get(fam, 35)
    parts = ["Export et international" if fam == "Export" else mx.FAMILY_LABEL[fam]]
    if SENIOR.search(t):
        score += 5
    # langue : c'est le premier filtre des recruteurs nordiques
    lang = language(desc)
    req = bool(LOCAL_REQ.search(raw))
    ok_en = bool(ENGLISH_OK.search(raw))
    if lang == "local":
        score -= 20
        req = True
        parts.append("annonce en langue locale, la langue sera exigée")
    elif req and not ok_en:
        score -= 15
        parts.append("langue du pays exigée")
    elif lang == "en" or ok_en:
        score += 5
        req = False
        parts.append("annonce en anglais")
    if EDGE.search(ctx):
        score += 12
        parts.append("votre atout : français, arabe, Afrique ou MENA")
    yrs = years_asked(desc)
    if yrs is not None:
        if yrs <= 3:
            score -= 15
        elif yrs >= 8:
            score += 5
        parts.append(f"{yrs} ans d'expérience demandés")
    head = nn(o["title"] + " " + o.get("company", ""))
    sector = ""
    for level, txt in enumerate((head, nn(desc[:300]), ctx)):
        good = bool(mx.GOOD_SECTOR.search(txt) or NORDIC_GOOD.search(txt))
        far = bool(mx.FAR_SECTOR.search(txt) or NORDIC_FAR.search(txt))
        if good or far:
            sector = "far" if far and (not good or level == 0) else ("good" if not far else "")
            break
    if sector == "good":
        score += 10
        parts.append("grande consommation, votre secteur")
    elif sector == "far":
        score -= 15
        parts.append("secteur éloigné de votre parcours")
    if GAMING_NORD.search(ctx) or mx.GAMING.search(ctx):
        score += 10
        parts.append("jeux et loteries, déjà pratiqués")
    hits = sum(1 for rx in mx.STRENGTHS if rx.search(ctx))
    score += min(6, 2 * hits)
    score = max(5, min(MAX_AUTO, score))
    why = ", ".join(parts) + ". Estimation automatique, permis de travail à prévoir."
    return fam, score, why[0].upper() + why[1:], lang, req


# ---------------------------------------------------------------- Suède : JobTech JobSearch
def scan_sweden(dump):
    out, seen = [], set()
    for q in SE_QUERIES:
        url = "https://jobsearch.api.jobtechdev.se/search?q=" + quote_plus(q) + "&limit=100"
        d = get(url, {"accept": "application/json"}, as_json=True, check_robots=False)
        time.sleep(1.5)
        if not d:
            continue
        if dump and q == SE_QUERIES[0]:
            save_dump(dump, "se-sample.json", d.get("hits", [])[:2])
        n = 0
        for h in d.get("hits", []):
            hid = str(h.get("id") or "")
            if not hid or hid in seen or h.get("removed"):
                continue
            seen.add(hid)
            addr = h.get("workplace_address") or {}
            if addr.get("country") and addr.get("country") not in ("Sverige", "Sweden"):
                continue
            emp = h.get("employer") or {}
            desc = ((h.get("description") or {}).get("text") or "")[:6000]
            langs = " ".join(x.get("label", "") for x in ((h.get("must_have") or {}).get("languages") or []))
            if re.search(r"svenska", langs, re.I):
                desc += "\nflytande svenska"
            out.append({"key": "se:" + hid, "title": (h.get("headline") or "").strip(), "company": (emp.get("name") or "").strip(),
                        "place": addr.get("city") or addr.get("municipality") or "Suède", "cc": "SE",
                        "url": h.get("webpage_url") or f"https://arbetsformedlingen.se/platsbanken/annonser/{hid}",
                        "source": "Platsbanken", "posted": day(h.get("publication_date")),
                        "deadline": day(h.get("application_deadline")), "desc": desc})
            n += 1
        print(f"Suède     {n:3} annonces · « {q} »")
    return out


# ---------------------------------------------------------------- Norvège : flux NAV
NAV = "https://pam-stilling-feed.nav.no"


def nav_token():
    t = get(NAV + "/api/publicToken", check_robots=False) or ""
    m = re.search(r"([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", t)
    return m.group(1) if m else ""


def walk(o, key):
    """Première valeur trouvée pour une clé, à n'importe quelle profondeur."""
    if isinstance(o, dict):
        if key in o and o[key] not in (None, "", [], {}):
            return o[key]
        for v in o.values():
            r = walk(v, key)
            if r not in (None, "", [], {}):
                return r
    elif isinstance(o, list):
        for v in o:
            r = walk(v, key)
            if r not in (None, "", [], {}):
                return r
    return None


def scan_norway(dump, since_days, budget=60):
    tok = os.environ.get("NAV_TOKEN", "").strip() or nav_token()  # jeton privé si enregistré, sinon public
    if not tok:
        print("Norvège : jeton public indisponible")
        return [], set(), False
    auth = {"Authorization": "Bearer " + tok, "Accept": "application/json"}
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=since_days)
    hdr = dict(auth)
    hdr["If-Modified-Since"] = email.utils.format_datetime(since, usegmt=True)
    url, pages, cand, inactive, last = NAV + "/api/v1/feed", 0, {}, set(), None
    while url and pages < 80:
        d = get(url, hdr if pages == 0 else auth, as_json=True, check_robots=False)
        pages += 1
        if not d:
            break
        items = d.get("items") or []
        for it in items:
            fe = it.get("_feed_entry") or {}
            uid = fe.get("uuid") or it.get("id")
            if not uid:
                continue
            if fe.get("status") != "ACTIVE":
                inactive.add("no:" + uid)
                cand.pop(uid, None)
                continue
            title = fe.get("title") or it.get("title") or ""
            if estimate({"title": title, "company": fe.get("businessName") or "", "desc": ""}) is None:
                continue
            cand[uid] = {"uid": uid, "url": urljoin(NAV, it.get("url") or ""), "title": title,
                         "company": fe.get("businessName") or "", "place": (fe.get("municipal") or "").title()}
        nxt = d.get("next_url")
        if not items or not nxt or d.get("next_id") == last:
            break
        last = d.get("next_id")
        url = urljoin(NAV, nxt)
        time.sleep(0.5)
    print(f"Norvège   {len(cand):3} annonces du domaine · {pages} pages du flux")
    out = []
    for i, c in enumerate(list(cand.values())[:budget]):
        e = get(c["url"], auth, as_json=True, check_robots=False)
        time.sleep(0.6)
        if not e:
            continue
        if dump and i < 2:
            save_dump(dump, f"no-entry-{i}.json", e)
        desc = mx.text(str(walk(e, "description") or ""))[:6000]
        due = str(walk(e, "applicationDue") or "")
        if not re.match(r"\d{4}-", due):
            due = str(walk(e, "expires") or "")
        out.append({"key": "no:" + c["uid"], "title": c["title"], "company": str(walk(e, "businessName") or c["company"]),
                    "place": c["place"] or "Norvège", "cc": "NO",
                    "url": "https://arbeidsplassen.nav.no/stillinger/stilling/" + c["uid"],
                    "source": "NAV", "posted": day(str(walk(e, "published") or "")),
                    "deadline": day(due) if re.match(r"\d{4}-", due) else "", "desc": desc})
    return out, inactive, True


# ---------------------------------------------------------------- Danemark : Jobindex
def scan_denmark(dump):
    out, seen = [], set()
    for q in DK_QUERIES:
        url = "https://www.jobindex.dk/jobsoegning?q=" + quote_plus(q)
        page = get(url)
        time.sleep(2.5)
        if not page:
            continue
        i = page.find("var Stash = ")
        if i < 0:
            continue
        try:
            stash, _ = json.JSONDecoder().raw_decode(page[i + len("var Stash = "):])
        except ValueError:
            continue
        res = walk(stash, "results") or []
        if dump and q == DK_QUERIES[0]:
            save_dump(dump, "dk-sample.json", [{k: v for k, v in r.items() if k != "geojson"} for r in res[:2]])
        n = 0
        for r in res:
            tid = str(r.get("tid") or "")
            if not tid or tid in seen or r.get("is_archived"):
                continue
            seen.add(tid)
            comp = (r.get("company") or {}).get("name") or r.get("companytext") or ""
            # seul le texte de présentation de l'annonce (les boutons du site sont en danois)
            paras = re.findall(r"<p[^>]*>(.*?)</p>", r.get("html") or "", re.S)
            snippet = mx.text(" ".join(paras))[:3000]
            out.append({"key": "dk:" + tid, "title": mx.text(r.get("headline") or ""), "company": mx.text(comp),
                        "place": r.get("area") or "Danemark", "cc": "DK",
                        "url": r.get("share_url") or f"https://www.jobindex.dk/vis-job/{tid}",
                        "source": "Jobindex", "posted": day(r.get("firstdate")), "deadline": day(r.get("lastdate")),
                        "desc": snippet})
            n += 1
        print(f"Danemark  {n:3} annonces · « {q} »")
    return out


# ---------------------------------------------------------------- listes
def save_dump(d, name, obj):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def key_of(o):
    url = o.get("url") or ""
    for prefix, rx in (("se:", r"platsbanken/annonser/(\d+)"), ("no:", r"stilling/([0-9a-f-]{36})"),
                       ("dk:", r"jobindex\.dk/(?:vis-job|c\?t=)/?([a-z]?\d+)")):
        m = re.search(rx, url)
        if m:
            return prefix + m.group(1)
    return o.get("key") or ""


def merge(nord, scraped, today, now_iso, sources, inactive):
    iso = today.isoformat()
    offers = [o for o in nord.get("offers", []) if isinstance(o, dict) and o.get("id")]
    by_key = {key_of(o): o for o in offers if key_of(o)}
    ids = {o["id"] for o in offers}
    added = 0
    for s in scraped:
        cur = by_key.get(s["key"]) or next((o for o in offers if o.get("cc") == s["cc"] and mx.same_offer(o, s)), None)
        if cur is not None:
            if s.get("deadline") and not cur.get("deadline"):
                cur["deadline"] = s["deadline"]
            continue
        est = estimate(s)
        if not est:
            continue
        fam, chances, why, lang, req = est
        month = (s.get("posted") or iso)[:7]
        base = "-".join(filter(None, [s["cc"].lower(), mx.slug(s["company"], 24), mx.slug(s["title"], 44), month]))
        oid, n = base, 2
        while oid in ids:
            oid, n = f"{base}-{n}", n + 1
        ids.add(oid)
        o = {"id": oid, "title": s["title"], "company": s["company"], "place": s["place"], "country": COUNTRY[s["cc"]],
             "cc": s["cc"], "family": fam, "chances": chances, "why": why, "url": s["url"], "source": s["source"],
             "posted": s.get("posted", ""), "first_seen": iso, "lang": lang, "auto": True}
        if req:
            o["lang_req"] = True
        if s.get("deadline"):
            o["deadline"] = s["deadline"]
        offers.append(o)
        by_key[s["key"]] = o
        added += 1
    before = len(offers)
    offers = [o for o in offers if key_of(o) not in inactive and mx.still_open(o, today, 75)
              and not mx.excluded_sector(o)]
    removed = before - len(offers)
    offers.sort(key=lambda o: (-int(o.get("chances") or 0), o.get("posted") or "", o.get("id")))
    nord.update({"updated": now_iso, "sources": sources, "offers": offers[:MAX_NORD]})
    return added, removed


def sync_selection(sel, nord, today, now_iso):
    """« Mes offres » : les offres nordiques à partir du seuil, avec les offres marocaines déjà retenues."""
    cur = {o["id"]: o for o in nord["offers"]}
    keep = []
    for o in sel.get("offers", []):
        if not isinstance(o, dict) or not o.get("id"):
            continue
        if o.get("cc") in COUNTRY:
            n = cur.get(o["id"])
            if not n or int(n.get("chances") or 0) < SEUIL_SELECTION:
                continue
            o.update(n)
        keep.append(o)
    have = {o["id"] for o in keep}
    for n in nord["offers"]:
        if n["id"] not in have and int(n.get("chances") or 0) >= SEUIL_SELECTION:
            keep.append(dict(n))
    keep = [o for o in keep if mx.still_open(o, today, 75) and not mx.excluded_sector(o)]
    keep.sort(key=lambda o: (-int(o.get("chances") or 0), o.get("posted") or ""))
    top = [o for o in keep if o.get("cc") in COUNTRY][:30]
    sel.update({"updated": now_iso, "offers": [o for o in keep if o.get("cc") not in COUNTRY or o in top]})


def main():
    dump = sys.argv[sys.argv.index("--dump") + 1] if "--dump" in sys.argv else None
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    today, now_iso = now.date(), now.strftime("%Y-%m-%dT%H:%M:%SZ")
    nord = mx.load(NORD)
    known = {key_of(o) for o in nord["offers"]}
    has_no = any(k.startswith("no:") for k in known)

    scraped, sources = [], []
    se = scan_sweden(dump)
    if se:
        sources.append("Platsbanken (Suède)")
    no, inactive, ok = scan_norway(dump, 3 if has_no else 12)
    if ok:
        sources.append("NAV (Norvège)")
    dk = scan_denmark(dump)
    if dk:
        sources.append("Jobindex (Danemark)")
    scraped = se + no + dk
    if not sources:
        print("Aucune source n'a pu être lue : listes inchangées.")
        return 1
    if dump:
        rated = [(estimate(s), s) for s in scraped]
        save_dump(dump, "rated.json", sorted(
            [{"cc": s["cc"], "chances": e[1], "title": s["title"], "company": s["company"], "why": e[2], "url": s["url"],
              "desc": s["desc"][:700]} for e, s in rated if e], key=lambda x: -x["chances"]))
    added, removed = merge(nord, scraped, today, now_iso, sources, inactive)
    counts = {}
    for o in nord["offers"]:
        counts[o["cc"]] = counts.get(o["cc"], 0) + 1
    nord["counts"] = counts
    sel = mx.load(OFFRES)
    sync_selection(sel, nord, today, now_iso)
    mx.save(NORD, nord)
    mx.save(OFFRES, sel)
    print(f"Pays nordiques : {len(nord['offers'])} offres ({added} nouvelles, {removed} retirées) {counts} · "
          f"Mes offres : {len(sel['offers'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
