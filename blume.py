#!/usr/bin/env python3
"""Blume（哥大 Columbia Tennis Center）场地 + 价格扒取器（只读，不预订）。

站点是 Angular SPA，数据走需鉴权的 API（https://blumecustomer.com/api/blumeclub/…），
必须登录。策略：Playwright 用真实 UI 登录（自动完成 token 引导）→ 抓一次真实
请求拿到鉴权头 → 用同一 context 按日期重放以下接口：
  POST /api/blumeclub/getbookingsnew         # 网格：球场 × 时段 可用性
  POST /api/blumeclub/getdailypricechart     # 每日价格表（也试 getmemberdailypricechart）
绿色格 = 可预订（含价格）；灰色 = 不可用。

用法:
  python3 blume.py           # 扒一次，生成 blume.html + _data.json
  python3 blume.py --open    # 生成后自动打开
  python3 blume.py --debug   # 额外把原始接口响应存到 blume_raw.json 供排查

凭据放 config.yaml 的 blume 段；留空则本脚本直接跳过。
会话缓存在 blume_auth.json，失效自动重登。
"""
import json
import re
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
BCFG = cfg.get("blume", {}) or {}
BASE = BCFG.get("base_url", "https://blumecustomer.com")
API = f"{BASE}/api/blumeclub"
AUTH = ROOT / "blume_auth.json"
DATA_JSON = ROOT / "blume_data.json"
OUT_HTML = ROOT / "blume.html"
RAW_DUMP = ROOT / "blume_raw.json"
PORTAL = f"{BASE}/cmportal/"
GRID_URL = f"{BASE}/cmportal/courtrental/courthiregriddisplay"
DAYS_AHEAD = int(BCFG.get("days_ahead", 3))
LOC_ID = 1100

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def enabled():
    return bool(BCFG.get("username") and BCFG.get("password"))


def resolve_dates():
    today = datetime.now().date()
    return [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(DAYS_AHEAD)]


# ---------- 登录 + 抓取 ----------

def _do_login(page):
    """用真实 UI 登录 Blume 门户。"""
    page.goto(PORTAL, wait_until="networkidle")
    page.wait_for_timeout(2500)
    # Angular 登录表单：用多种选择器兜底
    user_sel = ("input[formcontrolname*='user' i], input[formcontrolname*='email' i], "
                "input[placeholder*='user' i], input[placeholder*='email' i], "
                "input[type='email'], input[type='text']")
    pass_sel = "input[type='password'], input[formcontrolname*='pass' i]"
    page.wait_for_selector(user_sel, timeout=20000)
    page.fill(user_sel, BCFG["username"])
    page.fill(pass_sel, BCFG["password"])
    for bsel in ["button:has-text('Login')", "button:has-text('Log In')",
                 "button:has-text('Sign In')", "button[type='submit']"]:
        if page.locator(bsel).count():
            page.click(bsel)
            break
    page.wait_for_timeout(4000)


