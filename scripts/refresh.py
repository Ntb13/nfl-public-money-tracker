import json, re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

URL="https://www.sportsbettingdime.com/nfl/public-betting-trends/"
SPREAD_LIMIT=-6.5
MONEY_LIMIT=77.0
TEAMS={"ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB","HOU","IND","JAC","KC","LV","LAC","LA","MIA","MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS"}
now=datetime.now(timezone.utc).isoformat()

def load_old():
    try:
        with open("data.json") as f:return json.load(f)
    except Exception:return {"games":[],"history":[]}

def game_id(a,b): return "-".join(sorted((a,b)))

def get_rendered_text():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={"width":1600,"height":1400},user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
        page.goto(URL,wait_until="domcontentloaded",timeout=60000)
        # SBD's betting board is a client-side widget and may live in an iframe.
        # Do not wait for team text in the parent document; let the widget load,
        # then inspect every rendered frame.
        page.wait_for_timeout(15000)
        texts=[]
        for frame in page.frames:
            try:
                txt=frame.locator("body").inner_text(timeout=5000)
                if txt: texts.append(txt)
            except Exception:
                pass
        browser.close()
        return "\n".join(texts)

def parse_rendered(text):
    # Rendered SBD row order is:
    # TEAM, moneyline, ML BET%, ML $%, spread, SPREAD BET%, SPREAD $%, total, TOTAL BET%, TOTAL $%.
    # We intentionally trigger ONLY on the 2nd percentage after the spread: SPREAD $% (money/handle).
    lines=[re.sub(r"\s+"," ",x).strip() for x in text.splitlines() if x.strip()]
    rows=[]
    pct_re=re.compile(r"^(\d+(?:\.\d+)?)%$")
    spread_re=re.compile(r"^[+-](?:\d+(?:\.\d+)?|PK)$",re.I)
    for i,line in enumerate(lines):
        if line not in TEAMS: continue
        vals=[]
        for x in lines[i+1:i+18]:
            if x in TEAMS or "Matchup Report" in x: break
            vals.append(x)
        # Locate spread token, then the next two percentage tokens are spread BET% and spread $%.
        si=next((j for j,x in enumerate(vals) if spread_re.match(x) and not x.lower().startswith(("+o","-o","+u","-u"))),None)
        if si is None: continue
        after=vals[si+1:]
        ps=[float(m.group(1)) for x in after if (m:=pct_re.match(x))]
        if len(ps)<2: continue
        spread=float(vals[si].replace("+",""))
        rows.append({"team":line,"spread":spread,"spread_bet_pct":ps[0],"spread_money_pct":ps[1]})

    games=[]
    # SBD renders the two sides of each matchup consecutively.
    for i in range(len(rows)-1):
        a,b=rows[i],rows[i+1]
        if a["spread"]<0 and b["spread"]>0: fav,dog=a,b
        elif b["spread"]<0 and a["spread"]>0: fav,dog=b,a
        else: continue
        gid=game_id(fav["team"],dog["team"])
        if any(g["id"]==gid for g in games): continue
        games.append({
          "id":gid,"favorite":fav["team"],"underdog":dog["team"],
          "favorite_spread":fav["spread"],"underdog_spread":dog["spread"],
          "money_pct":fav["spread_money_pct"],"bet_pct":fav["spread_bet_pct"]
        })
    return games

old=load_old()
old_active={g["id"]:g for g in old.get("games",[]) if g.get("id")}
history={g["id"]:g for g in old.get("history",[]) if g.get("id")}
try:
    rendered=get_rendered_text()
    parsed=parse_rendered(rendered)
    if not parsed: raise RuntimeError("Rendered SBD page contained no parseable NFL matchups")
    source_available=True; source_note=f"Rendered SBD widget parsed successfully: {len(parsed)} matchups."
except Exception as e:
    parsed=[]; source_available=False; source_note=f"SBD browser scrape failed: {type(e).__name__}: {e}"

active=[]
if source_available:
    for g in parsed:
        qualifies=g["favorite_spread"]<=SPREAD_LIMIT and g["money_pct"]>=MONEY_LIMIT
        prev=old_active.get(g["id"]); hist=history.get(g["id"])
        if qualifies:
            if not hist:
                hist={**g,"entered_at":now,"peak_money_pct":g["money_pct"],"status":"active"}
            else:
                hist.update(g); hist["status"]="active"; hist["dropped_at"]=None; hist["drop_reason"]=None
                hist["peak_money_pct"]=max(hist.get("peak_money_pct",0),g["money_pct"])
            history[g["id"]]=hist
            active.append({**g,"entered_at":hist["entered_at"],"peak_money_pct":hist["peak_money_pct"]})
        elif prev:
            hist=history.get(g["id"],{**prev,"entered_at":prev.get("entered_at",now)})
            hist.update(g); hist["status"]="dropped"; hist["dropped_at"]=now
            reasons=[]
            if g["favorite_spread"]>SPREAD_LIMIT: reasons.append(f"spread moved to {g['favorite_spread']:+g}")
            if g["money_pct"]<MONEY_LIMIT: reasons.append(f"spread money fell to {g['money_pct']:g}%")
            hist["drop_reason"]="Dropped because "+" and ".join(reasons)+"."
            hist["peak_money_pct"]=max(hist.get("peak_money_pct",0),prev.get("money_pct",0),g["money_pct"])
            history[g["id"]]=hist
else:
    active=old.get("games",[]) # never erase qualifiers because the source failed

out={"updated_at":now,"source":"SportsBettingDime","source_url":URL,"source_available":source_available,
     "source_note":source_note,"parameters":{"favorite_spread_max":SPREAD_LIMIT,"favorite_money_pct_min":MONEY_LIMIT,
     "trigger_field":"spread $% (money/handle); NOT spread BET% (ticket count)"},
     "games":active,"history":list(history.values())}
with open("data.json","w") as f:json.dump(out,f,indent=2)
print(json.dumps({"source_available":source_available,"matchups":len(parsed),"qualifiers":[(g["favorite"],g["favorite_spread"],g["money_pct"],g["bet_pct"]) for g in active],"note":source_note}))
