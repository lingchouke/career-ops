import json
from collections import Counter
from pathlib import Path
from math import floor

def score(report,resume):
    config=json.loads(Path(__file__).with_name("scoring.json").read_text(encoding="utf8"))
    counts={"must":Counter(),"nice":Counter()}
    caps={}
    earned=possible=0
    for row in report["requirements"]:
        status=effective_status(row,resume)
        kind=row["importance"]
        counts[kind][status]+=1
        weight=config["weights"][kind]
        possible+=weight
        earned+=weight*config["credit"][status]
        if row["hard_gate"] and status!="met":
            caps["硬性门槛"+("未满足" if status=="missing" else "部分满足")]=config["caps"][status]
    if report["direction_mismatch"]:
        caps["岗位方向不符"]=config["caps"]["direction_mismatch"]
    base=floor(100*earned/possible+0.5) if possible else 0
    value=min([base,*caps.values()])
    band=next(label for limit,label in [(85,"高度匹配"),(70,"较匹配"),(50,"有差距"),(30,"差距较大"),(0,"不匹配")] if value>=limit)
    return value,band,counts,caps

def effective_status(row,resume):
    quote=row["evidence"]
    return row["status"] if quote.strip() and quote in resume else "missing"
