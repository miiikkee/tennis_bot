#!/usr/bin/env python3
"""CourtReserve 场地可预订信息扒取器（只读，不预订）。

支持多个 CourtReserve 站点（见 SITES 配置），无需登录。
数据来自公开 JSON 接口：
  GET https://{host}/Online/Reservations/ReadExpanded/{org}?jsonData={...}
关键：jsonData 里带 Date + CustomSchedulerId 才能不登录取到数据。

接口只返回「已占用/关闭/开放」的事件（类似 RIOC 返回被占时段）。可用性规则：
  颜色 #ffffff(白) = Reserve/可预订；无事件(空档) = 可预订；
  颜色 #b3b9be(灰) = Unavailable(关闭)；其它颜色 = Booked(已约/课程)。

用法:
  python3 courtreserve.py          # 扒所有站点，生成 courtreserve.html + _data.json
  python3 courtreserve.py --open   # 生成后自动打开
通常由 combined.py 调 scrape_locations() 合并进总览页。
"""
import json
import re
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DAYS_AHEAD = 3
SLOT_MIN = 30
WHITE = "#ffffff"   # Reserve / 可预订
GRAY = "#b3b9be"    # Unavailable / 关闭

# 每个 CourtReserve 站点一条配置。court_regex 决定纳入哪些球场。
SITES = [
    {
        "id": 1001,
        "host": "usta.courtreserve.com",
        "org_id": "5881",
        "scheduler_id": "294",
        "name": "USTA Billie Jean King NTC",
        "borough": "Flushing, Queens · CourtReserve",
        "court_regex": r"(Indoor|Outdoor) Court",
        "note": "Indoor + Outdoor（CourtReserve 公开数据只读；绿色格点击跳转官网预订）",
    },
    {
        "id": 1002,
        "host": "app.courtreserve.com",
        "org_id": "7690",
        "scheduler_id": "20437",
        "name": "Edgewater Tennis",
        "borough": "Edgewater, NJ · CourtReserve",
        "court_regex": r"^Edgewater",   # 同 org 还有 Bergenfield（另一地点），此处只取 Edgewater
        "note": "Edgewater 场地（CourtReserve 公开数据，non-member 可看 3 天；白色 Reserve = 可约）",
    },
]

DATA_JSON = ROOT / "courtreserve_data.json"
OUT_HTML = ROOT / "courtreserve.html"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
GREEN, RED, BOLD, RESET = "\033[32m", "\033[31m", "\033[1m", "\033[0m"


def _book_url(site):
    return (f"https://{site['host']}/Online/Reservations/Bookings/"
            f"{site['org_id']}?sId={site['scheduler_id']}")


def _epoch_et(s):
    """/Date(ms)/ (UTC) -> America/New_York 本地 datetime。"""
    ms = int(re.search(r"\((\d+)", s).group(1))
    return datetime.fromtimestamp(ms / 1000, tz=UTC).astimezone(TZ)


def fetch_day(site, date):
    """拉取某站点某天（date=YYYY-MM-DD）的事件列表。"""
    json_data = {
        "orgId": site["org_id"], "TimeZone": "America/New_York", "Date": date,
        "KendoDate": {"Year": int(date[:4]), "Month": int(date[5:7]), "Day": int(date[8:10])},
        "UiCulture": "en-US", "CostTypeId": "", "CustomSchedulerId": site["scheduler_id"],
        "ReservationMinInterval": str(SLOT_MIN), "SelectedCourtIds": "", "MemberIds": "",
        "MemberFamilyId": "", "EmbedCodeId": "", "HideEmbedCodeReservationDetails": "true",
    }
    qs = urlencode({"jsonData": json.dumps(json_data), "sort": "", "group": "", "filter": ""})
    url = f"https://{site['host']}/Online/Reservations/ReadExpanded/{site['org_id']}?{qs}"
    req = Request(url, headers={
        "User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
    })
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace")).get("Data", [])


def _clean(label):
    return re.sub(r"\s+", " ", label).strip()


def _court_key(label):
    """自然排序：Indoor 在前，其次 P 场，再按编号。适配 'Indoor Court #4' 与 'Edgewater 2'。"""
    l = _clean(label)
    indoor = 0 if "indoor" in l.lower() else 1
    m = re.search(r"(P?)\s*#?\s*(\d+)", l)   # 可有可无的 # / P 前缀
    is_p = 1 if (m and m.group(1) == "P") else 0
    n = int(m.group(2)) if m else 999
    return (indoor, is_p, n, l)


def _slots(day_start, day_end):
    step = timedelta(minutes=SLOT_MIN)
    out, cur = [], day_start
    while cur < day_end:
        out.append(cur)
        cur += step
    return out


def resolve_dates():
    today = datetime.now(tz=TZ).date()
    return [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(DAYS_AHEAD)]


