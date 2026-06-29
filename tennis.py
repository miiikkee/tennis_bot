#!/usr/bin/env python3
"""RIOC 网球场空场扫描器（只读，不提交）。

用法:
  python3 tennis.py            # 扫一次
  python3 tennis.py --watch    # 每小时自动扫，出现新空场时通知

成本优化：每个 court 的所有时段合并成一次 ConflictCheck 请求
(一天仅 6 个请求)。接口:
  GET  /Permits/Facilities/{siteId}  -> facility id
  POST /Permits/ConflictCheck        -> 返回被占用时段的下标列表，其余为空闲
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
AUTH = ROOT / "auth_state.json"
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
BASE = cfg["account"]["base_url"]

COURT_SITES = {
    1: "3c9230f0-9e2c-4ff0-8ad7-5300eb475af5",
    2: "f96d68ab-adea-42cb-8b42-c45a89e7ae2b",
    3: "5633e568-7db6-4e84-a02b-3ac827406bfc",
    4: "3e83f44d-ed76-4a95-a73e-e9c5dcfa6e55",
    5: "2158c5f2-8734-4755-b2ef-2627d4a5f0b1",
    6: "f3794e38-71ac-4440-9f3b-1adce02df1d7",
}

GREEN, DIM, RED, BOLD, RESET = "\033[32m", "\033[2m", "\033[31m", "\033[1m", "\033[0m"


def login(p):
    acc = cfg["account"]
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/Account/Login", wait_until="networkidle")
    page.fill("#loginEmail", acc["username"])
    page.fill("#loginPassword", acc["password"])
    page.click("button:has-text('Sign In')")
    page.wait_for_load_state("networkidle")
    if "/Account/Login" in page.url:
        browser.close()
        sys.exit("登录失败：请检查 config.yaml 的账号密码。")
    ctx.storage_state(path=str(AUTH))
    browser.close()


def new_api(p):
    return p.request.new_context(base_url=BASE, storage_state=str(AUTH))


def get_facility(api, court):
    r = api.get(f"/Permits/Facilities/{COURT_SITES[court]}")
    if r.status != 200 or not r.headers.get("content-type", "").startswith("application/json"):
        return None
    facs = r.json().get("Facilities", {})
    if not facs:
        return None
    name, fid = next(iter(facs.items()))
    return name, fid


def taken_indexes(api, fac_name, fac_id, slots):
    """一次请求返回被占用时段的下标集合；异常返回 None。"""
    payload = {
        "FacilityNames": [fac_name],
        "FacilityIds": [fac_id],
        "Dates": [
            {"Start": st.strftime("%Y-%m-%dT%H:%M:%S"), "Stop": en.strftime("%Y-%m-%dT%H:%M:%S")}
            for st, en in slots
        ],
    }
    r = api.post(
        "/Permits/ConflictCheck",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    if r.status != 200:
        return None
    try:
        return set(r.json())
    except Exception:
        return None


def resolve_dates():
    s = cfg["scan"]
    if s.get("dates"):
        return list(s["dates"])
    ahead = s.get("days_ahead", 2)
    ahead = ahead if isinstance(ahead, list) else [ahead]
    today = datetime.now().date()
    return [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in ahead]


def slots_for(date_str, start_hour, end_hour, slot_min):
    day = datetime.strptime(date_str, "%Y-%m-%d")
    cur = day.replace(hour=start_hour, minute=0)
    end = day.replace(hour=end_hour, minute=0)
    step = timedelta(minutes=slot_min)
    out = []
    while cur + step <= end + timedelta(seconds=1):
        out.append((cur, cur + step))
        cur += step
    return out


def ensure_session(p):
    """返回有效 api；必要时登录。"""
    if not AUTH.exists():
        print("首次运行，正在登录…")
        login(p)
    api = new_api(p)
    if get_facility(api, cfg["scan"]["courts"][0]) is None:
        print("会话失效，重新登录…")
        api.dispose()
        login(p)
        api = new_api(p)
    return api


def scan_once(api):
    """扫描配置里的日期，返回空闲列表 [{"date","court","start","end"}] 并打印网格、存 JSON。"""
    s = cfg["scan"]
    courts = s["courts"]
    facmap = {c: get_facility(api, c) for c in courts}
    req_count = len(courts)
    free_list = []

    for date_str in resolve_dates():
        wd = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")
        slots = slots_for(date_str, s["start_hour"], s["end_hour"], s["slot_minutes"])
        court_taken = {}
        for c in courts:
            name, fid = facmap[c]
            court_taken[c] = taken_indexes(api, name, fid, slots)
            req_count += 1

        print(f"\n{BOLD}=== {date_str} ({wd}) ==={RESET}")
        header = "时间段".ljust(15) + "".join(f"C{c}".center(6) for c in courts)
        print(header)
        print("-" * (15 + 6 * len(courts)))
        for i, (st, en) in enumerate(slots):
            label = f"{st:%H:%M}-{en:%H:%M}".ljust(15)
            cells, has_free = [], False
            for c in courts:
                taken = court_taken[c]
                if taken is None:
                    cells.append(f"{RED}  ?  {RESET}")
                elif i in taken:
                    cells.append(f"{DIM}  ·  {RESET}")
                else:
                    cells.append(f"{GREEN}  ✓  {RESET}")
                    has_free = True
                    free_list.append({
                        "date": date_str,
                        "court": c,
                        "start": f"{st:%H:%M}",
                        "end": f"{en:%H:%M}",
                    })
            if not s.get("only_free") or has_free:
                print(label + "".join(cells))

    print(f"\n{GREEN}{BOLD}空闲共 {len(free_list)} 个时段{RESET}  "
          f"{DIM}(本次 {req_count} 个请求){RESET}")
    if not free_list:
        print("  (无空闲)")

    # 保存到 data.json
    (ROOT / "data.json").write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "available": free_list,
    }, ensure_ascii=False, indent=2))
    return free_list


def notify_mac(title, msg):
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "{title}" sound name "Glass"'],
            check=False, capture_output=True,
        )
    except Exception:
        pass
    print("\a", end="")  # 终端响铃


def notify_wechat(title, content):
    """通过 PushPlus 发送微信通知。"""
    token = cfg.get("notify", {}).get("pushplus_token")
    if not token:
        return
    try:
        import requests
        payload = {
            "token": token,
            "title": title,
            "content": content,
        }
        requests.post("https://www.pushplus.plus/send", json=payload, timeout=5)
    except Exception as e:
        print(f"{RED}WeChat 通知失败: {e}{RESET}")


def watch():
    interval = cfg.get("watch", {}).get("interval_minutes", 60)
    notify = cfg.get("watch", {}).get("notify_on_new", True)
    prev = set()
    with sync_playwright() as p:
        api = ensure_session(p)
        while True:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n{BOLD}[{now}] 扫描中…{RESET}")
            try:
                cur_list = scan_once(api)
            except Exception as e:
                print(f"{RED}扫描出错，重建会话：{e}{RESET}")
                api.dispose()
                api = ensure_session(p)
                continue
            # 转换为集合便于比较（使用 (date, court, start-end) 元组）
            cur = set((item["date"], item["court"], f"{item['start']}-{item['end']}") for item in cur_list)
            new = cur - prev
            if new and prev:  # 第一次不报（全是"新"）
                lines = "; ".join(f"C{c} {d} {s}" for d, c, s in sorted(new))
                print(f"{GREEN}{BOLD}🎾 新空场：{lines}{RESET}")
                if notify:
                    notify_mac("🎾 网球场新空位", lines[:200])
                    notify_wechat("🎾 网球场新空位", lines[:200])
            prev = cur
            print(f"{DIM}{interval} 分钟后再扫… (Ctrl+C 退出){RESET}")
            time.sleep(interval * 60)


def main():
    if "--watch" in sys.argv:
        watch()
    else:
        with sync_playwright() as p:
            api = ensure_session(p)
            scan_once(api)
            api.dispose()


if __name__ == "__main__":
    main()
