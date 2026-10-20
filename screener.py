"""台股每日技術面選股：產生手機可安裝的網頁(docs/) + 選用 Telegram 通知"""
import os, json, zlib, struct, datetime as dt
import numpy as np, pandas as pd, requests, yfinance as yf

TOP_N = 15
MIN_AVG_VOL = 500_000   # 5日均量 >= 500張
MIN_PRICE = 10
TZ = dt.timezone(dt.timedelta(hours=8))

def get_universe():
    u = {}
    try:
        for x in requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=30).json():
            c = x["Code"]
            if len(c) == 4 and c.isdigit() and not c.startswith("0"):
                u[c + ".TW"] = x["Name"]
    except Exception as e:
        print("上市清單失敗", e)
    try:
        for x in requests.get("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", timeout=30).json():
            c = x["SecuritiesCompanyCode"]
            if len(c) == 4 and c.isdigit() and not c.startswith("0"):
                u[c + ".TWO"] = x["CompanyName"]
    except Exception as e:
        print("上櫃清單失敗", e)
    return u

def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

def analyze(df):
    df = df.dropna(subset=["Close", "Volume"])
    if len(df) < 70:
        return None
    c, v = df["Close"], df["Volume"]
    ma20, ma60 = c.rolling(20).mean(), c.rolling(60).mean()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    r = rsi(c)
    vol_ratio = v.iloc[-1] / v.iloc[-21:-1].mean()
    ok = (
        c.iloc[-1] >= MIN_PRICE
        and v.iloc[-5:].mean() >= MIN_AVG_VOL
        and c.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]          # 多頭排列
        and ma20.iloc[-1] > ma20.iloc[-6]                        # 月線上彎
        and c.iloc[-1] > c.iloc[-21:-1].max()                    # 突破20日高
        and vol_ratio >= 1.5                                     # 量增
        and hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]  # MACD 轉強
        and 55 <= r.iloc[-1] <= 80                               # RSI 強勢但未過熱
    )
    if not ok:
        return None
    return dict(close=round(float(c.iloc[-1]), 2), pct=round(float((c.iloc[-1]/c.iloc[-2]-1)*100), 2),
                vol_ratio=round(float(vol_ratio), 1), stop=round(float(ma20.iloc[-1]), 1))

def scan():
    uni = get_universe()
    tickers, hits, last = list(uni), [], None
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i+150]
        try:
            data = yf.download(chunk, period="9mo", group_by="ticker",
                               progress=False, threads=True, auto_adjust=True)
        except Exception as e:
            print("下載失敗", e); continue
        for t in chunk:
            try:
                d = data[t]
                day = d["Close"].dropna().index[-1].date()
                last = day if last is None or day > last else last
                res = analyze(d)
            except Exception:
                continue
            if res:
                res.update(code=t.split(".")[0], name=uni[t]); hits.append(res)
    hits.sort(key=lambda x: x["vol_ratio"], reverse=True)
    return hits[:TOP_N], len(hits), last

# ---------- 產生手機網頁 (PWA) ----------
def make_png(size, path):
    rows = []
    for y in range(size):
        row = bytearray([0]); fy = y / size
        for x in range(size):
            fx = x / size
            inside = 0.25 <= fy <= 0.72 and abs(fx - 0.5) <= (fy - 0.25) / 0.47 * 0.27
            row += bytes((255, 255, 255)) if inside else bytes((198, 40, 40))
        rows.append(bytes(row))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)

