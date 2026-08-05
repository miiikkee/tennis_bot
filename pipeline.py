#!/usr/bin/env python3
"""数据管道（产品用）：把免登录来源抽成独立 adapter，产出 webapp 只读的契约文件。

稳定性设计：
- 只跑免登录来源（NYC Parks / CourtReserve），登录站是静态锁定卡（LOCKED），不进关键路径。
- 每个来源独立缓存 cache/<key>.json（last-good）；抓失败 → 沿用上次成功数据并标记 stale，绝不清零。
- 并发抓取 + 每源超时；单源挂不影响其它。
- 分类（region / book_kind / site）在这里完成，webapp 只做展示。
- 原子写（临时文件 + os.replace）+ 契约校验，webapp 永远读到完整合法的 JSON。

产出 public_data.json：
  { generated_at, sources:[{key,label,status,last_success,error,count}],
    public:[location...（含 region/book_kind/site/source/updated_at/stale）],
    locked:[{name,region,blurb,has_price,login_url}] }

用法: python3 pipeline.py
"""
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo

import nycparks
import courtreserve

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")
CACHE = ROOT / "cache"
OUT = ROOT / "public_data.json"
LOGIN_OUT = ROOT / "login_data.json"
PER_SOURCE_TIMEOUT = 150  # 秒，单源超时即用 last-good
INCLUDE_LOGIN_SITES = True  # 用 config.yaml 里配置的账号后台抓取需登录的场馆

import yaml  # noqa: E402
cfg = yaml.safe_load((ROOT / "config.yaml").read_text()) if (ROOT / "config.yaml").exists() else {}

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"

# 免登录来源（产品关键路径）
SOURCES = [
    {"key": "nycparks", "label": "NYC Parks", "fn": nycparks.scrape_locations},
    {"key": "courtreserve", "label": "CourtReserve", "fn": courtreserve.scrape_locations},
]

# 需登录来源：配置了账号的用运营方账号后台抓取（见 LOGIN_SOURCES）；
# 没配置账号的仍作为锁定卡（LOCKED，只跳转）。key 用于二者对应。
LOCKED = [
    {"key": "rioc", "name": "RIOC Octagon Courts", "region": "Roosevelt Island",
     "login_url": "https://rioc.civicpermits.com/Account/Login?ReturnUrl=%2f",
     "blurb": "RIOC permit 系统，需账号申请。", "has_price": False},
    {"key": "columbia", "name": "Columbia Tennis Center", "region": "Manhattan",
     "login_url": "https://blumecustomer.com/cmportal/columbia/login",
     "blurb": "哥大 Blume 系统，需账号登录（含价格）。", "has_price": True},
    {"key": "prospect", "name": "Prospect Park Tennis Center", "region": "Brooklyn",
     "login_url": "https://prospectpark.aptussoft.com/Member",
     "blurb": "Prospect Park（Aptus 系统），需账号登录。", "has_price": False},
]


def _login_sources():
    """登录类来源（运营方账号）。延迟 import 以免无谓加载 Playwright 相关模块。"""
    import combined
    import aptus
    import blume
    rioc_ok = bool((cfg.get("account") or {}).get("username"))
    return [
        {"key": "rioc", "label": "RIOC", "site": "RIOC", "default_type": "Outdoor",
         "enabled": (lambda: rioc_ok), "adapter": combined.rioc_location},
        {"key": "prospect", "label": "Prospect Park", "site": "Prospect", "default_type": "Outdoor",
         "enabled": aptus.enabled, "adapter": aptus.scrape_location},
        {"key": "columbia", "label": "Columbia", "site": "Columbia", "default_type": "",
         "enabled": blume.enabled, "adapter": blume.scrape_location},
    ]


def run_login_source(src):
    """跑单个登录来源（Playwright，串行）；成功写缓存，失败回退 last-good。"""
    cf = CACHE / f"{src['key']}.json"
    prev = None
    if cf.exists():
        try:
            prev = json.loads(cf.read_text())
        except Exception:
            prev = None
    try:
        loc = src["adapter"]()
        locs = [loc] if loc else []
        if not locs:
            raise RuntimeError("适配器未返回场馆")
        rec = {"key": src["key"], "label": src["label"], "status": "fresh",
               "last_success": now_iso(), "error": None, "locations": locs}
        atomic_write(cf, rec)
        return rec
    except Exception as e:
        if prev:
            prev["status"] = "stale"
            prev["error"] = str(e)
            print(f"  {RED}✗ {src['label']} 登录抓取失败，沿用上次数据（stale）：{e}{RESET}")
            return prev
        print(f"  {RED}✗ {src['label']} 登录抓取失败且无缓存：{e}{RESET}")
        return None


def now_iso():
    return datetime.now(TZ).isoformat()


