import itertools, time, json, urllib.request

BASE = "https://www.stortinget.no/globalassets/pdf/verv-og-okonomiske-interesser"
USC = "https://www.stortinget.no/globalassets/pdf/verv_oekonomiske_interesser_register"
UA = "registrum-archive-audit/1.0 (+sondreskarsten@gmail.com)"
FULL = {1:'januar',2:'februar',3:'mars',4:'april',5:'mai',6:'juni',7:'juli',8:'august',9:'september',10:'oktober',11:'november',12:'desember'}
ABBR = {1:['jan'],2:['feb'],3:['mar'],4:['apr'],5:[],6:['jun'],7:['jul'],8:['aug'],9:['sep','sept'],10:['okt'],11:['nov'],12:['des']}

def periods(y, m):
    a = f"{y-1}-{y}" if m <= 9 else f"{y}-{y+1}"
    b = f"{y}-{y+1}" if m <= 9 else f"{y-1}-{y}"
    return [a, b]

def month_tokens(m, dots=True):
    toks = [FULL[m]] + ABBR[m]
    out = set(toks)
    if dots:
        out |= {t + '.' for t in toks}
    return sorted(out)

def day_tokens(d, extended=False):
    out = {str(d), f"{d}."}
    if extended:
        out |= {f"{d:02d}", f"{d:02d}."}
    return sorted(out)

def dated_candidates(y, m, d, extended=False):
    prefixes = ['pr-', 'pr.-'] + (['pr..-'] if extended else [])
    for per, pre, day, mo in itertools.product(
        periods(y, m), prefixes, day_tokens(d, extended), month_tokens(m)
    ):
        yield f"{BASE}/arkiv_{per}/{pre}{day}-{mo}-{y}.pdf"

def code_candidates(y, m, d):
    codes = [f"{y}-{d:02d}{m:02d}", f"{y}-{m:02d}{d:02d}", f"{y}-{d:02d}-{m:02d}", f"{d:02d}{m:02d}-{y}"]
    for c in codes:
        yield f"{USC}/{c}.pdf"
        for per in periods(y, m):
            yield f"{BASE}/arkiv_{per}/{c}.pdf"

def head(url, timeout=15):
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': UA})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0

class Limiter:
    def __init__(self, rate):
        self.rate = rate
        self.floor = 4.0
        self.last = 0.0
    def wait(self):
        gap = 1.0 / self.rate
        now = time.monotonic()
        if now - self.last < gap:
            time.sleep(gap - (now - self.last))
        self.last = time.monotonic()
    def penalize(self):
        self.rate = max(self.floor, self.rate * 0.5)
    def reward(self):
        self.rate = min(self.rate + 0.02, 24.0)