def scrape_days(site):
    """返回 {date: events}，并累积球场名单（跨天并集，更稳）。"""
    court_re = re.compile(site["court_regex"])
    days, roster = {}, set()
    for date in resolve_dates():
        evs = fetch_day(site, date)
        days[date] = evs
        roster.update(_clean(e["CourtLabel"]) for e in evs if court_re.search(e["CourtLabel"]))
        n = len({_clean(e["CourtLabel"]) for e in evs if court_re.search(e["CourtLabel"])})
        print(f"  {GREEN}✓{RESET} {date}: {len(evs)} 个事件 / {n} 片场")
        time.sleep(1)
    return days, sorted(roster, key=_court_key)


def _status_for(events):
    """给定重叠某格的事件列表，判定该格状态。白色/空档=可约。"""
    status = "available"
    for color in events:
        if color == WHITE:   # 白色事件视为可预订，继续看有没有其它占用
            continue
        return "unavailable" if color == GRAY else "booked"
    return status


def build_date(site, date, events, courts):
    """把某天事件重建成 court×time 网格。"""
    court_re = re.compile(site["court_regex"])
    per_court = {c: [] for c in courts}
    starts, ends = [], []
    for e in events:
        if not court_re.search(e["CourtLabel"]):
            continue
        c = _clean(e["CourtLabel"])
        if c not in per_court:
            continue
        s, en = _epoch_et(e["Start"]), _epoch_et(e["End"])
        per_court[c].append((s, en, (e.get("ReservationColor") or "").lower()))
        starts.append(s)
        ends.append(en)

    if not starts:  # 该天无数据，退回 6AM–11:30PM
        base = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=TZ)
        day_start, day_end = base.replace(hour=6), base.replace(hour=23, minute=30)
    else:
        day_start, day_end = min(starts), max(ends)
        day_start = day_start.replace(minute=0 if day_start.minute < 30 else 30,
                                      second=0, microsecond=0)
        if day_end.minute not in (0, 30):
            day_end = (day_end + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)

    slots = _slots(day_start, day_end)
    times = [s.strftime("%I:%M %p").lstrip("0") for s in slots]
    book_url = _book_url(site)
    grid = {c: {} for c in courts}
    avail = 0
    step = timedelta(minutes=SLOT_MIN)
    for i, s in enumerate(slots):
        e_end = s + step
        tlabel = times[i]
        for c in courts:
            overlap = [color for (es, ee, color) in per_court[c] if es < e_end and ee > s]
            status = _status_for(overlap)
            grid[c][tlabel] = {"status": status, "href": book_url if status == "available" else None}
            if status == "available":
                avail += 1
    label = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    return {"date": date, "label": label, "times": times,
            "courts": courts, "grid": grid, "available_count": avail}


def scrape_site(site):
    """扒取单个站点并转换成 nycparks 的 location 结构。"""
    print(f"{BOLD}扒取 CourtReserve: {site['name']}…{RESET}")
    days, courts = scrape_days(site)
    dates = [build_date(site, d, evs, courts) for d, evs in days.items()]
    return {
        "id": site["id"],
        "name": site["name"],
        "borough": site["borough"],
        "reservation_courts": len(courts),
        "walkon_courts": None,
        "first_reservation": "—",
        "last_reservation": "—",
        "url": _book_url(site),
        "note": site["note"],
        "courts": courts,
        "dates": dates,
        "available_total": sum(d["available_count"] for d in dates),
    }


def scrape_locations():
    """扒取所有站点，返回 location 列表（失败的站点单独降级，不影响其它）。"""
    locations = []
    for site in SITES:
        try:
            loc = scrape_site(site)
            print(f"  {GREEN}✓{RESET} {loc['name']}  "
                  f"{len(loc['dates'])} 天 / {loc['available_total']} 个空位")
            locations.append(loc)
        except Exception as e:
            print(f"  {RED}✗ {site['name']} 扒取失败: {e}{RESET}")
            locations.append({
                "id": site["id"], "name": site["name"], "borough": site["borough"],
                "reservation_courts": None, "walkon_courts": None,
                "first_reservation": "—", "last_reservation": "—",
                "url": _book_url(site), "note": f"扒取失败：{e}",
                "courts": [], "dates": [], "available_total": None,
            })
    return locations


def main():
    locations = scrape_locations()
    payload = {"timestamp": datetime.now().isoformat(),
               "source": _book_url(SITES[0]), "locations": locations}
    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    import nycparks
    OUT_HTML.write_text(nycparks.render_html(
        payload, title="🎾 CourtReserve 场地总览", cmd="python3 courtreserve.py"))
    total = sum((l.get("available_total") or 0) for l in locations)
    print(f"\n{GREEN}{BOLD}完成：{len(locations)} 个站点，共 {total} 个可预订时段{RESET}")
    print(f"  数据 -> {DATA_JSON}")
    print(f"  页面 -> {OUT_HTML}")
    if "--open" in sys.argv:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
