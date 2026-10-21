p = "app/services/adaptive/daily_learner.py"
s = open(p, encoding="utf-8").read()
def rep(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)

rep("from datetime import datetime, timedelta, timezone\n", "from datetime import datetime, time as dtime, timedelta, timezone\n")
rep("ET = ZoneInfo(\"America/New_York\")\nSTATE_PATH", "ET = ZoneInfo(\"America/New_York\")\nMARKET_CLOSE = dtime(16, 0)\nSETTLED = dtime(16, 5)      # after this, today's daily bar is final\nSTATE_PATH")
rep("                complete = t.date() < now_et.date() or now_et.time() > datetime(2000, 1, 1, 16, 5).time()\n",
    "                complete = t.date() < now_et.date() or now_et.time() > SETTLED\n")
rep("""                after_close = t.time() >= datetime(2000, 1, 1, 16, 0).time()
                entry_date = pd.Timestamp(t.date()) if after_close else pd.Timestamp(t.date()) - pd.Timedelta(days=1)
                prior = closes[closes.index <= entry_date]
                nxt = closes[closes.index > entry_date]
                if len(prior) and len(nxt) and nxt.index[0] <= pd.Timestamp(now_et.date()) - pd.Timedelta(days=0) \
                        and (nxt.index[0].date() < now_et.date() or now_et.time() > datetime(2000, 1, 1, 16, 5).time()):
""", """                # Entry = last close before the signal; exit = the next trading day's close
                after_close = t.time() >= MARKET_CLOSE
                entry_date = pd.Timestamp(t.date()) if after_close else pd.Timestamp(t.date()) - pd.Timedelta(days=1)
                prior = closes[closes.index <= entry_date]
                nxt = closes[closes.index > entry_date]
                if (len(prior) and len(nxt)
                        and (nxt.index[0].date() < now_et.date() or now_et.time() > SETTLED)):
""")
open(p, "w", encoding="utf-8").write(s)