def _capture_and_scrape(p, debug=False):
    from playwright.sync_api import TimeoutError as PWTimeout
    browser = p.chromium.launch(headless=True)
    ctx_args = {}
    if AUTH.exists():
        ctx_args["storage_state"] = str(AUTH)
    ctx = browser.new_context(**ctx_args)
    page = ctx.new_page()

    # 捕获真实请求的鉴权头 + 请求体模板
    captured = {"headers": None, "body": None}

    def on_request(req):
        if "getbookingsnew" in req.url and req.method == "POST" and captured["headers"] is None:
            captured["headers"] = dict(req.headers)
            captured["body"] = req.post_data

    page.on("request", on_request)

    # 先进网格页；若被踢回登录则登录
    page.goto(GRID_URL, wait_until="networkidle")
    page.wait_for_timeout(3000)
    if "/cmportal/courtrental" not in page.url or captured["headers"] is None:
        # 可能需要登录
        if not (BCFG.get("username") and BCFG.get("password")):
            raise RuntimeError("需要登录但 config.yaml 的 blume 未填账号密码")
        _do_login(page)
        ctx.storage_state(path=str(AUTH))
        page.goto(GRID_URL, wait_until="networkidle")
        page.wait_for_timeout(4000)

    if captured["headers"] is None:
        page.screenshot(path=str(ROOT / "blume_debug.png"))
        raise RuntimeError("未捕获到 getbookingsnew 请求（登录可能失败，见 blume_debug.png）")

    # 用捕获到的鉴权头，按日期重放 API
    api_headers = {k: v for k, v in captured["headers"].items()
                   if k.lower() in ("authorization", "content-type", "clienttoken",
                                    "usertoken", "token", "apikey", "accept")}
    api_headers.setdefault("Content-Type", "application/json")
    try:
        body_tmpl = json.loads(captured["body"]) if captured["body"] else {}
    except Exception:
        body_tmpl = {}

    raw = {}
    results = {}
    for date in resolve_dates():
        body = _with_date(body_tmpl, date)
        grid = _post(ctx, f"{API}/getbookingsnew", api_headers, body)
        price = None
        for ep in ("getmemberdailypricechart", "getdailypricechartnew", "getdailypricechart"):
            price = _post(ctx, f"{API}/{ep}", api_headers, body)
            if price and price.get("data"):
                break
        raw[date] = {"grid": grid, "price": price}
        results[date] = (grid, price)
        print(f"  {GREEN}✓{RESET} {date}: grid={_size(grid)} price={_size(price)}")

    browser.close()
    if debug:
        RAW_DUMP.write_text(json.dumps(raw, ensure_ascii=False, indent=2)[:5_000_000])
        print(f"  {DIM}原始响应 -> {RAW_DUMP}{RESET}")
    return results


def _post(ctx, url, headers, body):
    r = ctx.request.post(url, headers=headers, data=json.dumps(body))
    try:
        return r.json()
    except Exception:
        return None


def _with_date(tmpl, date):
    """把请求体里的日期字段替换成目标日期（尽量兼容多种字段名/格式）。"""
    body = json.loads(json.dumps(tmpl)) if tmpl else {}
    mmddyyyy = datetime.strptime(date, "%Y-%m-%d").strftime("%m/%d/%Y")
    for k in list(body.keys()):
        kl = k.lower()
        if "date" in kl:
            v = body[k]
            body[k] = mmddyyyy if (isinstance(v, str) and "/" in v) else date
    body.setdefault("bookingdate", mmddyyyy)
    return body


def _size(obj):
    if not obj:
        return "空"
    d = obj.get("data") if isinstance(obj, dict) else obj
    if isinstance(d, dict):
        return "{" + ",".join(f"{k}:{len(v) if isinstance(v,list) else '?'}" for k, v in d.items()) + "}"
    if isinstance(d, list):
        return f"[{len(d)}]"
    return "?"


# ---------- 解析（依据 main.js 里的字段名，首跑后按 blume_raw.json 校准） ----------

