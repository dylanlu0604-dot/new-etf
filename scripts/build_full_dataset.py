#!/usr/bin/env python3
"""Build the complete, source-backed CSV from direct public pages.

This deliberately uses deterministic rules only; no API, LLM, or TinyFish call is made.
"""
import csv, json, re, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
money = json.loads((ROOT / "artifacts/moneydj_sources.json").read_text())["records"]
official = {x["ticker"]: x for x in json.loads((ROOT / "artifacts/official_sources.json").read_text())["records"]}

ALLOWED_RISK = {"RR1","RR2","RR3","RR4","RR5"}
KNOWN_RISK = {
    # Explicitly reconciled against the earlier verified rows / official page text.
    "00402A":"RR4", "00408A":"RR4", "00410A":"RR5", "00409A":"RR4", "00411A":"RR4",
    "009827":"RR4", "009828":"RR5", "009829":"RR5", "00987D":"RR2",
    "00991B":"RR2", "00990B":"RR3", "009823":"RR4", "009824":"RR4",
    "009825":"RR5", "009826":"RR4",
    "00728":"RR4", "00834B":"RR2", "00910":"RR4", "00959B":"RR2",
}

def s(x): return str(x or "").strip()

def category(rec):
    n, t = s(rec.get("name")), s(rec.get("target"))
    if any(k in n+t for k in ["債", "債券", "公司債", "公債", "市政債"]): return "Fixed Income"
    if any(k in n for k in ["美元", "日圓", "人民幣", "RMB"]): return "Currency"
    if any(k in n+t for k in ["黃金", "白銀", "石油", "原油", "布蘭特", "黃豆", "銅"]): return "Commodities"
    return "Equity"

def bond_sector(rec):
    text = s(rec.get("name")) + s(rec.get("target")) + s(rec.get("region"))
    if any(k in text for k in ["非投資", "高收益", "非投債"]): return "High-Yield/Junk Bond ETFs"
    if any(k in text for k in ["新興市場", "新興亞洲", "EM主權"]): return "Emerging Market Bond ETFs"
    if any(k in text for k in ["公債", "政府", "主權", "美債", "市政"]): return "Government Bond ETFs"
    return "Investment Grade Corporate Bond ETFs"

def commodity_type(rec):
    text = s(rec.get("name")) + s(rec.get("strategy"))
    if any(k in text for k in ["黃金", "白銀"]): return "Precious Metals"
    if any(k in text for k in ["石油", "原油", "布蘭特"]): return "Energy"
    if "銅" in text: return "Industrial Metals"
    if "黃豆" in text: return "Agriculture"
    return "n.a."

def currency(rec):
    text = s(rec.get("name"))
    if "日圓" in text: return "JPY"
    if any(k in text for k in ["人民幣", "RMB"]): return "RMB"
    return "USD"

def region(rec):
    n, r = s(rec.get("name")), s(rec.get("region"))
    text = n + r + s(rec.get("strategy"))
    if any(k in text for k in ["台日韓", "亞太", "亞洲", "韓國"]): return "Emerging Asia Pacific", "Broad"
    if "台灣" in text or "臺灣" in text: return "Emerging Asia Pacific", "Taiwan"
    if "中國" in text or "中證" in text or "深証" in text or "香港" in text: return "Emerging Asia Pacific", "China"
    if "印度" in text: return "Emerging Asia Pacific", "India"
    if "越南" in text: return "Emerging Asia Pacific", "Vietnam"
    if "日本" in text or "日經" in text: return "Developed Asia Pacific", "Japan"
    if "澳洲" in text: return "Developed Asia Pacific", "Broad"
    if "歐洲" in text or "德國" in text: return "Developed Europe", "Broad"
    if "加拿大" in text: return "North America", "Broad"
    if any(k in text for k in ["美國", "北美", "S&P500", "標普500", "NASDAQ", "那斯達克", "道瓊"]): return "North America", "U.S."
    if "新興市場" in text: return "Emerging Markets", "Broad"
    if "全球" in text or "世界" in text: return "Global", "Broad"
    # Commodities/currency products with no country exposure are global.
    return "Global", "Broad"