def atomic_write(path, obj):
    """写临时文件再原子替换，杜绝读到半截 JSON。"""
    data = json.dumps(obj, ensure_ascii=False, indent=2)  # 先序列化，坏数据在此就报错
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def region_of(borough):
    b = borough or ""
    for k in ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"):
        if k.lower() in b.lower():
            return k
    if "nj" in b.lower() or "edgewater" in b.lower():
        return "New Jersey"
    parts = b.split("·")[0].split(",")
    return (parts[-1] if len(parts) > 1 else parts[0]).strip() or "—"


def valid_location(loc):
    return (isinstance(loc.get("name"), str) and loc.get("id") is not None
            and isinstance(loc.get("dates"), list) and isinstance(loc.get("courts"), list))


def run_source(src):
    """跑单个来源；成功则写缓存，失败则回退上次成功缓存并标记 stale。含逐地点兜底。"""
    cf = CACHE / f"{src['key']}.json"
    prev = None
    if cf.exists():
        try:
            prev = json.loads(cf.read_text())
        except Exception:
            prev = None
    try:
        locs = src["fn"]() or []
        # 逐地点兜底：本轮某地点抓空(dates=[]) 但上次有数据 -> 沿用旧数据并标记
        if prev:
            prev_by_id = {l.get("id"): l for l in prev.get("locations", [])}
            for i, loc in enumerate(locs):
                if not loc.get("dates") and prev_by_id.get(loc.get("id"), {}).get("dates"):
                    bf = dict(prev_by_id[loc["id"]])
                    bf["_backfilled"] = True
                    locs[i] = bf
        rec = {"key": src["key"], "label": src["label"], "status": "fresh",
               "last_success": now_iso(), "error": None, "locations": locs}
        atomic_write(cf, rec)
        return rec
    except Exception as e:
        if prev:
            prev["status"] = "stale"
            prev["error"] = str(e)
            print(f"  {RED}✗ {src['label']} 失败，沿用上次成功数据（stale）：{e}{RESET}")
            return prev
        print(f"  {RED}✗ {src['label']} 失败且无缓存：{e}{RESET}")
        return {"key": src["key"], "label": src["label"], "status": "error",
                "last_success": None, "error": str(e), "locations": []}


# 场馆经纬度（用于「按地点」地图；含锁定站）。按名字子串匹配。
COORDS = {
    "Central Park": (40.7896, -73.9616), "Alley Pond": (40.7466, -73.7553),
    "McCarren": (40.7205, -73.9506), "Mill Pond": (40.8268, -73.9285),
    "Riverside Clay": (40.7960, -73.9772), "Riverside Park (119": (40.8110, -73.9660),
    "Randall": (40.7930, -73.9210), "Sutton East": (40.7585, -73.9600),
    "USTA": (40.7500, -73.8450), "Edgewater": (40.8276, -73.9770),
    "RIOC": (40.7620, -73.9490), "Columbia": (40.8700, -73.9200),
    "Prospect Park": (40.6540, -73.9620),
}


def coords_of(name):
    for k, v in COORDS.items():
        if k in name:
            return {"lat": v[0], "lng": v[1]}
    return {"lat": None, "lng": None}


def default_type_of(loc):
    """场馆室内外默认：USTA 靠球场名自描述；NYC Parks 全室外；CourtReserve 的 Edgewater(Infinite Future) 室内。"""
    url = (loc.get("url") or "").lower()
    if loc["source"] == "nycparks":
        return "Outdoor"
    if "usta" in url:
        return ""  # 名字里已含 Indoor/Outdoor
    if "courtreserve.com" in url:
        return "Indoor"
    return ""


def annotate(loc, rec):
    """把展示所需分类下沉到数据层：region / book_kind / site / source / 新鲜度 / 室内外 / 坐标。"""
    url = loc.get("url", "")
    facility = "courtreserve.com" in url
    loc["book_kind"] = "facility" if facility else "slot"
    loc["site"] = loc["name"].split()[0] if facility else "NYC Parks"
    loc["region"] = region_of(loc.get("borough"))
    loc["source"] = rec["key"]
    loc["updated_at"] = rec.get("last_success")
    loc["stale"] = (rec["status"] != "fresh") or bool(loc.get("_backfilled")) or bool(loc.get("error"))
    loc["default_type"] = default_type_of(loc)
    loc.update(coords_of(loc["name"]))
    return loc


