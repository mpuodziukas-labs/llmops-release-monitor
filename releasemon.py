"""Simulated release pipeline for a versioned LLM app. Stdlib only, seeded, no network."""
import hashlib, json, math, random

PRICE_IN, PRICE_OUT = 0.003, 0.015  # synthetic dollars per 1k tokens
GATE_TOL = 0.01                      # candidate may trail baseline by this much offline
SLO = {"quality_drop": 0.03, "p95_ratio": 1.25, "cost_ratio": 1.30}
PSI_LIMIT = 0.20                     # common rule of thumb: >0.2 is a major shift
KAPPA_FLOOR, KAPPA_DROP = 0.70, 0.15


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


# ---------- registry and hash-chained audit log ----------
def entry_hash(seq, event, data, prev):
    return sha(json.dumps([seq, event, data, prev], sort_keys=True))


class Registry:
    def __init__(self, path):
        self.path = path
        self.state = {"versions": {}, "active": None, "audit": []}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.state, f, indent=1, sort_keys=True)

    @classmethod
    def load(cls, path):
        r = cls(path)
        with open(path) as f:
            r.state = json.load(f)
        return r

    def log(self, event, data):
        a = self.state["audit"]
        prev = a[-1]["hash"] if a else "0" * 64
        a.append({"seq": len(a), "event": event, "data": data, "prev": prev,
                  "hash": entry_hash(len(a), event, data, prev)})
        self.save()

    def register(self, vid, prompt, model, eval_scores):
        self.state["versions"][vid] = {"prompt_hash": sha(prompt)[:16], "model": model,
                                       "eval": eval_scores}
        self.log("register", {"version": vid, "model": model, "eval": eval_scores})

    def set_active(self, vid):
        self.state["active"] = vid
        self.log("promote", {"version": vid})


def verify_chain(entries):
    """Return (ok, index of first bad entry or None)."""
    prev = "0" * 64
    for i, e in enumerate(entries):
        if e["seq"] != i or e["prev"] != prev or e["hash"] != entry_hash(i, e["event"], e["data"], prev):
            return False, i
        prev = e["hash"]
    return True, None


# ---------- eval-gated promotion ----------
def gate(baseline_eval, cand_eval, tol=GATE_TOL):
    return cand_eval["quality"] >= baseline_eval["quality"] - tol


# ---------- labelled synthetic traffic ----------
def traffic(profile, n, seed):
    """profile: quality, lat_ms (median), tok_in, tok_out. Each request carries a label."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        ti = max(1, int(rng.gauss(profile["tok_in"], profile["tok_in"] * 0.15)))
        to = max(1, int(rng.gauss(profile["tok_out"], profile["tok_out"] * 0.20)))
        rows.append({"correct": rng.random() < profile["quality"],
                     "lat": rng.lognormvariate(math.log(profile["lat_ms"]), 0.25),
                     "tok_in": ti, "tok_out": to})
    return rows


def p95(xs):
    s = sorted(xs)
    return s[min(len(s) - 1, int(math.ceil(0.95 * len(s))) - 1)]


def metrics(rows):
    n = len(rows)
    cost = sum(r["tok_in"] * PRICE_IN + r["tok_out"] * PRICE_OUT for r in rows) / 1000
    return {"n": n, "quality": sum(r["correct"] for r in rows) / n,
            "p95_ms": p95([r["lat"] for r in rows]), "cost_per_1k": cost / n * 1000,
            "tokens_in": sum(r["tok_in"] for r in rows), "tokens_out": sum(r["tok_out"] for r in rows)}


def slo_breaches(base, canary):
    out = []
    if canary["quality"] < base["quality"] - SLO["quality_drop"]:
        out.append("quality")
    if canary["p95_ms"] > base["p95_ms"] * SLO["p95_ratio"]:
        out.append("latency")
    if canary["cost_per_1k"] > base["cost_per_1k"] * SLO["cost_ratio"]:
        out.append("cost")
    return out


def canary(reg, base_id, cand_id, profiles, split=0.10, n=20000, seed=7):
    """Route `split` of traffic to the candidate; roll back on any SLO breach."""
    rng = random.Random(seed)
    base_rows = traffic(profiles[base_id], n, seed + 1)
    cand_rows = traffic(profiles[cand_id], n, seed + 2)
    to_cand = [i for i in range(n) if rng.random() < split]
    keep = set(to_cand)
    b = metrics([r for i, r in enumerate(base_rows) if i not in keep])
    c = metrics([cand_rows[i] for i in to_cand])
    breaches = slo_breaches(b, c)
    if breaches:
        reg.log("rollback", {"version": cand_id, "breaches": breaches, "canary_n": c["n"]})
        return "rollback", breaches, b, c
    reg.set_active(cand_id)
    return "promoted", [], b, c


# ---------- drift ----------
def score_window(a, b, n, seed):
    rng = random.Random(seed)
    return [rng.betavariate(a, b) for _ in range(n)]


def psi(ref, cur, bins=10):
    """Population stability index with reference-quantile bins."""
    s = sorted(ref)
    edges = [s[int(len(s) * k / bins)] for k in range(1, bins)]

    def share(xs):
        c = [0] * bins
        for x in xs:
            c[sum(1 for e in edges if x > e)] += 1
        return [max(v / len(xs), 1e-4) for v in c]
    r, q = share(ref), share(cur)
    return sum((qi - ri) * math.log(qi / ri) for ri, qi in zip(r, q))


def human_labels(n, seed, prevalence=0.70):
    rng = random.Random(seed)
    return [1 if rng.random() < prevalence else 0 for _ in range(n)]


def judge_labels(human, seed, flip_pass=0.05, lenient=0.05):
    """flip_pass: P(judge fails a human pass). lenient: P(judge passes a human fail)."""
    rng = random.Random(seed)
    return [(0 if rng.random() < flip_pass else 1) if h else (1 if rng.random() < lenient else 0)
            for h in human]


def cohen_kappa(a, b):
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def judge_drifted(ref_kappa, cur_kappa):
    return cur_kappa < KAPPA_FLOOR or ref_kappa - cur_kappa > KAPPA_DROP