INDEX = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#c62828"><link rel="manifest" href="manifest.json">
<link rel="icon" href="icon-192.png"><title>台股每日選股</title>
<style>
:root{--bg:#f5f5f5;--card:#fff;--tx:#111;--sub:#666}
@media(prefers-color-scheme:dark){:root{--bg:#121212;--card:#1e1e1e;--tx:#eee;--sub:#999}}
body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--tx)}
header{background:#c62828;color:#fff;padding:16px}h1{margin:0;font-size:20px}
header p{margin:4px 0 0;font-size:13px;opacity:.9}
.card{background:var(--card);margin:10px;padding:12px 14px;border-radius:12px;display:flex;justify-content:space-between;align-items:center}
.n{font-size:17px;font-weight:600}.s{font-size:12px;color:var(--sub);margin-top:4px}
.p{text-align:right}.px{font-size:18px;font-weight:600}.up{color:#d32f2f}.dn{color:#2e7d32}
.empty,.foot{text-align:center;color:var(--sub);padding:20px;font-size:13px}
</style></head><body>
<header><h1>📈 台股每日選股</h1><p id="meta">載入中…</p></header>
<div id="list"></div>
<div class="foot">條件：多頭排列＋突破20日高＋量增1.5倍＋MACD轉強＋RSI 55~80<br>
使用前一交易日收盤資料。技術訊號僅供參考，非投資建議。</div>
<script>
fetch('data.json?'+Date.now()).then(r=>r.json()).then(d=>{
 document.getElementById('meta').textContent='資料日 '+d.date+'｜符合 '+d.total+' 檔｜更新 '+d.updated;
 var l=document.getElementById('list');
 if(!d.stocks.length){l.innerHTML='<div class="empty">今日無符合條件的個股</div>';return;}
 l.innerHTML=d.stocks.map(function(s){var c=s.pct>=0?'up':'dn';
 return '<div class="card"><div><div class="n">'+s.code+' '+s.name+'</div><div class="s">量比 '+s.vol_ratio+'x｜停損參考 '+s.stop+'</div></div>'+
 '<div class="p"><div class="px '+c+'">'+s.close.toFixed(2)+'</div><div class="s '+c+'">'+(s.pct>=0?'+':'')+s.pct.toFixed(2)+'%</div></div></div>';}).join('');
}).catch(function(){document.getElementById('meta').textContent='尚無資料，請稍後再試';});
if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js');
</script></body></html>"""

MANIFEST = {"name": "台股每日選股", "short_name": "台股選股", "start_url": "./", "scope": "./",
            "display": "standalone", "background_color": "#c62828", "theme_color": "#c62828",
            "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                      {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}

SW = """self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(clients.claim()));
self.addEventListener('fetch',e=>{e.respondWith(fetch(e.request).then(r=>{var c=r.clone();
caches.open('v1').then(x=>x.put(e.request,c));return r;}).catch(()=>caches.match(e.request)));});"""

def write_site(hits, total, date):
    os.makedirs("docs", exist_ok=True)
    data = {"date": str(date), "total": total, "stocks": hits,
            "updated": dt.datetime.now(TZ).strftime("%m/%d %H:%M")}
    json.dump(data, open("docs/data.json", "w", encoding="utf-8"), ensure_ascii=False)
    open("docs/index.html", "w", encoding="utf-8").write(INDEX)
    json.dump(MANIFEST, open("docs/manifest.json", "w", encoding="utf-8"), ensure_ascii=False)
    open("docs/sw.js", "w").write(SW)
    make_png(192, "docs/icon-192.png"); make_png(512, "docs/icon-512.png")

# ---------- Telegram 通知（選用）----------
def notify(hits, total, date):
    tg, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tg and chat):
        print("未設定 Telegram，略過通知"); return
    if hits:
        lines = [f"📈 台股偏多訊號（{date} 收盤）", f"共 {total} 檔符合，前 {len(hits)} 檔：", ""]
        lines += [f"{h['code']} {h['name']}  {h['close']} ({h['pct']:+.1f}%) 量比{h['vol_ratio']}x" for h in hits]
    else:
        lines = [f"📉 今日無符合條件的個股（{date} 收盤）"]
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        o, r = repo.split("/"); lines += ["", f"完整頁面：https://{o}.github.io/{r}/"]
    lines.append("⚠️ 技術訊號僅供參考，非投資建議")
    r = requests.post(f"https://api.telegram.org/bot{tg}/sendMessage",
                      json={"chat_id": chat, "text": "\n".join(lines)}, timeout=30)
    print("Telegram", r.status_code)

if __name__ == "__main__":
    hits, total, date = scan()
    date = date or dt.datetime.now(TZ).date()
    write_site(hits, total, date)
    notify(hits, total, date)
