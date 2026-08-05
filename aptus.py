#!/usr/bin/env python3
"""Prospect Park Tennis Center（Aptus 系统）场地可用信息扒取器（只读，不预订）。

站点需登录（Knockout/jQuery 门户）。数据接口：
  POST /Member/Aptus/CourtBooking_Get
    data: locationid, resourcetype(Clay/Hard), start, end (MM/DD/YYYY), CalledFrom=WEB
    需带请求头 RequestVerificationToken（页面全局变量 TOKENHEADERVALUE）
  返回 {"CourtBooking_GetResult": "[[courts],[reserved events],[...]]"}
    courts: [{name:"Court 3a", id:"Clay2"}...]
    events: [{resourceId, start, end, title:"RESERVED", color:"#ff0000"...}]
  只返回已占用(RESERVED)时段 —— 空档 = 可预订（同 RIOC 模型）。

策略：Playwright 登录 → 打开 Calender 拿 token → 按 resourcetype×日期调接口 → 重建网格。

用法:
  python3 aptus.py            # 扒一次，生成 aptus.html + _data.json
  python3 aptus.py --open     # 生成后自动打开
凭据放 config.yaml 的 prospectpark 段；留空则跳过。会话缓存 aptus_auth.json。
"""
import json
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
PCFG = cfg.get("prospectpark", {}) or {}
BASE = PCFG.get("base_url", "https://prospectpark.aptussoft.com")
LOCATIONID = "Brooklyn"                      # GetCourtLocationList -> LocationID
RESOURCE_TYPES = ["Clay", "Hard"]
DAYS_AHEAD = int(PCFG.get("days_ahead", 3))
SLOT_MIN = 30
LOC_ID = 1101
AUTH = ROOT / "aptus_auth.json"
DATA_JSON = ROOT / "aptus_data.json"
OUT_HTML = ROOT / "aptus.html"
MAIN_URL = f"{BASE}/Member/Aptus/Main"
CAL_URL = f"{BASE}/Member/Aptus/Calender"
GET_URL = f"{BASE}/Member/Aptus/CourtBooking_Get"

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def enabled():
    return bool(PCFG.get("email") and PCFG.get("password"))


def resolve_dates():
    today = datetime.now().date()
    return [(today + timedelta(days=d)) for d in range(DAYS_AHEAD)]


def _token(page):
    try:
        return page.evaluate("() => (typeof TOKENHEADERVALUE!=='undefined') ? TOKENHEADERVALUE : null")
    except Exception:
        return None


def _authed(page):
    """真正判断是否登录：匿名页也有 token，故用一次真实取数验证（有球场即已登录）。"""
    tok = _token(page)
    if not tok:
        return False
    courts, _ = _fetch(page, tok, RESOURCE_TYPES[0], resolve_dates()[0])
    return bool(courts)


def _login(page):
    page.goto(MAIN_URL, wait_until="networkidle")
    page.wait_for_selector("#email", timeout=20000)
    page.fill("#email", PCFG["email"])
    page.fill("#password", PCFG["password"])
    page.wait_for_timeout(200)
    page.click("#btnSignIn")
    page.wait_for_timeout(5000)


def _fetch(page, token, resourcetype, d):
    """调 CourtBooking_Get，返回 (courts, events) 或 (None,None)。"""
    mmddyyyy = d.strftime("%m/%d/%Y")
    js = """([url,rt,day,tok]) => new Promise((res)=>{
      $.ajax({url:url, type:'POST', async:true,
        data:{locationid:'%s', resourcetype:rt, start:day, end:day, CalledFrom:'WEB'},
        headers:{'RequestVerificationToken': tok},
        success:x=>res(x), error:e=>res({__err:e.status})});
    })""" % LOCATIONID
    r = page.evaluate(js, [GET_URL, resourcetype, mmddyyyy, token])
    if not isinstance(r, dict) or "__err" in r or "CourtBooking_GetResult" not in r:
        return None, None
    parsed = json.loads(r["CourtBooking_GetResult"])
    courts = parsed[0] if len(parsed) > 0 else []
    events = parsed[1] if len(parsed) > 1 else []
    return courts, events


def _slots(day_start, day_end):
    step = timedelta(minutes=SLOT_MIN)
    out, cur = [], day_start
    while cur < day_end:
        out.append(cur)
        cur += step
    return out


