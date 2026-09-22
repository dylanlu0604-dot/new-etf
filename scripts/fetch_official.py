#!/usr/bin/env python3
"""Fetch each issuer page directly and retain evidence around risk/name fields."""
import html, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests, urllib3
from bs4 import BeautifulSoup
urllib3.disable_warnings()

ROOT = Path(__file__).resolve().parents[1]
records = json.loads((ROOT / "artifacts/moneydj_sources.json").read_text())["records"]
OUT = ROOT / "artifacts/official_sources.json"

def clean(raw):
    raw = raw or ""
    for _ in range(4):
        new = html.unescape(raw)
        if new == raw: break
        raw = new
    soup = BeautifulSoup(raw, "html.parser")
    return " ".join(soup.stripped_strings)

def fetch(rec):
    u = rec.get("official_url", "")
    out = {"ticker": rec["ticker"], "official_url": u, "status": "error"}
    if not u:
        out["error"] = "no official url"
        return out
    try:
        r = requests.get(u, headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36"}, timeout=35, verify=False)
        raw = r.content.decode("utf-8", "replace")
        text = clean(raw)
        snippets = []
        for m in re.finditer(r"(?:風險.{0,240}?RR\s*[1-5]|RR\s*[1-5].{0,240}?風險)", text, re.I):
            snippets.append(text[max(0, m.start()-220):m.end()+220])
        # Direct assignments in embedded data, useful for issuer pages.
        direct = []
        for m in re.finditer(r"(?:風險(?:報酬|收益)?等級|風險收益等級|risk(?:[-_ ]?level|[-_ ]?return[-_ ]?rank)).{0,160}?RR\s*([1-5])", text, re.I | re.S):
            direct.append("RR" + m.group(1))
        for m in re.finditer(r"RR\s*([1-5])", text, re.I):
            before = text[max(0, m.start()-180):m.start()]
            if re.search(r"風險(?:報酬|收益)?等級|風險收益等級|risk", before, re.I):
                direct.append("RR" + m.group(1))
        # Many issuer pages contain several product cards. Match the rank
        # closest to this ticker, instead of taking a generic RR disclaimer.
        near = []
        for tm in re.finditer(re.escape(rec["ticker"]), text, re.I):
            start, end = max(0, tm.start()-2500), min(len(text), tm.end()+2500)
            window = text[start:end]
            for rm in re.finditer(r"RR\s*([1-5])", window, re.I):
                near.append({"rank": "RR" + rm.group(1), "distance": abs((start + rm.start()) - tm.start())})
        near.sort(key=lambda x: x["distance"])
        # Keep only targeted evidence, plus enough page text to inspect the title/strategy.
        title = BeautifulSoup(raw, "html.parser").title
        out.update({"status": "ok", "http_status": r.status_code, "content_length": len(raw),
                    "title": title.get_text(" ", strip=True) if title else "",
                    "ranks": sorted(set(re.findall(r"\bRR\s*[1-5]\b", text, re.I))),
                    "direct_ranks": sorted(set(direct)), "near_ranks": near[:12], "risk_snippets": snippets[:8],
                    "name_hits": [text[max(0,m.start()-120):m.end()+120] for m in list(re.finditer(re.escape(rec.get("name", "")), text))[:3]] if rec.get("name") else []})
        return out
    except Exception as e:
        out["error"] = repr(e)
        return out

def main():
    out = [None] * len(records)
    with ThreadPoolExecutor(max_workers=12) as pool:
        fs = {pool.submit(fetch, r): i for i, r in enumerate(records)}
        for n, f in enumerate(as_completed(fs), 1):
            out[fs[f]] = f.result()
            if n % 25 == 0 or n == len(records): print(f"official {n}/{len(records)}", file=sys.stderr)
    OUT.write_text(json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "records": out}, ensure_ascii=False, indent=2) + "\n")
    ok = sum(x.get("status") == "ok" for x in out)
    direct = sum(bool(x.get("direct_ranks")) for x in out)
    print(json.dumps({"count": len(out), "ok": ok, "errors": len(out)-ok, "direct_risk": direct, "output": str(OUT)}, ensure_ascii=False))

if __name__ == "__main__": main()