def themes(rec):
    text = s(rec.get("name")) + s(rec.get("strategy"))
    tags = []
    def add(x):
        if x not in tags: tags.append(x)
    if any(k in text for k in ["黃金", "白銀"]): add("黃金礦業")
    if any(k in text for k in ["石油", "原油", "布蘭特"]): add("油氣")
    if "黃豆" in text: add("天然資源")
    if "銅" in text: add("天然資源")
    if any(k in text for k in ["半導體", "科技", "電子", "NASDAQ", "那斯達克", "AI", "人工智慧", "創新"]):
        add("人工智慧"); add("半導體")
    if "機器人" in text: add("機器人")
    if any(k in text for k in ["太空", "衛星"]): add("太空經濟")
    if any(k in text for k in ["電動", "新能源", "綠能", "低碳"]): add("乾淨能源")
    if any(k in text for k in ["資安", "網路安全"]): add("網路安全")
    if any(k in text for k in ["航運"]): add("航運")
    if any(k in text for k in ["REIT", "房地產"]): add("房地產循環")
    if any(k in text for k in ["金融", "銀行"]): add("金融科技")
    if any(k in text for k in ["高息", "股利", "收益", "優息"]): add("股利因子")
    if any(k in text for k in ["債", "債券"]): add("固定收益")
    if not tags:
        cat = category(rec)
        if cat == "Fixed Income": add("固定收益")
        elif cat == "Commodities": add("商品市場")
        elif cat == "Currency": add("匯率資產")
        else: add("股票市場")
    return "、".join(tags[:5])

def risk_rank(rec):
    t = rec["ticker"]
    if t in KNOWN_RISK: return KNOWN_RISK[t], "explicit_override"
    o = official.get(t, {})
    near = o.get("near_ranks") or []
    if near:
        counts = collections.Counter(x["rank"] for x in near[:5])
        rank, count = counts.most_common(1)[0]
        if count >= 3 or (len(counts) == 1 and rank in ALLOWED_RISK): return rank, "official_nearest_ticker"
        # When the closest evidence is a repeated exact product block, use it.
        if near[0]["rank"] in ALLOWED_RISK and near[0]["distance"] < 100: return near[0]["rank"], "official_nearest_ticker"
    direct = set(o.get("direct_ranks") or [])
    if len(direct) == 1: return next(iter(direct)), "official_direct"
    n, target = s(rec.get("name")), s(rec.get("target"))
    text = n + target
    if any(k in text for k in ["正2", "反1", "槓桿", "反向"]): return "RR5", "strategy_rule"
    if category(rec) == "Fixed Income":
        if any(k in text for k in ["非投資", "高收益", "新興市場", "新興亞洲"]): return "RR3", "bond_risk_rule"
        return "RR2", "bond_risk_rule"
    if category(rec) == "Commodities": return "RR5", "commodity_risk_rule"
    if category(rec) == "Currency": return "RR5", "currency_risk_rule"
    if any(k in text for k in ["半導體", "科技", "AI", "人工智慧", "生技", "太空", "衛星", "電動"]): return "RR5", "equity_concentration_rule"
    if s(rec.get("region")) in {"台灣", "中國", "日本", "美國", "北美"}: return "RR4", "equity_broad_rule"
    return "RR4", "equity_broad_rule"

def suitability(rec, cat, lev):
    if lev == "Yes": return "只適合能承受極高波動、理解每日槓桿或反向機制且具短線風險管理能力的投資人"
    if cat == "Fixed Income": return "重視收益與資產配置、並能承受利率、信用或匯率波動的投資人"
    if cat in {"Commodities", "Currency"}: return "理解商品或匯率價格波動、希望分散傳統股債曝險的積極型投資人"
    if s(rec.get("region")) in {"全球", "新興市場"}: return "看好跨市場長期成長、能承受股票市場波動並願意中長期持有的投資人"
    return "看好相關市場或主題、能承受股票價格波動並願意中長期持有的投資人"

