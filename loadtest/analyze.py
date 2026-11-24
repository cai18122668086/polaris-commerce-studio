"""Summarise one load-test run directory produced by run.sh (stdlib only).

python3 -I analyze.py RUN_DIR [--json]
"""
import csv, gzip, json, re, sys
from collections import defaultdict
from pathlib import Path

run = Path(sys.argv[1])
_meta = (run / "meta.txt").read_text() if (run / "meta.txt").exists() else ""
_m = re.search(r"stages=p(\d+)", _meta)
if _m:  # 单阶段运行：30 秒爬坡 + 5 分钟稳态
    PHASES = [(_m.group(1) + "VU", 30, 330)]
else:
    PHASES = [("10VU", 30, 330), ("25VU", 360, 660), ("50VU", 690, 990)]  # 稳态窗口（秒，相对开始）


def pct(v, q):
    if not v:
        return None
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


dur = defaultdict(list)            # (phase, name) -> [ms]
stat = defaultdict(lambda: [0, 0, 0, 0, 0])  # (phase, name) -> [n, unexpected, 5xx, status0]
jobs = defaultdict(list)
outcomes = defaultdict(int)
checks = defaultdict(lambda: [0, 0])
t0 = None
rows = []
with gzip.open(run / "k6.csv.gz", "rt", newline="") as f:
    for r in csv.DictReader(f):
        rows.append(r)
        if t0 is None:
            t0 = int(r["timestamp"])
for r in rows:
    m, ts, val = r["metric_name"], int(r["timestamp"]) - t0, float(r["metric_value"] or 0)
    extra = dict(kv.split("=", 1) for kv in (r.get("extra_tags") or "").split("&") if "=" in kv)
    if m == "http_req_duration":
        name = r["name"]
        phases = ["all"] + [p for p, a, b in PHASES if a <= ts < b]
        code = int(r["status"] or 0)
        for p in phases:
            k = (p, name, extra.get("gen", "no"))
            dur[k].append(val)
            s = stat[k]
            s[0] += 1
            s[1] += r["expected_response"] != "true"
            s[2] += code >= 500
            s[3] += code == 0
            s[4] += code == 429
    elif m == "job_e2e_seconds":
        jobs[extra.get("kind", "?")].append(val)
    elif m == "job_outcome":
        outcomes[(extra.get("kind", "?"), extra.get("result", "?"))] += int(val)
    elif m == "checks":
        checks[r["check"]][0] += 1
        checks[r["check"]][1] += val == 0

out = {"endpoints": [], "jobs": {}, "outcomes": {}, "checks": {}, "containers": {}, "queues": {}, "logs": {}}
for (p, name, gen), v in sorted(dur.items()):
    n, bad, s5, s0, s429 = stat[(p, name, gen)]
    out["endpoints"].append({"phase": p, "name": name, "gen": gen, "n": n, "p50": round(pct(v, .5)), "p95": round(pct(v, .95)),
                             "p99": round(pct(v, .99)), "max": round(max(v)), "err%": round(100 * bad / n, 2), "5xx": s5, "neterr": s0, "429": s429})
for k, v in jobs.items():
    out["jobs"][k] = {"n": len(v), "p50": round(pct(v, .5), 1), "p95": round(pct(v, .95), 1), "max": round(max(v), 1)}
out["outcomes"] = {f"{k}:{s}": n for (k, s), n in sorted(outcomes.items())}
out["checks"] = {k: {"n": n, "fail": f} for k, (n, f) in checks.items()}

# 容器资源峰值
def mib(s):
    num, unit = re.match(r"([\d.]+)\s*([KMG]i?B|B)", s).groups()
    return float(num) * {"B": 1 / 2**20, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1024, "MB": 1, "GB": 1024}[unit]
peak = {}
if (run / "stats.tsv").exists():
    for line in open(run / "stats.tsv"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            continue
        _, name, cpu, mem = parts[:4]
        used, limit = [x.strip() for x in mem.split("/")]
        c = peak.setdefault(name.replace("polaris-loadstg-", "").rsplit("-1", 1)[0], {"cpu%": 0, "mem_mib": 0, "limit_mib": round(mib(limit))})
        c["cpu%"] = max(c["cpu%"], float(cpu.rstrip("%") or 0))
        c["mem_mib"] = max(c["mem_mib"], round(mib(used)))
out["containers"] = peak
qmax = defaultdict(int)
if (run / "queues.tsv").exists():
    for line in open(run / "queues.tsv"):
        for kv in line.split()[1:]:
            k, _, v = kv.partition("=")
            if v.isdigit():
                qmax[k] = max(qmax[k], int(v))
out["queues"] = dict(qmax)
pats = {
    "pool_timeout": r"QueuePool limit|TimeoutError.*pool|pool.*timed out|PoolTimeout",
    "db_too_many_conn": r"too many clients|remaining connection slots",
    "http_5xx_logged": r'" 5\d\d ',
    "traceback": r"Traceback \(most recent call last\)",
    "worker_lost_sig9": r"WorkerLostError|signal 9|SIGKILL",
    "oom_text": r"MemoryError|Out of memory|oom",
    "celery_timelimit": r"TimeLimitExceeded|SoftTimeLimitExceeded",
    "integrity_error": r"IntegrityError",
}
for logf in sorted((run / "logs").glob("*.log")):
    txt = logf.read_text(errors="replace")
    hits = {k: len(re.findall(p, txt)) for k, p in pats.items()}
    hits = {k: v for k, v in hits.items() if v}
    if hits:
        out["logs"][logf.stem.replace("polaris-loadstg-", "")] = hits

if "--json" in sys.argv:
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit()
json.dump(out, open(run / "analysis.json", "w"), ensure_ascii=False, indent=1)
print(f"run {run.name}")
for ph in ["all"] + [p for p, *_ in PHASES]:
    eps = [e for e in out["endpoints"] if e["phase"] == ph]
    if not eps:
        continue
    print(f"\n== {ph}  (gen=yes 为生成类提交接口)")
    print(f"{'endpoint':42} {'gen':3} {'n':>6} {'p50':>6} {'p95':>6} {'p99':>6} {'max':>6} {'err%':>6} {'5xx':>4} {'net0':>4} {'429':>4}")
    for e in eps:
        print(f"{e['name'][:42]:42} {e['gen']:3} {e['n']:6} {e['p50']:6} {e['p95']:6} {e['p99']:6} {e['max']:6} {e['err%']:6} {e['5xx']:4} {e['neterr']:4} {e['429']:4}")
    tot = sum(e["n"] for e in eps); s5 = sum(e["5xx"] for e in eps); bad = sum(round(e["err%"] * e["n"] / 100) for e in eps)
    s0 = sum(e["neterr"] for e in eps)
    print(f"status0 (k6 timeout/abort) {s0}; total {tot} req, unexpected {bad} ({100*bad/max(tot,1):.2f}%), 5xx {s5} ({100*s5/max(tot,1):.2f}%)")
print("\njobs (seconds, submit->terminal):", json.dumps(out["jobs"], ensure_ascii=False))
print("outcomes:", json.dumps(out["outcomes"], ensure_ascii=False))
print("checks:", json.dumps(out["checks"], ensure_ascii=False))
print("queue max depth:", json.dumps(out["queues"]))
print("container peaks:", json.dumps(out["containers"]))
print("log signals:", json.dumps(out["logs"], ensure_ascii=False))
