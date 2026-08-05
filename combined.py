#!/usr/bin/env python3
"""合并总览：把 RIOC（tennis.py）和 NYC Parks（nycparks.py）两套网球场
放进同一个页面，按「地点 × 时间」统一展示。

用法:
  python3 combined.py          # 各扒一次，生成 courts.html + courts_data.json
  python3 combined.py --open   # 生成后自动在浏览器打开

- RIOC：需登录的 permit 系统，用 tennis.py 的接口只读扫描（不提交）。
- NYC Parks：公开静态页，用 nycparks.py 只读扒取。
两者都转换成同一种 location 结构，复用 nycparks 的表格 + 网格 UI。
每跑一次覆盖输出文件；打开/刷新 courts.html 即为最新。
"""
import json
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import tennis
import nycparks
import courtreserve
import blume
import aptus

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "courts_data.json"
OUT_HTML = ROOT / "courts.html"
RIOC_ID = 1000  # 数值 id，避开与 NYC 地点 id (2~13) 冲突

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def rioc_location():
    """扫描 RIOC 六片场并转换成 nycparks 的 location 结构。"""
    cfg = tennis.cfg
    s = cfg["scan"]
    courts = s["courts"]
    court_strs = [str(c) for c in courts]

    with sync_playwright() as p:
        api = tennis.ensure_session(p)
        facmap = {c: tennis.get_facility(api, c) for c in courts}
        dates = []
        for date_str in tennis.resolve_dates():
            slots = tennis.slots_for(date_str, s["start_hour"], s["end_hour"], s["slot_minutes"])
            times = [st.strftime("%I:%M %p").lstrip("0") for st, _ in slots]
            grid = {c: {} for c in court_strs}
            avail = 0
            for c in courts:
                name, fid = facmap[c]
                taken = tennis.taken_indexes(api, name, fid, slots)
                for i, (st, en) in enumerate(slots):
                    tlabel = times[i]
                    if taken is None:
                        status = "unavailable"
                    elif i in taken:
                        status = "booked"
                    else:
                        status = "available"
                        avail += 1
                    grid[str(c)][tlabel] = {
                        "status": status,
                        "href": tennis.BASE if status == "available" else None,
                    }
            label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %d, %Y")
            dates.append({
                "date": date_str, "label": label, "times": times,
                "courts": court_strs, "grid": grid, "available_count": avail,
            })
        api.dispose()

    return {
        "id": RIOC_ID,
        "name": "RIOC Octagon Courts",
        "borough": "Roosevelt Island",
        "reservation_courts": len(courts),
        "walkon_courts": None,
        "first_reservation": "—",
        "last_reservation": "—",
        "url": tennis.BASE,
        "note": "RIOC permit 系统（需登录申请，本表为只读扫描；绿色格点击跳转官网）",
        "courts": court_strs,
        "dates": dates,
        "available_total": sum(d["available_count"] for d in dates),
    }


def main():
    locations = []

    # 1) RIOC（可能因登录/网络失败，失败也不影响 NYC 部分）
    print(f"{BOLD}扫描 RIOC 网球场…{RESET}")
    try:
        rioc = rioc_location()
        print(f"  {GREEN}✓{RESET} RIOC Octagon Courts  "
              f"{len(rioc['dates'])} 天 / {rioc['available_total']} 个空位")
        locations.append(rioc)
    except Exception as e:
        print(f"  {RED}✗ RIOC 扫描失败: {e}{RESET}")
        locations.append({
            "id": RIOC_ID, "name": "RIOC Octagon Courts", "borough": "Roosevelt Island",
            "reservation_courts": None, "walkon_courts": None,
            "first_reservation": "—", "last_reservation": "—",
            "url": tennis.BASE, "note": f"扫描失败：{e}",
            "courts": [], "dates": [], "available_total": None,
        })

    # 2) NYC Parks
    locations += nycparks.scrape_locations()

    # 3) CourtReserve 站点（USTA BJK、Edgewater…，无需登录；每站自带降级处理）
    locations += courtreserve.scrape_locations()

    # 4) Blume（哥大 Columbia Tennis Center，需登录，含价格；未配置则跳过）
    if blume.enabled():
        print(f"{BOLD}扒取 Blume（哥大 Columbia Tennis Center）…{RESET}")
        try:
            loc = blume.scrape_location()
            if loc:
                locations.append(loc)
        except Exception as e:
            print(f"  {RED}✗ Blume 扒取失败: {e}{RESET}")
            locations.append({
                "id": blume.LOC_ID, "name": "Columbia Tennis Center (Blume)",
                "borough": "Manhattan · Blume", "reservation_courts": None,
                "walkon_courts": None, "first_reservation": "—", "last_reservation": "—",
                "url": blume.GRID_URL, "note": f"扒取失败：{e}",
                "courts": [], "dates": [], "available_total": None,
            })
    else:
        print(f"{DIM}Blume 未配置账号密码，跳过（在 config.yaml 的 blume 段填写即可）。{RESET}")

    # 5) Prospect Park（Aptus，需登录；未配置则跳过）
    if aptus.enabled():
        try:
            loc = aptus.scrape_location()
            if loc:
                locations.append(loc)
        except Exception as e:
            print(f"  {RED}✗ Prospect Park 扒取失败: {e}{RESET}")
            locations.append({
                "id": aptus.LOC_ID, "name": "Prospect Park Tennis Center",
                "borough": "Brooklyn · Aptus", "reservation_courts": None,
                "walkon_courts": None, "first_reservation": "—", "last_reservation": "—",
                "url": aptus.CAL_URL, "note": f"扒取失败：{e}",
                "courts": [], "dates": [], "available_total": None,
            })
    else:
        print(f"{DIM}Prospect Park 未配置账号密码，跳过（在 config.yaml 的 prospectpark 段填写即可）。{RESET}")

    payload = {
        "timestamp": datetime.now().isoformat(),
        "source": nycparks.MAIN_URL,
        "locations": locations,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    OUT_HTML.write_text(nycparks.render_html(
        payload,
        title="🎾 网球场可预订总览（RIOC + NYC Parks）",
        cmd="python3 combined.py",
    ))

    total = sum((l.get("available_total") or 0) for l in locations)
    print(f"\n{GREEN}{BOLD}完成：{len(locations)} 个地点，共 {total} 个可预订时段{RESET}")
    print(f"  数据 -> {OUT_JSON}")
    print(f"  页面 -> {OUT_HTML}")

    if "--open" in sys.argv:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
