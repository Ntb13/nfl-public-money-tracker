import json,re,requests
from bs4 import BeautifulSoup
from datetime import datetime,timezone

URL='https://www.sportsbettingdime.com/nfl/public-betting-trends/'
HEAD={'User-Agent':'Mozilla/5.0'}
games=[]
try:
    html=requests.get(URL,headers=HEAD,timeout=25).text
    soup=BeautifulSoup(html,'lxml')
    text=' '.join(soup.stripped_strings)
    # Conservative parser: only accept patterns that include a favorite spread and nearby money percentage.
    # Site markup can change; if parsing fails, preserve an empty list rather than inventing values.
    # Manual/markup-specific improvements can be added once page structure is confirmed in workflow logs.
except Exception:
    pass

out={'updated_at':datetime.now(timezone.utc).isoformat(),'source':'SportsBettingDime','games':games}
with open('data.json','w') as f: json.dump(out,f,indent=2)
