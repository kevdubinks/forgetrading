# decision_engine.py v2.2
import json,sys,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from utils import setup_logging,load_settings,load_json,save_json,DATA_DIR,now_iso
logger=setup_logging("decision_engine")
DECISION_LOG=DATA_DIR/"decisions.json"

W={"news_high":30,"news_medium":15,"price_surge":25,"price_drop":20,"wallet_move":25,"trending":10}

def score_news(articles):
    score=0;reasons=[]
    for a in articles:
        t=a["title"].lower()
        for kw in ["hack","exploit","ban","sec","regulation","crash","delist","emergency","rug","scam"]:
            if kw in t:score+=W["news_high"];reasons.append(f"[NEWS HIGH] {a["title"][:80]}");break
        else:
            for kw in ["partnership","launch","mainnet","listing","acquisition","funding","million","billion"]:
                if kw in t:score+=W["news_medium"];reasons.append(f"[NEWS MED] {a["title"][:80]}");break
    return min(score,100),reasons

def score_prices(price_data):
    score=0;reasons=[];surges=[];drops=[]
    for a in price_data.get("alerts",[]):
        chg=a["change_24h"]
        if chg>10:score+=W["price_surge"];surges.append(a);reasons.append(f"[SURGE] {a["coin"]}: {chg:+.1f}%")
        elif chg>5:score+=W["price_surge"]//2;surges.append(a)
        elif chg<-10:score+=W["price_drop"];drops.append(a);reasons.append(f"[DROP] {a["coin"]}: {chg:+.1f}%")
    if price_data.get("trending"):score+=W["trending"]
    return min(score,100),reasons,surges,drops

def score_wallets(alerts):
    score=0;reasons=[]
    for a in alerts:
        if a["severity"]=="high":score+=W["wallet_move"];reasons.append(f"[WHALE] {a["wallet"]}: {a["detail"]}")
        elif a["severity"]=="medium":score+=W["wallet_move"]//2
    return min(score,100),reasons

def generate_conviction(articles,price_data,wallet_alerts,settings=None):
    ns,nr=score_news(articles);ps,pr,surges,drops=score_prices(price_data);ws,wr=score_wallets(wallet_alerts)
    total=ns+ps+ws
    if total>=70:L="STRONG";A="ANALYZE"
    elif total>=40:L="MODERATE";A="MONITOR"
    elif total>=15:L="WEAK";A="WATCH"
    else:L="CALM";A="HOLD"
    logger.info(f"Conviction: {L} ({total}/100) -> {A}")
    return{"score":total,"level":L,"action":A,"components":{"news":ns,"prices":ps,"wallets":ws},"reasons":nr+pr+wr,"surges":[{"coin":s["coin"],"change":s["change_24h"]}for s in surges],"drops":[{"coin":d["coin"],"change":d["change_24h"]}for d in drops],"timestamp":now_iso()}

def paper_trade_recommendation(conv,price_data,alpaca_data,settings=None):
    if not alpaca_data or conv["level"]=="CALM":return None
    bp=alpaca_data["account"]["buying_power"]
    rk=settings.get("risk_rules",{})if settings else{}
    mp=bp*(rk.get("max_position_pct",5)/100)
    trades=[]
    for s in conv.get("surges",[])[:3]:
        if s["change"]>5:alloc=min(mp*(s["change"]/100),mp);trades.append({"action":"BUY","asset":s["coin"].upper(),"allocation":round(alloc,2),"reason":f"Surge {s["change"]:+.1f}% en 24h"})
    if not trades and conv["level"]in("STRONG","MODERATE"):trades.append({"action":"MONITOR","asset":"MARCHE","allocation":0,"reason":f"Signal {conv["level"]}"})
    return{"conviction_score":conv["score"],"conviction_level":conv["level"],"buying_power":bp,"max_position":mp,"trades":trades,"timestamp":now_iso()}

def get_decision_report(articles,price_data,wallet_alerts,alpaca_data,settings=None):
    conv=generate_conviction(articles,price_data,wallet_alerts,settings)
    reco=paper_trade_recommendation(conv,price_data,alpaca_data,settings)
    d={"conviction":conv,"recommendation":reco}
    h=load_json(DECISION_LOG)or[];h.append(d)
    if len(h)>90:h=h[-90:]
    save_json(DECISION_LOG,h)
    return d

if __name__=="__main__":
    from news_collector import collect_all_news
    from wallet_tracker import track_all_wallets
    from price_tracker import get_price_data
    from alpaca_tracker import get_alpaca_data
    s=load_settings()
    art=collect_all_news(s);wal=track_all_wallets(s);pri=get_price_data(s);alp=get_alpaca_data(s)
    d=get_decision_report(art,pri,wal,alp,s)
    cv=d["conviction"];rc=d["recommendation"]
    DOL=chr(36)
    print(f"Conviction: {cv["level"]} ({cv["score"]}/100) -> {cv["action"]}")
    for r in cv["reasons"][:5]:print(f"  {r}")
    if rc and rc.get("trades"):
        print(f"Paper Trades ({len(rc["trades"])}):")
        for t in rc["trades"]:print(f"  {t["action"]} {t["asset"]}: {DOL}{t["allocation"]:,.2f}")