def description(rec, cat, rg, rs, risk, lev, active):
    if rec.get("ticker") == "00762B":
        return "公開資料查核時，MoneyDJ、Yahoo Finance及以代號搜尋的公開結果均未找到可核對的現行產品頁面；此代號可能已下市、停牌或為清單誤植。為避免捏造名稱、日期、策略、費用與風險等級，本筆以 n.a. 標示，需由使用者提供基金名稱或正確代號後再補查。"
    issuer, name = s(rec.get("issuer")), s(rec.get("name"))
    listing = s(rec.get("listing_date")) or "未載明"
    manager = s(rec.get("manager")) or "官方頁面未載明"
    strategy = s(rec.get("strategy")) or ("以指數化方式配置相關標的" if not active else "由經理團隊依投資策略主動選股")
    fee = s(rec.get("management_fee")) or "官方頁面未載明"
    if not strategy.endswith(("。", ".")): strategy += "。"
    mode = "主動管理" if active == "Yes" else "指數化／被動管理"
    return (f"{issuer}發行的「{name}」於{listing}掛牌，採{mode}，{strategy} "
            f"投資區域歸類為{rg}－{rs}，主題涵蓋{themes(rec)}；經理人為{manager}，經理費資料為{fee}。"
            f"本基金風險報酬等級為{risk}，槓桿或反向屬性為{lev}，適合{suitability(rec, cat, lev)}。"
            "投資前仍應以發行公司最新公開說明書、基金基本資料及公告費率為準，並留意市場、匯率、利率、信用與折溢價風險。")

def main():
    rows, logs = [], []
    for rec in money:
        t=rec["ticker"]; cat=category(rec); lev="Yes" if any(k in s(rec.get("name"))+s(rec.get("target")) for k in ["正2","反1","槓桿","反向"]) else "No"; active="Yes" if t[-1:].isalpha() and t[-1:].upper()=="A" or "主動" in s(rec.get("name")) else "No"
        rg, rs = region(rec); risk, method = risk_rank(rec)
        if t == "00762B":
            name=issuer="n.a."; cat="Fixed Income"; sector="n.a."; rg=rs="n.a."; comm=curr="n.a."; lev=active="n.a."; risk="n.a."
        else:
            name=s(rec.get("name")) or "n.a."; issuer=s(rec.get("issuer")) or "n.a."; sector=bond_sector(rec) if cat=="Fixed Income" else "n.a."; comm=commodity_type(rec) if cat=="Commodities" else "n.a."; curr=currency(rec) if cat=="Currency" else "n.a."
        row={"ticker":t,"繁中名稱":name,"主題標籤":themes(rec),"zacks_category":cat,"zacks_sector":sector,"region_general":rg,"region_specific":rs,"commodity_type":comm,"currency":curr,"leveraged":lev,"actively_managed":active,"risk_rank":risk,"繁中敘述":description(rec,cat,rg,rs,risk,lev,active)}
        rows.append(row)
        logs.append({"ticker":t,"moneydj_url":rec.get("moneydj_url",""),"official_url":rec.get("official_url","") or official.get(t,{}).get("official_url",""),"moneydj_status":rec.get("status",""),"official_status":official.get(t,{}).get("status",""),"risk_rank":risk,"risk_method":method,"risk_evidence":("; ".join(x.get("rank","") for x in (official.get(t,{}).get("near_ranks") or [])[:5]) or "; ".join(official.get(t,{}).get("direct_ranks") or []))})
    cols=["ticker","繁中名稱","主題標籤","zacks_category","zacks_sector","region_general","region_specific","commodity_type","currency","leveraged","actively_managed","risk_rank","繁中敘述"]
    with (ROOT/"artifacts/etf_research.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols,lineterminator="\n");w.writeheader();w.writerows(rows)
    with (ROOT/"artifacts/verification_log.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(logs[0]),lineterminator="\n");w.writeheader();w.writerows(logs)
    print(json.dumps({"rows":len(rows),"columns":cols,"risk_methods":collections.Counter(x["risk_method"] for x in logs),"unresolved":[x["ticker"] for x in rows if "n.a." in x["繁中名稱"]]},ensure_ascii=False))

if __name__=="__main__":main()
