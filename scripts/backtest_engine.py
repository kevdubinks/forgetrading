# backtest_engine.py - Phase 3
import json, urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import sys, os
sys.path.insert(0, str(Path(__file__).parent))
from utils import setup_logging, load_settings, save_json, DATA_DIR
logger=setup_logging("backtest")
BACKTEST_DIR=DATA_DIR/"backtest"
BINANCE_KLINES="https://api.binance.com/api/v3/klines"
CS={"bitcoin":"BTCUSDT","ethereum":"ETHUSDT","solana":"SOLUSDT","near":"NEARUSDT","chainlink":"LINKUSDT"}

def fetch_klines(sym,interval="1d",lim=90):
    u=f"{BINANCE_KLINES}?symbol={sym}&interval={interval}&limit={lim}"
    r=urllib.request.Request(u,headers={"User-Agent":"TradingAgent/1.0"})
    try:
        d=json.loads(urllib.request.urlopen(r,timeout=15).read())
        return[{"t":int(k[0]),"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])}for k in d]
    except Exception as e:
        logger.error(str(e))
        return[]

def changes(k):
    return[{"t":k[i]["t"],"p":k[i]["c"],"c":((k[i]["c"]-k[i-1]["c"])/k[i-1]["c"])*100}for i in range(1,len(k))]

def run_backtest(s=None,days=30):
    if s is None:s=load_settings()
    BACKTEST_DIR.mkdir(parents=True,exist_ok=True)
    coins=s.get("price_tracking",{}).get("coins",["bitcoin"])
    rk=s.get("risk_rules",{})
    mp=rk.get("max_position_pct",5)
    cap=100000
    t=[]
    for cid in coins[:3]:
        sym=CS.get(cid)
        if not sym:continue
        kl=fetch_klines(sym,lim=days+1)
        if len(kl)<10:continue
        ch=changes(kl)
        logger.info(f"{sym}: {len(ch)} days")
        for i,day in enumerate(ch[:-1]):
            cg=day["c"]
            ep=day["p"]
            if cg>5:
                al=min(cap*(mp/100)*(cg/100),cap*(mp/100))
                nx=ch[i+1]
                pnl=al*((nx["p"]-ep)/ep)
                t.append({"coin":cid,"date":datetime.fromtimestamp(day["t"]/1000).strftime("%Y-%m-%d"),"sig":f"Surge {cg:+.1f}%","alloc":round(al,2),"pnl":round(pnl,2),"pp":round((pnl/al)*100 if al>0 else 0,2)})
            elif cg<-10:
                al=min(cap*(mp/100)*(abs(cg)/100),cap*(mp/100))
                nx=ch[i+1]
                pnl=al*((ep-nx["p"])/ep)
                t.append({"coin":cid,"date":datetime.fromtimestamp(day["t"]/1000).strftime("%Y-%m-%d"),"sig":f"Drop {cg:+.1f}%","alloc":round(al,2),"pnl":round(pnl,2),"pp":round((pnl/al)*100 if al>0 else 0,2)})
    if not t:
        logger.info("No trades in period")
        return{"trades":[],"metrics":{"total_trades":0,"error":"No trades generated"}}
    w=[x for x in t if x["pnl"]>0]
    l=[x for x in t if x["pnl"]<=0]
    tp=sum(x["pnl"]for x in t)
    wr=len(w)/len(t)*100
    aw=sum(x["pnl"]for x in w)/len(w)if w else 0
    al=sum(x["pnl"]for x in l)/len(l)if l else 0
    b=max(t,key=lambda x:x["pnl"])
    wrst=min(t,key=lambda x:x["pnl"])
    m={"total_trades":len(t),"wins":len(w),"losses":len(l),"win_rate":round(wr,1),"total_pnl":round(tp,2),"avg_win":round(aw,2),"avg_loss":round(al,2),"profit_factor":round(abs(aw/al)if al!=0 else 999,2),"best":round(b["pnl"],2),"worst":round(wrst["pnl"],2),"return_pct":round((tp/cap)*100,2)}
    fname=BACKTEST_DIR/f"bt_{datetime.now().strftime("%Y%m%d_%H%M")}.json"
    save_json(fname,{"trades":t,"metrics":m})
    logger.info(f"Backtest: {len(t)} trades, PnL=${tp:.2f}, WR={wr:.1f}%")
    return{"trades":t,"metrics":m}

if __name__=="__main__":
    r=run_backtest(days=90)
    m=r["metrics"]
    S=chr(36)
    if m.get("error"):
        print(f"Result: {m["error"]}")
        print("Try increasing days or lowering thresholds")
        exit()
    print(f"\n=== Backtest 30 jours ===")
    print(f"Trades: {m["total_trades"]} | Wins: {m["wins"]} | Losses: {m["losses"]}")
    print(f"Win Rate: {m["win_rate"]}%")
    print(f"Total PnL: {S}{m["total_pnl"]:,.2f}")
    print(f"Return: {m["return_pct"]}%")
    print(f"Profit Factor: {m["profit_factor"]}")
    rr = abs(m.get("avg_win",0) / m.get("avg_loss",1)) if m.get("avg_loss") and m["avg_loss"] != 0 else 0
    ev = (m["win_rate"]/100 * m["avg_win"]) + ((1 - m["win_rate"]/100) * m["avg_loss"])
    print(f"Avg Win: {S}{m["avg_win"]:,.2f} | Avg Loss: {S}{m["avg_loss"]:,.2f}")
    print(f"R:R Ratio: 1:{rr:.2f}")
    print(f"Expected Value: {S}{ev:,.2f}/trade")
    print(f"Best: {S}{m["best"]:,.2f} | Worst: {S}{m["worst"]:,.2f}")
    if r["trades"]:
        print("\nDerniers trades:")
        for tx in r["trades"][-5:]:
            pl="+"if tx["pnl"]>=0 else""
            print(f"  {tx["date"]} {tx["coin"]:10s} {tx["sig"]:20s} -> PnL: {pl}{S}{tx["pnl"]:,.2f}")
