#!/usr/bin/env python3
"""NYC Parks 网球场可预订信息扒取器（只读，不预订）。

抓取 https://www.nycgovparks.org/tennisreservation/ 上全部地点的：
  1) 汇总表（Reservation Courts / Walk-on Courts / First / Last Reservation）
  2) 每个地点每一天的「场地 × 时间」可用网格
     （绿色 "Reserve this time" = available；Booked / Not Available = 不可约）

用法:
  python3 nycparks.py          # 扒一次，更新 nycparks_data.json + nycparks.html
  python3 nycparks.py --open   # 扒完后自动在浏览器打开 nycparks.html

站点是纯静态 HTML（无需登录、无需提交），一次全量只需 9 个 GET 请求。
每跑一次脚本，两个文件都会被最新数据覆盖 —— 打开/刷新 nycparks.html 即为实时结果。
"""
import json
import re
import sys
import time
import webbrowser
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
BASE = "https://www.nycgovparks.org"
MAIN_URL = f"{BASE}/tennisreservation/"
DATA_JSON = ROOT / "nycparks_data.json"
OUT_HTML = ROOT / "nycparks.html"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

GREEN, DIM, RED, BOLD, RESET = "\033[32m", "\033[2m", "\033[31m", "\033[1m", "\033[0m"

# status class -> 状态语义
STATUS = {"status1": "unavailable", "status2": "available", "status3": "booked"}


def fetch(url, retries=3):
    """带真实 UA 的 GET；CloudFront 对短 UA / 过快请求会返回 403，故重试 + 间隔。"""
    for attempt in range(retries):
        try:
            req = Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            if "<TITLE>ERROR" in body or "could not be satisfied" in body:
                raise RuntimeError("被 CloudFront 拦截")
            return body
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  {DIM}重试 {url} ({e}){RESET}")
            time.sleep(2 + attempt * 2)


def strip_tags(s):
    return unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse_main(html):
    """解析首页汇总表 -> [{id,name,borough,reservation_courts,walkon_courts,
    first_reservation,last_reservation,url}]。"""
    locations = []
    for row in re.findall(r"<tr.*?</tr>", html, re.S):
        m = re.search(r"/tennisreservation/availability/(\d+)", row)
        if not m:
            continue
        loc_id = int(m.group(1))
        cells = re.findall(r"<td.*?</td>", row, re.S)
        if len(cells) < 5:
            continue
        # 地点单元格：<strong>名称</strong>, 行政区<br><a ...>
        name_m = re.search(r"<strong>(.*?)</strong>", cells[0], re.S)
        name = strip_tags(name_m.group(1)) if name_m else ""
        # 名称后面到 <br> 之间是行政区（去掉开头逗号）
        after = re.sub(r"<strong>.*?</strong>", "", cells[0].split("<br")[0], flags=re.S)
        borough = strip_tags(after).lstrip(", ").strip()

        def num(cell):
            t = strip_tags(cell)
            m2 = re.search(r"\d+", t)
            return int(m2.group()) if m2 else None

        locations.append({
            "id": loc_id,
            "name": name,
            "borough": borough,
            "reservation_courts": num(cells[1]),
            "walkon_courts": num(cells[2]),
            "first_reservation": strip_tags(cells[3]),
            "last_reservation": strip_tags(cells[4]),
            "url": f"{BASE}/tennisreservation/availability/{loc_id}",
        })
    return locations