def _parse(results):
    """把 {date:(grid_json, price_json)} 解析成 location dict。
    首次真实运行后，若字段名有出入，据 blume_raw.json 微调即可。"""
    dates_out = []
    courts_order = []
    for date, (grid, price) in results.items():
        data = (grid or {}).get("data", grid) or {}
        courts = data.get("courts") or data.get("courtlist") or []
        # 球场名 + id
        cid_name = {}
        for c in courts:
            cid = c.get("courtid") or c.get("id")
            nm = c.get("courtname") or c.get("name") or c.get("displayname") or f"Court {cid}"
            if cid is not None:
                cid_name[int(cid)] = nm
        if not courts_order and cid_name:
            courts_order = [cid_name[k] for k in sorted(cid_name)]

        # 可用时段：slots 里 isavailable==1
        slots = data.get("slots") or data.get("courtslots") or data.get("gridcells") or []
        # 价格表：court/time -> price
        price_map = _price_map(price)

        # 组织成 grid[courtname][timelabel]
        times_set = {}
        gmap = {nm: {} for nm in cid_name.values()}
        for s in slots:
            cid = s.get("courtid")
            tmin = s.get("timeinminutes")
            if cid is None or tmin is None:
                continue
            nm = cid_name.get(int(cid))
            if not nm:
                continue
            tlabel = _minlabel(tmin)
            times_set[tmin] = tlabel
            avail = s.get("isavailable") in (1, True) and s.get("slotstatusid", 1) == 1
            pr = price_map.get((int(cid), tmin)) or price_map.get(tmin)
            gmap[nm][tlabel] = {
                "status": "available" if avail else "unavailable",
                "href": GRID_URL if avail else None,
                "price": pr,
            }

        times = [times_set[t] for t in sorted(times_set)]
        avail_count = sum(1 for nm in gmap for t in gmap[nm]
                          if gmap[nm][t]["status"] == "available")
        label = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
        dates_out.append({"date": date, "label": label, "times": times,
                          "courts": courts_order, "grid": gmap,
                          "available_count": avail_count})

    return {
        "id": LOC_ID,
        "name": "Columbia Tennis Center (Blume)",
        "borough": "Manhattan · Blume",
        "reservation_courts": len(courts_order) or None,
        "walkon_courts": None,
        "first_reservation": "—", "last_reservation": "—",
        "url": GRID_URL,
        "note": "哥大 Columbia Tennis Center（Blume，需登录；绿色=可预订，含价格）",
        "courts": courts_order,
        "dates": dates_out,
        "available_total": sum(d["available_count"] for d in dates_out),
    }


def _minlabel(m):
    h, mi = divmod(int(m), 60)
    return datetime(2000, 1, 1, h % 24, mi).strftime("%I:%M %p").lstrip("0")


def _price_map(price):
    """把价格表响应压成 {(courtid,timeinminutes):price} 或 {timeinminutes:price}。"""
    out = {}
    if not price:
        return out
    data = price.get("data", price) if isinstance(price, dict) else price
    rows = data if isinstance(data, list) else (data.get("pricechart") or data.get("prices")
                                                or data.get("pricelist") or [])
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        pr = r.get("price") or r.get("rate") or r.get("amount") or r.get("cost")
        tmin = r.get("timeinminutes") or r.get("starttime")
        cid = r.get("courtid")
        if pr is None:
            continue
        if cid is not None and tmin is not None:
            out[(int(cid), int(tmin))] = pr
        elif tmin is not None:
            out[int(tmin)] = pr
    return out


def scrape_location(debug=False):
    if not enabled():
        print(f"{DIM}Blume 未配置账号密码，跳过。{RESET}")
        return None
    from playwright.sync_api import sync_playwright
    print(f"{BOLD}扒取 Blume（哥大 Columbia Tennis Center）…{RESET}")
    with sync_playwright() as p:
        results = _capture_and_scrape(p, debug=debug)
    loc = _parse(results)
    print(f"  {GREEN}{loc['reservation_courts'] or 0} 片场 / {loc['available_total']} 个空位{RESET}")
    return loc


def main():
    debug = "--debug" in sys.argv
    if not enabled():
        sys.exit("请先在 config.yaml 的 blume 段填写 username / password。")
    loc = scrape_location(debug=debug)
    payload = {"timestamp": datetime.now().isoformat(), "source": GRID_URL, "locations": [loc]}
    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    import nycparks
    OUT_HTML.write_text(nycparks.render_html(
        payload, title="🎾 哥大 Columbia Tennis Center（Blume）", cmd="python3 blume.py"))
    print(f"\n{GREEN}{BOLD}完成 -> {OUT_HTML}{RESET}")
    if "--open" in sys.argv:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
