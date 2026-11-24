"""Markdown comparison of analysis.json files: python3 -I compare.py LABEL=RUN_DIR ..."""
import json, sys
from pathlib import Path

runs = [(a.split("=", 1)[0], json.load(open(Path(a.split("=", 1)[1]) / "analysis.json"))) for a in sys.argv[1:]]


def steady(d):
    phases = {e["phase"] for e in d["endpoints"]} - {"all"}
    ph = sorted(phases)[0] if phases else "all"
    return {e["name"]: e for e in d["endpoints"] if e["phase"] == ph}


names = sorted({n for _, d in runs for n in steady(d)})
print("| 接口 | " + " | ".join(f"{l} n / p50 / p95 / p99 ms / 5xx" for l, _ in runs) + " |")
print("|---" * (len(runs) + 1) + "|")
for n in names:
    cells = []
    for _, d in runs:
        e = steady(d).get(n)
        cells.append("—" if not e else f"{e['n']} / {e['p50']} / {e['p95']} / {e['p99']} / {e['5xx']}" + (f" (429×{e['429']})" if e.get("429") else ""))
    print(f"| {n} | " + " | ".join(cells) + " |")
print()
print("| 汇总 | " + " | ".join(l for l, _ in runs) + " |")
print("|---" * (len(runs) + 1) + "|")
def tot(d, gen=None):
    es = [e for e in steady(d).values() if gen is None or e["gen"] == gen]
    n = sum(e["n"] for e in es); s5 = sum(e["5xx"] for e in es)
    worst = max((e["p95"] for e in es), default=0)
    return n, s5, worst
rows = [("请求数（稳态 5 分钟）", lambda d: tot(d)[0]),
        ("5xx 比例", lambda d: f"{100*tot(d)[1]/max(tot(d)[0],1):.2f}%"),
        ("非生成接口中最差 p95 (ms)", lambda d: tot(d, 'no')[2]),
        ("连接池超时（日志）", lambda d: sum(v.get("pool_timeout", 0) for v in d["logs"].values())),
        ("worker 子进程被 SIGKILL", lambda d: sum(v.get("worker_lost_sig9", 0) for v in d["logs"].values())),
        ("IntegrityError（重复投递）", lambda d: sum(v.get("integrity_error", 0) for v in d["logs"].values())),
        ("队列峰值 default/detail/replica", lambda d: "/".join(str(d["queues"].get(k, "-")) for k in ("default", "domestic_detail_v431", "one_click_replica"))),
        ("api 内存峰值/上限 MiB", lambda d: f"{d['containers'].get('api',{}).get('mem_mib')}/{d['containers'].get('api',{}).get('limit_mib')}"),
        ("api CPU 峰值 %", lambda d: d['containers'].get('api',{}).get('cpu%')),
        ("detail-worker 内存峰值/上限", lambda d: f"{d['containers'].get('detail-worker',{}).get('mem_mib')}/{d['containers'].get('detail-worker',{}).get('limit_mib')}"),
        ("worker 内存峰值/上限", lambda d: f"{d['containers'].get('worker',{}).get('mem_mib')}/{d['containers'].get('worker',{}).get('limit_mib')}"),
        ("postgres CPU 峰值 %", lambda d: d['containers'].get('postgres',{}).get('cpu%')),
        ("任务结果", lambda d: ", ".join(f"{k}={v}" for k, v in d["outcomes"].items())),
        ("任务耗时 p50/p95 s", lambda d: ", ".join(f"{k} {v['p50']}/{v['p95']}" for k, v in d["jobs"].items()))]
for label, f in rows:
    print(f"| {label} | " + " | ".join(str(f(d)) for _, d in runs) + " |")