def _scrape_login():
    """串行抓取登录类来源（运营方账号）。返回 (locations, sources_status, scraped_keys)。"""
    locations, sources_status, scraped_keys = [], [], set()
    try:
        login_srcs = [s for s in _login_sources() if s["enabled"]()]
    except Exception as e:
        print(f"  {RED}登录来源初始化失败：{e}{RESET}")
        return locations, sources_status, scraped_keys
    if login_srcs:
        print(f"{BOLD}用运营方账号抓取需登录场馆（串行）…{RESET}")
    for src in login_srcs:
        rec = run_login_source(src)
        if not rec or not rec.get("locations"):
            continue
        kept = 0
        for loc in rec["locations"]:
            if not valid_location(loc):
                continue
            annotate(loc, rec)
            loc["book_kind"] = "facility"   # 无逐时段直链 -> 去官网订
            loc["site"] = src["site"]
            if src.get("default_type"):
                loc["default_type"] = src["default_type"]
            locations.append(loc)
            kept += 1
        if kept:
            scraped_keys.add(src["key"])
            sources_status.append({"key": rec["key"], "label": rec["label"],
                                   "status": rec["status"], "last_success": rec.get("last_success"),
                                   "error": rec.get("error"), "count": kept})
            dot = "✓" if rec["status"] == "fresh" else "⚠"
            print(f"  {GREEN if rec['status']=='fresh' else RED}{dot}{RESET} "
                  f"{rec['label']:<14} {kept} 个地点 · {rec['status']}（登录）")
    return locations, sources_status, scraped_keys


def generate_login():
    """只抓登录类来源 -> login_data.json（供 Mac 端跑、push 到托管仓库）。"""
    CACHE.mkdir(exist_ok=True)
    locations, sources_status, _ = _scrape_login()
    payload = {"generated_at": now_iso(), "sources": sources_status, "locations": locations}
    atomic_write(LOGIN_OUT, payload)
    total = sum((l.get("available_total") or 0) for l in locations)
    print(f"\n{GREEN}{BOLD}登录数据完成：{len(locations)} 个地点 · {total} 个空位 -> {LOGIN_OUT}{RESET}")
    return payload


def generate(include_login=INCLUDE_LOGIN_SITES):
    CACHE.mkdir(exist_ok=True)
    print(f"{BOLD}数据管道：并发抓取免登录来源…{RESET}")
    records = {}
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as ex:
        futs = {s["key"]: ex.submit(run_source, s) for s in SOURCES}
        for s in SOURCES:
            try:
                records[s["key"]] = futs[s["key"]].result(timeout=PER_SOURCE_TIMEOUT)
            except Exception as e:  # 超时/线程崩溃 -> last-good
                cf = CACHE / f"{s['key']}.json"
                if cf.exists():
                    prev = json.loads(cf.read_text())
                    prev["status"] = "stale"
                    prev["error"] = f"timeout/{e}"
                    records[s["key"]] = prev
                    print(f"  {RED}✗ {s['label']} 超时，沿用缓存（stale）{RESET}")
                else:
                    records[s["key"]] = {"key": s["key"], "label": s["label"],
                                         "status": "error", "last_success": None,
                                         "error": str(e), "locations": []}

    public, sources_status = [], []
    for s in SOURCES:
        rec = records[s["key"]]
        kept = 0
        for loc in rec.get("locations", []):
            if valid_location(loc):
                public.append(annotate(loc, rec))
                kept += 1
            else:
                print(f"  {DIM}跳过不合契约的地点：{loc.get('name')}{RESET}")
        sources_status.append({"key": rec["key"], "label": rec["label"],
                               "status": rec["status"], "last_success": rec.get("last_success"),
                               "error": rec.get("error"), "count": kept})
        dot = {"fresh": "✓", "stale": "⚠", "error": "✗"}.get(rec["status"], "?")
        print(f"  {GREEN if rec['status']=='fresh' else RED}{dot}{RESET} "
              f"{rec['label']:<14} {kept} 个地点 · {rec['status']}")

    # 登录类来源：用运营方账号（config.yaml）串行抓取，抓到的按普通场馆并入 public
    scraped_keys = set()
    if include_login:
        loc2, ss2, scraped_keys = _scrape_login()
        public += loc2
        sources_status += ss2

    # 仍未接入账号的才作为锁定卡
    locked = [dict(l, **coords_of(l["name"])) for l in LOCKED if l["key"] not in scraped_keys]
    payload = {"generated_at": now_iso(), "sources": sources_status,
               "public": public, "locked": locked}
    atomic_write(OUT, payload)
    total = sum((l.get("available_total") or 0) for l in public)
    print(f"\n{GREEN}{BOLD}完成：{len(public)} 个地点（含 {len(scraped_keys)} 个登录）· "
          f"{total} 个空位 · {len(locked)} 个锁定 -> {OUT}{RESET}")
    return payload


if __name__ == "__main__":
    import sys
    if "--login-only" in sys.argv:
        generate_login()
    elif "--public-only" in sys.argv:
        generate(include_login=False)
    else:
        generate()
