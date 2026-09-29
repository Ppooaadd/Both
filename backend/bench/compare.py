"""Summarise benchmark result files side by side: python -m bench.compare a.json b.json"""

import json
import statistics as st
import sys

KEYS = [
    "mel_f",
    "beg_recall_grid",
    "int_recall_grid",
    "adv_recall",
    "adv_precision",
    "adv_onset_err_ms",
]

for path in sys.argv[1:]:
    with open(path) as fh:
        rows = json.load(fh)["rows"]
    groups = {
        "synthetic": [r for r in rows if not r["song"].startswith("vocadito")],
        "real vocal": [r for r in rows if r["song"].startswith("vocadito")],
    }
    for g, rs in groups.items():
        if not rs:
            continue
        vals = []
        for k in KEYS:
            xs = [r[k] for r in rs if k in r and r[k] == r[k]]
            vals.append(f"{k}={st.mean(xs):.3f}" if xs else f"{k}=-")
        print(f"{path.split('/')[-1]:10s} {g:10s} " + " ".join(vals))
