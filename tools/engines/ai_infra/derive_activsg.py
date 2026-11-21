#!/usr/bin/env python3
"""Derive line and transformer rating distributions from the Texas A&M ACTIVSg
synthetic grids, as shipped in MATPOWER (CC BY 4.0).

The cases are entirely synthetic and bear no relation to the real grid at their
location. RuralSim uses them only as *parameter distributions by voltage class*
(rateA percentiles, X/R ratio), never as topology. Writes
params/activsg_distributions.json. Run once; the output is committed.

    python3 tools/engines/ai_infra/derive_activsg.py case_ACTIVSg70k.m case_ACTIVSg10k.m

Sources (sha256 of the files used for the committed output):
  https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case_ACTIVSg70k.m
    5df8c785c75f174555d307e05ae279c51f888ebbd85c469dab3265baf3e96293
  https://raw.githubusercontent.com/MATPOWER/matpower/master/data/case_ACTIVSg10k.m
    ead10b25fecc4dcc02f88bacdfb3526fe8b8985b81f7e539c95abddb32575590
Cite: Birchfield et al., IEEE Trans. Power Systems 32(4) 3258-3265, 2017,
doi:10.1109/TPWRS.2016.2616385.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "params" / "activsg_distributions.json"


def load(fn):
    t = Path(fn).read_text()

    def block(name):
        m = re.search(r"mpc\." + name + r"\s*=\s*\[(.*?)\];", t, re.S)
        rows = [r.strip().rstrip(";") for r in m.group(1).strip().split("\n")
                if r.strip() and not r.strip().startswith("%")]
        return np.array([[float(x) for x in r.split()] for r in rows])

    return block("bus"), block("branch")


def main(files):
    out = {}
    for fn in files:
        bus, br = load(fn)
        kv = dict(zip(bus[:, 0].astype(int), bus[:, 9]))
        df = pd.DataFrame({"f": br[:, 0].astype(int), "t": br[:, 1].astype(int), "r": br[:, 2],
                           "x": br[:, 3], "rateA": br[:, 5], "ratio": br[:, 8], "status": br[:, 10]})
        df["kvf"] = df.f.map(kv)
        df["kvt"] = df.t.map(kv)
        lines = df[(df.kvf == df.kvt) & (df.ratio == 0) & (df.status == 1) & (df.rateA > 0)]
        tx = df[(df.kvf != df.kvt) & (df.status == 1) & (df.rateA > 0)]
        res = {}
        for v, g in lines.groupby("kvf"):
            if len(g) < 30:
                continue
            res[int(v)] = {
                "n": int(len(g)),
                "rateA_MVA_p10_25_50_75_90": g.rateA.quantile([.1, .25, .5, .75, .9]).round(0).tolist(),
                "x_over_r_p10_50_90": (g.x / g.r.replace(0, np.nan)).quantile([.1, .5, .9]).round(2).tolist(),
            }
        tr = {}
        tx = tx.assign(hi=tx[["kvf", "kvt"]].max(axis=1), lo=tx[["kvf", "kvt"]].min(axis=1))
        for (a, b), g in tx.groupby(["hi", "lo"]):
            if len(g) < 30 or b < 30:
                continue
            tr[f"{int(a)}/{int(b)}"] = {"n": int(len(g)),
                                        "rateA_MVA_p10_50_90": g.rateA.quantile([.1, .5, .9]).round(0).tolist()}
        out[Path(fn).stem] = {"lines": res, "transformers": tr}
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main(sys.argv[1:])