def scrape_location():
    if not enabled():
        print(f"{DIM}Prospect Park 未配置账号密码，跳过。{RESET}")
        return None
    from playwright.sync_api import sync_playwright
    print(f"{BOLD}扒取 Prospect Park Tennis Center（Aptus）…{RESET}")
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)

        def open_calender(use_auth):
            ctx = br.new_context(**({"storage_state": str(AUTH)} if use_auth and AUTH.exists() else {}))
            page = ctx.new_page()
            page.goto(CAL_URL, wait_until="networkidle")
            page.wait_for_timeout(3000)
            return ctx, page

        ctx, page = open_calender(use_auth=True)
        if not _authed(page):                       # 缓存会话失效或首次运行 -> 全新登录
            print(f"  {DIM}登录中…{RESET}")
            ctx.close()
            ctx = br.new_context()
            page = ctx.new_page()
            _login(page)                            # 全新 context 直接进 Main 登录（同 recon）
            ctx.storage_state(path=str(AUTH))
            page.goto(CAL_URL, wait_until="networkidle")
            page.wait_for_timeout(3000)
        token = _token(page)
        if not token or not _authed(page):
            br.close()
            raise RuntimeError("登录失败或未取到有效会话")

        # 收集：{date: {courtname: [(start,end)...reserved]}}, 以及球场名单
        per_date = {}          # date_str -> {courtdisplay: [(s,e)]}
        court_order = []
        for d in resolve_dates():
            dstr = d.strftime("%Y-%m-%d")
            per_date[dstr] = {}
            for rt in RESOURCE_TYPES:
                courts, events = _fetch(page, token, rt, d)
                if courts is None:
                    continue
                id_name = {c["id"]: f"{rt}: {c['name']}" for c in courts}
                for disp in id_name.values():
                    if disp not in court_order:
                        court_order.append(disp)
                    per_date[dstr].setdefault(disp, [])
                for e in events or []:
                    disp = id_name.get(e.get("resourceId"))
                    if not disp:
                        continue
                    try:
                        s = datetime.fromisoformat(e["start"])
                        en = datetime.fromisoformat(e["end"])
                    except Exception:
                        continue
                    per_date[dstr].setdefault(disp, []).append((s, en))
            print(f"  {GREEN}✓{RESET} {dstr}: {sum(len(v) for v in per_date[dstr].values())} 个已占用时段")
        br.close()

    # 重建网格
    dates_out = []
    for dstr, courts_res in per_date.items():
        # 当天所有事件的时间范围决定窗口；无事件退回 6AM–11PM
        allev = [t for lst in courts_res.values() for t in lst]
        base = datetime.strptime(dstr, "%Y-%m-%d")
        if allev:
            day_start = min(s for s, _ in allev).replace(
                minute=0 if min(s for s, _ in allev).minute < 30 else 30, second=0, microsecond=0)
            end_max = max(e for _, e in allev)
            day_end = end_max if end_max.minute in (0, 30) else (
                end_max + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        else:
            day_start, day_end = base.replace(hour=6), base.replace(hour=23)
        slots = _slots(day_start, day_end)
        times = [s.strftime("%I:%M %p").lstrip("0") for s in slots]
        grid = {c: {} for c in court_order}
        avail = 0
        step = timedelta(minutes=SLOT_MIN)
        for i, s in enumerate(slots):
            e_end = s + step
            tlabel = times[i]
            for c in court_order:
                booked = any(es < e_end and ee > s for (es, ee) in courts_res.get(c, []))
                grid[c][tlabel] = {"status": "booked" if booked else "available",
                                   "href": MAIN_URL if not booked else None}
                if not booked:
                    avail += 1
        label = base.strftime("%A, %B %d, %Y")
        dates_out.append({"date": dstr, "label": label, "times": times,
                          "courts": court_order, "grid": grid, "available_count": avail})

    loc = {
        "id": LOC_ID,
        "name": "Prospect Park Tennis Center",
        "borough": "Brooklyn · Aptus",
        "reservation_courts": len(court_order) or None,
        "walkon_courts": None,
        "first_reservation": "—", "last_reservation": "—",
        "url": MAIN_URL,   # 用户跳转用门户首页；Calender 直连会报 "Please select locationid"
        "note": "Prospect Park Tennis Center（Aptus，需登录；绿色=可预订，含 Clay/Hard 场地）",
        "courts": court_order,
        "dates": dates_out,
        "available_total": sum(d["available_count"] for d in dates_out),
    }
    print(f"  {GREEN}{len(court_order)} 片场 / {loc['available_total']} 个空位{RESET}")
    return loc


def main():
    if not enabled():
        sys.exit("请先在 config.yaml 的 prospectpark 段填写 email / password。")
    loc = scrape_location()
    payload = {"timestamp": datetime.now().isoformat(), "source": CAL_URL, "locations": [loc]}
    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    import nycparks
    OUT_HTML.write_text(nycparks.render_html(
        payload, title="🎾 Prospect Park Tennis Center（Aptus）", cmd="python3 aptus.py"))
    print(f"\n{GREEN}{BOLD}完成 -> {OUT_HTML}{RESET}")
    if "--open" in sys.argv:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
