import json, re, requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

URL = "https://www.sportsbettingdime.com/nfl/public-betting-trends/"
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; NFLPublicMoneyTracker/1.0)"}
SPREAD_LIMIT = -6.5
MONEY_LIMIT = 77.0
now = datetime.now(timezone.utc).isoformat()

def num(s):
    m=re.search(r"[-+]?\d+(?:\.\d+)?", str(s).replace("−","-"))
    return float(m.group()) if m else None

def pct(s):
    v=num(s)
    return v if v is not None and 0 <= v <= 100 else None

def key(team, opponent):
    return re.sub(r"[^a-z0-9]+","-",f"{team}-{opponent}".lower()).strip("-")

def load_old():
    try:
        with open("data.json") as f: return json.load(f)
    except Exception:
        return {"games":[],"history":[]}

def parse_tables(html):
    """Conservative table parser. Returns [] rather than guessing when markup is ambiguous."""
    soup=BeautifulSoup(html,"lxml")
    page_text=" ".join(soup.stripped_strings)
    if "Public betting trends are not currently available" in page_text:
        return [], False, "SBD reports public betting trends are not currently available."

    found=[]
    for table in soup.find_all("table"):
        headers=[" ".join(x.stripped_strings).strip().lower() for x in table.find_all("th")]
        if not headers: continue
        # SBD tables can vary, so identify columns by meaning rather than fixed positions.
        spread_i=next((i for i,h in enumerate(headers) if "spread" in h or "odds" in h),None)
        bet_i=next((i for i,h in enumerate(headers) if "bet" in h and "%" in h),None)
        money_i=next((i for i,h in enumerate(headers) if "money" in h and "%" in h),None)
        side_i=next((i for i,h in enumerate(headers) if any(x in h for x in ("team","side","matchup"))),0)
        if spread_i is None or money_i is None: continue
        rows=[]
        for tr in table.find_all("tr"):
            cells=[" ".join(x.stripped_strings).strip() for x in tr.find_all(["td","th"])]
            if len(cells)<=max(spread_i,money_i,side_i): continue
            spread=num(cells[spread_i]); money=pct(cells[money_i])
            bets=pct(cells[bet_i]) if bet_i is not None and len(cells)>bet_i else None
            team=cells[side_i].strip()
            if team and spread is not None and money is not None and team.lower() not in ("team","side","matchup"):
                rows.append({"team":team,"spread":spread,"money_pct":money,"bet_pct":bets})
        # Pair adjacent sides when the table is team-row based.
        for i in range(0,len(rows)-1,2):
            a,b=rows[i],rows[i+1]
            fav=a if a["spread"]<b["spread"] else b
            dog=b if fav is a else a
            if fav["spread"] >= 0: continue
            found.append({
                "id":key(fav["team"],dog["team"]),
                "favorite":fav["team"],"underdog":dog["team"],
                "favorite_spread":fav["spread"],"underdog_spread":dog["spread"],
                "money_pct":fav["money_pct"],"bet_pct":fav["bet_pct"]
            })
    # de-duplicate exact matchup IDs
    return list({g["id"]:g for g in found}.values()), bool(found), None if found else "No parseable SBD spread table was found."

old=load_old()
old_games={g.get("id"):g for g in old.get("games",[]) if g.get("id")}
history={g.get("id"):g for g in old.get("history",[]) if g.get("id")}
source_available=False
source_note=None
parsed=[]

try:
    r=requests.get(URL,headers=HEADERS,timeout=30)
    r.raise_for_status()
    parsed,source_available,source_note=parse_tables(r.text)
except Exception as e:
    source_note=f"Source request failed: {type(e).__name__}"

active=[]
if source_available:
    seen=set()
    for g in parsed:
        seen.add(g["id"])
        qualifies=g["favorite_spread"]<=SPREAD_LIMIT and g["money_pct"]>=MONEY_LIMIT
        previous=old_games.get(g["id"])
        hist=history.get(g["id"])
        if qualifies:
            if hist is None:
                hist={**g,"entered_at":now,"peak_money_pct":g["money_pct"],"status":"active"}
            else:
                hist.update(g); hist["status"]="active"; hist["dropped_at"]=None; hist["drop_reason"]=None
                hist["peak_money_pct"]=max(hist.get("peak_money_pct",0),g["money_pct"])
            history[g["id"]]=hist
            active.append({**g,"entered_at":hist["entered_at"],"peak_money_pct":hist["peak_money_pct"]})
        elif previous:
            hist=history.get(g["id"],{**previous,"entered_at":previous.get("entered_at",now)})
            hist.update(g); hist["status"]="dropped"; hist["dropped_at"]=now
            reasons=[]
            if g["favorite_spread"]>SPREAD_LIMIT: reasons.append(f"spread moved to {g['favorite_spread']:+g}, below the -6.5 threshold")
            if g["money_pct"]<MONEY_LIMIT: reasons.append(f"spread money fell to {g['money_pct']:g}%, below 77%")
            hist["drop_reason"]="Dropped because "+" and ".join(reasons)+"."
            hist["peak_money_pct"]=max(hist.get("peak_money_pct",0),previous.get("money_pct",0),g["money_pct"])
            history[g["id"]]=hist
else:
    # Never falsely mark a game as dropped just because SBD is unavailable.
    active=list(old.get("games",[]))

out={
  "updated_at":now,
  "source":"SportsBettingDime",
  "source_url":URL,
  "source_available":source_available,
  "source_note":source_note,
  "parameters":{"favorite_spread_max":SPREAD_LIMIT,"favorite_money_pct_min":MONEY_LIMIT},
  "games":active,
  "history":list(history.values())
}
with open("data.json","w") as f: json.dump(out,f,indent=2)
print(json.dumps({"source_available":source_available,"parsed_games":len(parsed),"active_qualifiers":len(active),"history":len(history),"note":source_note}))
