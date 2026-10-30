import re, time, urllib.request, urllib.error
from urllib.parse import quote
UA = "Mozilla/5.0 (compatible; RadarEmploi/1.0; +https://github.com/aminebenkhadra-dotcom/Job-search)"
out = []
for i, u in enumerate(l.strip() for l in open("probe3/urls.txt") if l.strip()):
    u = quote(u, safe=":/?&=%#+,;@!$'()*[]~")
    name = "probe3/%02d.html" % i
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Language": "fr"}), timeout=30) as r:
            body = r.read(); status = r.status
    except urllib.error.HTTPError as e:
        body, status = b"", e.code
    except Exception as e:
        body, status = str(e).encode(), 0
    open(name, "wb").write(body)
    out.append(f"{i:02d}\t{status}\t{len(body)}\t{u}")
    print(out[-1], flush=True)
    time.sleep(2)
open("probe3/status.txt", "w").write("\n".join(out) + "\n")