def parse_availability(html):
    """解析单个地点的可用页 -> (note, courts, [dates])。
    每个 date: {date, label, times, grid{court:{time:{status,href}}}, available_count}。"""
    note_m = re.search(r"Online reservations are available for courts? ([^.<]+)", html)
    note = ("Courts " + note_m.group(1).strip()) if note_m else None

    # 找到所有日期 tab-pane 的起点，切成片段
    marks = [(m.group(1), m.start())
             for m in re.finditer(r'<div id="(\d{4}-\d{2}-\d{2})" class="tab-pane', html)]
    dates = []
    courts_global = []
    for i, (date, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(html)
        seg = html[start:end]

        label_m = re.search(r"<h3>(.*?)</h3>", seg, re.S)
        label = strip_tags(label_m.group(1)) if label_m else date

        thead_m = re.search(r"<thead>(.*?)</thead>", seg, re.S)
        courts = re.findall(r">Court ([\w /-]+?)<", thead_m.group(1)) if thead_m else []
        courts = [c.strip() for c in courts]
        if courts and not courts_global:
            courts_global = courts

        grid = {c: {} for c in courts}
        times = []
        tbody_m = re.search(r"<tbody>(.*?)</tbody>", seg, re.S)
        avail_count = 0
        if tbody_m:
            for tr in re.findall(r"<tr>(.*?)</tr>", tbody_m.group(1), re.S):
                tds = re.findall(r"<td.*?</td>", tr, re.S)
                if len(tds) < 2:
                    continue
                tlabel = strip_tags(tds[0])
                if not tlabel:
                    continue
                times.append(tlabel)
                for court, td in zip(courts, tds[1:]):
                    cls_m = re.search(r'class="(status\d)"', td)
                    status = STATUS.get(cls_m.group(1), "unavailable") if cls_m else "unavailable"
                    href_m = re.search(r'href="([^"]*reserv[^"]*)"', td)
                    href = (BASE + href_m.group(1)) if href_m else None
                    grid[court][tlabel] = {"status": status, "href": href}
                    if status == "available":
                        avail_count += 1
        dates.append({
            "date": date,
            "label": label,
            "times": times,
            "courts": courts,
            "grid": grid,
            "available_count": avail_count,
        })
    return note, courts_global, dates


def scrape_locations():
    """只扒取 NYC Parks 全部地点并返回 location 列表（不写文件）。"""
    print(f"{BOLD}扒取 NYC Parks 网球场…{RESET}")
    main_html = fetch(MAIN_URL)
    locations = parse_main(main_html)
    print(f"  首页解析出 {len(locations)} 个地点")

    for loc in locations:
        time.sleep(1.5)  # 礼貌间隔，避开 CloudFront 限流
        try:
            html = fetch(loc["url"])
            note, courts, dates = parse_availability(html)
            loc["note"] = note
            loc["courts"] = courts
            loc["dates"] = dates
            loc["available_total"] = sum(d["available_count"] for d in dates)
            print(f"  {GREEN}✓{RESET} {loc['name']:<48} "
                  f"{len(dates)} 天 / {loc['available_total']} 个空位")
        except Exception as e:
            loc.update({"note": None, "courts": [], "dates": [],
                        "available_total": None, "error": str(e)})
            print(f"  {RED}✗ {loc['name']}: {e}{RESET}")
    return locations


def scrape():
    locations = scrape_locations()
    payload = {
        "timestamp": datetime.now().isoformat(),
        "source": MAIN_URL,
        "locations": locations,
    }
    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    OUT_HTML.write_text(render_html(payload))
    total = sum((l.get("available_total") or 0) for l in locations)
    print(f"\n{GREEN}{BOLD}完成：{len(locations)} 个地点，共 {total} 个可预订时段{RESET}")
    print(f"  数据 -> {DATA_JSON}")
    print(f"  页面 -> {OUT_HTML}")
    return payload


def render_html(payload, title="🎾 NYC Parks 网球场可预订总览",
                cmd="python3 nycparks.py"):
    """生成自包含 HTML（数据内嵌），打开即看，无需服务器。"""
    # 转义 </ 防止数据里出现 </script> 破坏内嵌 <script> 块
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return (HTML_TEMPLATE
            .replace("__DATA__", data_json)
            .replace("__TITLE__", title)
            .replace("__CMD__", cmd))


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
  :root { --green:#5a8a2a; --green-btn:#7cae4a; --border:#ccc; --dim:#777; }
  * { box-sizing: border-box; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial;
         margin:0; padding:24px; color:#222; background:#fafafa; }
  .wrap { max-width:1200px; margin:0 auto; }
  h1 { margin:0 0 4px; font-size:24px; }
  .meta { color:var(--dim); font-size:13px; margin-bottom:20px; }
  .meta a { color:var(--green); }
  table { width:100%; border-collapse:collapse; background:#fff; }
  th, td { border:1px solid var(--border); padding:10px 12px; text-align:left; vertical-align:top; }
  th { background:#f0f0f0; font-weight:700; }
  .summary td { cursor:pointer; }
  .summary tr.loc-row:hover { background:#f5faef; }
  .locname { font-weight:700; }
  .badge { display:inline-block; min-width:20px; padding:2px 8px; border-radius:10px;
           font-size:12px; font-weight:700; color:#fff; background:var(--green-btn); }
  .badge.zero { background:#bbb; }
  .toggle { color:var(--green); font-size:12px; }
  .detail { display:none; background:#fff; }
  .detail.open { display:table-row; }
  .detail-inner { padding:16px; }
  .datetabs { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 14px; }
  .datetab { padding:6px 10px; border:1px solid var(--border); border-radius:6px;
             background:#fff; cursor:pointer; font-size:13px; white-space:nowrap; }
  .datetab.active { background:var(--green); color:#fff; border-color:var(--green); }
  .datetab .n { font-weight:700; }
  .grid td, .grid th { text-align:center; padding:6px 8px; font-size:13px; }
  .grid th { background:#f0f0f0; }
  .grid .time { font-weight:700; white-space:nowrap; background:#f7f7f7; }
  .cell-available a { display:block; background:var(--green-btn); color:#fff; text-decoration:none;
             border:1px solid #6a9a3a; border-radius:5px; padding:6px 4px; font-weight:600;
             font-size:12px; line-height:1.15; }
  .cell-available a:hover { background:var(--green); }
  .cell-booked { color:#333; }
  .cell-unavailable { color:#aaa; }
  .note { color:var(--dim); font-size:13px; margin:4px 0 0; }
  .controls { margin:0 0 16px; }
  .controls input { padding:8px 10px; font-size:14px; width:260px; border:1px solid var(--border); border-radius:6px; }
  .controls label { font-size:13px; color:var(--dim); margin-left:14px; cursor:pointer; }
  .hint { color:var(--dim); font-size:12px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="meta">
    最后更新 <b id="ts"></b> ·
    数据来源 <a id="src" href="#" target="_blank">nycgovparks.org / rioc</a> ·
    <span class="hint">重新运行 <code>__CMD__</code> 后刷新本页即更新</span>
  </div>

  <div class="controls">
    <input id="q" type="text" placeholder="搜索地点 / 行政区…" oninput="render()">
    <label><input type="checkbox" id="onlyavail" onchange="render()"> 只看有空位的地点</label>
  </div>

  <table class="summary">
    <thead>
      <tr>
        <th>Location 地点</th>
        <th>Reservation Courts</th>
        <th>Walk-on Courts</th>
        <th>First Reservation</th>
        <th>Last Reservation</th>
        <th>可预订时段</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
  <p class="hint" style="margin-top:14px;">点击任意地点行可展开「场地 × 时间」网格 —— 绿色
    <b style="color:#5a8a2a;">Reserve this time</b> 即为可预订（点击跳转官网预订页）。</p>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
document.getElementById('ts').textContent = new Date(DATA.timestamp).toLocaleString('zh-CN');
document.getElementById('src').href = DATA.source;

const openState = {};   // locId -> bool
const dateIdx  = {};    // locId -> active date index

function esc(s){ return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmtPrice(p){ const n = Number(p); return isNaN(n) ? esc(String(p)) : '$' + (n % 1 ? n.toFixed(2) : n); }

function gridTable(loc){
  const dates = loc.dates || [];
  if(!dates.length) return '<p class="note">该地点暂无在线预订日程。</p>';
  const di = Math.min(dateIdx[loc.id]||0, dates.length-1);
  const d = dates[di];
  let tabs = '<div class="datetabs">';
  dates.forEach((dd,i)=>{
    tabs += `<div class="datetab ${i===di?'active':''}" onclick="pickDate(${loc.id},${i})">`
         + `${esc(dd.date)} <span class="n">(${dd.available_count})</span></div>`;
  });
  tabs += '</div>';

  const courts = d.courts || [];
  let t = `<h3 style="margin:6px 0;">${esc(d.label)}</h3>`;
  if(loc.note) t += `<p class="note">${esc(loc.note)}</p>`;
  // 场地名若已含 "Court" 或非纯数字，则原样显示，否则加 "Court " 前缀
  const chdr = c => /court/i.test(c) || /[^0-9]/.test(c) ? esc(c) : 'Court ' + esc(c);
  t += '<div style="overflow-x:auto;"><table class="grid"><thead><tr><th></th>';
  courts.forEach(c=> t += `<th>${chdr(c)}</th>`);
  t += '</tr></thead><tbody>';
  (d.times||[]).forEach(tm=>{
    t += `<tr><td class="time">${esc(tm)}</td>`;
    courts.forEach(c=>{
      const cell = (d.grid[c]||{})[tm] || {status:'unavailable'};
      if(cell.status==='available'){
        const href = cell.href ? esc(cell.href) : '#';
        const label = cell.price != null && cell.price !== ''
          ? `Reserve · ${fmtPrice(cell.price)}` : 'Reserve this time';
        t += `<td class="cell-available"><a href="${href}" target="_blank">${label}</a></td>`;
      } else if(cell.status==='booked'){
        t += '<td class="cell-booked">Booked</td>';
      } else {
        t += '<td class="cell-unavailable">Not Available</td>';
      }
    });
    t += '</tr>';
  });
  t += '</tbody></table></div>';
  return tabs + t;
}

function pickDate(locId, i){ dateIdx[locId]=i; render(); }
function toggle(locId){ openState[locId]=!openState[locId]; render(); }

function render(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const onlyAvail = document.getElementById('onlyavail').checked;
  let html = '';
  DATA.locations.forEach(loc=>{
    const hay = (loc.name+' '+loc.borough).toLowerCase();
    if(q && !hay.includes(q)) return;
    const avail = loc.available_total || 0;
    if(onlyAvail && avail<=0) return;
    const open = !!openState[loc.id];
    html += `<tr class="loc-row" onclick="toggle(${loc.id})">
      <td><span class="locname">${esc(loc.name)}</span>, ${esc(loc.borough)}<br>
          <span class="toggle">${open?'▾ 收起':'▸ 展开网格'}</span></td>
      <td>${loc.reservation_courts ?? '—'}</td>
      <td>${loc.walkon_courts ?? '—'}</td>
      <td>${esc(loc.first_reservation||'—')}</td>
      <td>${esc(loc.last_reservation||'—')}</td>
      <td><span class="badge ${avail?'':'zero'}">${avail}</span></td>
    </tr>`;
    html += `<tr class="detail ${open?'open':''}"><td colspan="6"><div class="detail-inner">
      ${open ? gridTable(loc) : ''}</div></td></tr>`;
  });
  document.getElementById('rows').innerHTML = html ||
    '<tr><td colspan="6" style="text-align:center;color:#999;">无匹配地点</td></tr>';
}
render();
</script>
</body>
</html>
"""


def main():
    scrape()
    if "--open" in sys.argv:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
