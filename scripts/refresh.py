import json,re
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright

URL="https://www.sportsbettingdime.com/nfl/public-betting-trends/"
SPREAD_LIMIT=-6.5
MONEY_LIMIT=77.0
now=datetime.now(timezone.utc).isoformat()

def load_old():
    try:
        with open("data.json") as f:return json.load(f)
    except Exception:return {"games":[],"history":[]}

def pct(x):
    m=re.search(r"(\d+(?:\.\d+)?)%",x or "")
    return float(m.group(1)) if m else None

def number(x):
    m=re.search(r"([+-]?\d+(?:\.\d+)?)", (x or "").replace("−","-"))
    return float(m.group(1)) if m else None

def gid(a,b):return "-".join(sorted((a,b)))

def scrape():
    games=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"])
        page=browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
        page.goto(URL,wait_until="domcontentloaded",timeout=60000)
        page.wait_for_timeout(10000)

        tables=page.query_selector_all("table")
        target=None; best=0
        for table in tables:
            rows=table.query_selector_all("tr")
            n=sum(1 for r in rows if not (r.get_attribute("class") or "").strip())
            if n>best: target,best=table,n
        if not target or best<3:
            browser.close(); raise RuntimeError(f"No SBD data table found (tables={len(tables)}, rows={best})")

        rows=[r for r in target.query_selector_all("tr") if not (r.get_attribute("class") or "").strip()]
        i=0
        while i<len(rows)-2:
            txt=(rows[i].inner_text() or "").strip()
            # Match SBD date rows such as "Sep 27, 10:00am PDT".
            if re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b.*\d{1,2}:\d{2}",txt,re.I):
                parsed=[]
                for row in (rows[i+1],rows[i+2]):
                    th=row.query_selector("th")
                    team=(th.inner_text() if th else "").strip()
                    cells=[(c.text_content() or "").strip() for c in row.query_selector_all("td")]
                    # SBD duplicates mobile/desktop ML cells. Desktop layout:
                    # td[3:6] ML; td[6]=SPREAD; td[7]=Spread BET%; td[8]=Spread $%/handle.
                    if team and len(cells)>8:
                        parsed.append({"team":team,"spread":number(cells[6]),"bet_pct":pct(cells[7]),"money_pct":pct(cells[8])})
                if len(parsed)==2 and all(x["spread"] is not None and x["money_pct"] is not None for x in parsed):
                    a,b=parsed
                    if a["spread"]<0 and b["spread"]>0:fav,dog=a,b
                    elif b["spread"]<0 and a["spread"]>0:fav,dog=b,a
                    else:fav=dog=None
                    if fav:
                        games.append({"id":gid(fav["team"],dog["team"]),"favorite":fav["team"],"underdog":dog["team"],
                          "favorite_spread":fav["spread"],"underdog_spread":dog["spread"],
                          "money_pct":fav["money_pct"],"bet_pct":fav["bet_pct"],"kickoff_label":txt})
                i+=3;continue
            i+=1
        browser.close()
    if not games:raise RuntimeError("SBD table loaded but no NFL matchups parsed")
    return games

old=load_old();old_active={g["id"]:g for g in old.get("games",[]) if g.get("id")}
history={g["id"]:g for g in old.get("history",[]) if g.get("id")}
try:
    parsed=scrape();available=True;note=f"Live SBD table parsed successfully: {len(parsed)} matchups."
except Exception as e:
    parsed=[];available=False;note=f"SBD scrape failed: {type(e).__name__}: {e}"

active=[]
if available:
    for g in parsed:
        q=g["favorite_spread"]<=SPREAD_LIMIT and g["money_pct"]>=MONEY_LIMIT
        prev=old_active.get(g["id"]);h=history.get(g["id"])
        if q:
            if not h:h={**g,"entered_at":now,"peak_money_pct":g["money_pct"],"status":"active"}
            else:
                h.update(g);h.update({"status":"active","dropped_at":None,"drop_reason":None})
                h["peak_money_pct"]=max(h.get("peak_money_pct",0),g["money_pct"])
            history[g["id"]]=h
            active.append({**g,"entered_at":h["entered_at"],"peak_money_pct":h["peak_money_pct"]})
        elif prev:
            h=history.get(g["id"],{**prev,"entered_at":prev.get("entered_at",now)})
            h.update(g);h.update({"status":"dropped","dropped_at":now})
            reasons=[]
            if g["favorite_spread"]>SPREAD_LIMIT:reasons.append(f"spread moved to {g['favorite_spread']:+g}")
            if g["money_pct"]<MONEY_LIMIT:reasons.append(f"spread money fell to {g['money_pct']:g}%")
            h["drop_reason"]="Dropped because "+" and ".join(reasons)+"."
            h["peak_money_pct"]=max(h.get("peak_money_pct",0),prev.get("money_pct",0),g["money_pct"])
            history[g["id"]]=h
else:active=old.get("games",[])

out={"updated_at":now,"source":"SportsBettingDime","source_url":URL,"source_available":available,"source_note":note,
"parameters":{"favorite_spread_max":SPREAD_LIMIT,"favorite_money_pct_min":MONEY_LIMIT,
"trigger_field":"SBD Spread $% (money/handle) ONLY; Spread BET% is displayed only as context and never triggers qualification."},
"games":active,"history":list(history.values())}
with open("data.json","w") as f:json.dump(out,f,indent=2)
print(json.dumps({"available":available,"matchups":len(parsed),"qualifiers":[[g["favorite"],g["favorite_spread"],g["money_pct"],g["bet_pct"]] for g in active],"note":note}))
