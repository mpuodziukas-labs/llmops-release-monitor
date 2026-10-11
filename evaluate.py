"""Run planted failures and clean controls through the release pipeline."""
import os, sys, tempfile
import releasemon as rm

PROFILES = {
    "v1": {"quality": 0.90, "lat_ms": 800, "tok_in": 600, "tok_out": 200},
    "v2": {"quality": 0.91, "lat_ms": 820, "tok_in": 600, "tok_out": 205},          # clean upgrade
    "v3-regressed": {"quality": 0.80, "lat_ms": 800, "tok_in": 600, "tok_out": 200},
    "v4-slow": {"quality": 0.91, "lat_ms": 1300, "tok_in": 600, "tok_out": 200},
    "v5-costly": {"quality": 0.91, "lat_ms": 800, "tok_in": 600, "tok_out": 600},
}
OFFLINE = {k: {"quality": v["quality"]} for k, v in PROFILES.items()}


def fresh():
    d = tempfile.mkdtemp()
    reg = rm.Registry(os.path.join(d, "registry.json"))
    for vid in PROFILES:
        reg.register(vid, "prompt text of " + vid, "model-" + vid[:2], OFFLINE[vid])
    reg.set_active("v1")
    return reg


def release(cand):
    reg = fresh()
    if not rm.gate(OFFLINE["v1"], OFFLINE[cand]):
        reg.log("blocked", {"version": cand})
        return "blocked"
    return rm.canary(reg, "v1", cand, PROFILES)[0]


def canary_reason(cand):
    reg = fresh()
    res = rm.canary(reg, "v1", cand, PROFILES)
    return res[0] + (":" + ",".join(res[1]) if res[1] else "")


def drift(a, b):
    ref = rm.score_window(8, 2, 5000, 1)
    cur = rm.score_window(a, b, 5000, 2)
    return "alert" if rm.psi(ref, cur) > rm.PSI_LIMIT else "stable"


def judge(flip, lenient):
    h_ref = rm.human_labels(600, 3)
    k_ref = rm.cohen_kappa(h_ref, rm.judge_labels(h_ref, 4))
    h = rm.human_labels(600, 5)
    k = rm.cohen_kappa(h, rm.judge_labels(h, 6, flip, lenient))
    return "alert" if rm.judge_drifted(k_ref, k) else "stable"


def audit(tamper):
    reg = fresh()
    reg.log("canary", {"version": "v2", "quality": 0.91})
    if tamper:
        e = reg.state["audit"][2]
        e["data"] = dict(e["data"], eval={"quality": 0.99})  # rewrite history, keep old hash
        reg.save()
    ok, _ = rm.verify_chain(rm.Registry.load(reg.path).state["audit"])
    return "tampered" if not ok else "intact"


# (case, kind, expected, thunk)
CASES = [
    ("regressed version blocked", "planted", "blocked", lambda: release("v3-regressed")),
    ("latency regression rolls back", "planted", "rollback:latency", lambda: canary_reason("v4-slow")),
    ("cost blow-up rolls back", "planted", "rollback:cost", lambda: canary_reason("v5-costly")),
    ("injected drift window", "planted", "alert", lambda: drift(5, 3)),
    ("judge drifts from human labels", "planted", "alert", lambda: judge(0.05, 0.45)),
    ("tampered audit entry", "planted", "tampered", lambda: audit(True)),
    ("clean upgrade promoted", "control", "promoted", lambda: release("v2")),
    ("stable production window", "control", "stable", lambda: drift(8, 2)),
    ("judge agrees with humans", "control", "stable", lambda: judge(0.05, 0.05)),
    ("untouched audit log", "control", "intact", lambda: audit(False)),
]


def run():
    rows = []
    for name, kind, exp, thunk in CASES:
        got = thunk()
        rows.append((name, kind, exp, got, got == exp))
    return rows


def render(rows):
    w = max(len(r[0]) for r in rows)
    lines = [f"{'case'.ljust(w)}  kind     expected          observed          result"]
    for name, kind, exp, got, ok in rows:
        lines.append(f"{name.ljust(w)}  {kind.ljust(7)}  {exp.ljust(16)}  {got.ljust(16)}  {'OK' if ok else 'MISS'}")
    pl = [r for r in rows if r[1] == "planted"]
    ct = [r for r in rows if r[1] == "control"]
    c = sum(r[4] for r in pl)
    p = sum(r[4] for r in ct)
    lines.append(f"{c}/{len(pl)} planted failures caught, {p}/{len(ct)} controls passed")
    return "\n".join(lines), c == len(pl) and p == len(ct)


def main():
    text, ok = render(run())
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
