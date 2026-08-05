/*! tennis-finder — 可嵌入的网球场空位组件（Web Component，框架无关）
 *
 * 用法（任何栈都行）：
 *   <script src="tennis-finder.js"></script>
 *   <tennis-finder src="/public_data.json"></tennis-finder>
 *
 * 属性：
 *   src   —— public_data.json 的 URL（由 pipeline.py 产出并托管）。跨域需服务端开 CORS。
 *   theme —— "dark" | "light"（可选；默认跟随系统 prefers-color-scheme）。
 *   poll  —— 自动刷新间隔（秒，可选）。设了就定时重新 fetch，页面无需刷新。
 *
 * 无 src 时，可用内嵌快照：
 *   <tennis-finder><script type="application/json">{...public_data...}</script></tennis-finder>
 *
 * 样式全部封装在 Shadow DOM 内，不会和你的页面互相影响。
 */
(function () {
  "use strict";

  const CSS = `
  :host{ all:initial; display:block; container-type:inline-size;
    --bg:#f7f8f7; --card:#fff; --ink:#111; --sub:#667; --line:#e6e8e6;
    --green:#2e7d32; --green-soft:#e7f4e8; --green-btn:#3f9c46; --chip:#f0f2f0;
    --accent:#2e7d32; --lock:#8a6d1f; --lock-soft:#fbf3dc; --shadow:0 1px 3px rgba(0,0,0,.06);
    --badge-in-bg:#e9edff; --badge-in-ink:#3a4db0; --map-bg:#e9eff4; }
  @media (prefers-color-scheme: dark){ :host{ --bg:#0f1210; --card:#181c19; --ink:#eef0ee;
    --sub:#9aa39c; --line:#2a302b; --green:#7cc47f; --green-soft:#17301a; --green-btn:#3f9c46;
    --chip:#222824; --accent:#7cc47f; --lock:#d9bd6b; --lock-soft:#2a2413;
    --shadow:0 1px 3px rgba(0,0,0,.3); --badge-in-bg:#1c2340; --badge-in-ink:#93a2f0; --map-bg:#141b22; } }
  :host([theme="dark"]){ --bg:#0f1210; --card:#181c19; --ink:#eef0ee; --sub:#9aa39c; --line:#2a302b;
    --green:#7cc47f; --green-soft:#17301a; --green-btn:#3f9c46; --chip:#222824; --accent:#7cc47f;
    --lock:#d9bd6b; --lock-soft:#2a2413; --shadow:0 1px 3px rgba(0,0,0,.3);
    --badge-in-bg:#1c2340; --badge-in-ink:#93a2f0; --map-bg:#141b22; }
  :host([theme="light"]){ --bg:#f7f8f7; --card:#fff; --ink:#111; --sub:#667; --line:#e6e8e6;
    --green:#2e7d32; --green-soft:#e7f4e8; --green-btn:#3f9c46; --chip:#f0f2f0; --accent:#2e7d32;
    --lock:#8a6d1f; --lock-soft:#fbf3dc; --shadow:0 1px 3px rgba(0,0,0,.06);
    --badge-in-bg:#e9edff; --badge-in-ink:#3a4db0; --map-bg:#e9eff4; }
  *{ box-sizing:border-box }
  .root{ position:relative; background:var(--bg); color:var(--ink); border-radius:12px; padding:14px 16px 20px;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",Arial;
    font-size:15px; line-height:1.4 }
  a{ color:inherit }
  .hrow{ display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap }
  h1{ font-size:19px;margin:0;display:flex;align-items:center;gap:8px }
  .updated{ color:var(--sub);font-size:12px } .updated .dot{ color:var(--green) }
  .btn{ border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;
    padding:7px 12px;font-size:13px;cursor:pointer } .btn:hover{ border-color:var(--green) }
  .seg{ display:inline-flex;background:var(--chip);border-radius:10px;padding:3px;margin:12px 0 }
  .seg button{ border:0;background:transparent;color:var(--sub);padding:7px 16px;border-radius:8px;
    font-size:14px;font-weight:600;cursor:pointer } .seg button.on{ background:var(--card);color:var(--ink);box-shadow:var(--shadow) }
  .filters{ display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:6px 0 4px }
  .fgroup{ display:flex;gap:6px;flex-wrap:wrap;align-items:center } .flabel{ font-size:12px;color:var(--sub) }
  .chip{ border:1px solid var(--line);background:var(--card);border-radius:999px;padding:6px 12px;
    font-size:13px;cursor:pointer;white-space:nowrap } .chip.on{ background:var(--green);border-color:var(--green);color:#fff }
  .chip .n{ opacity:.7;font-size:11px;margin-left:4px }
  input.search{ border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;
    padding:8px 14px;font-size:13px;min-width:170px;flex:1 }
  .count{ color:var(--sub);font-size:13px;margin:14px 0 8px;font-weight:600 }
  .banner{ display:flex;align-items:center;gap:10px;background:var(--lock-soft);border:1px solid var(--line);
    border-radius:12px;padding:12px 14px;margin:14px 0;font-size:14px } .banner b{ color:var(--lock) }
  .lockln{ color:var(--lock);font-weight:700;text-decoration:underline;cursor:pointer }
  .mapbox{ margin:8px 0 18px } .maphd{ font-size:14px;font-weight:700;margin:0 0 8px }
  svg.map{ width:100%;height:auto;max-height:440px;background:var(--map-bg);border:1px solid var(--line);border-radius:12px;display:block }
  svg.map a{ cursor:pointer } svg.map a circle{ transition:transform .1s } svg.map a:hover circle{ transform:scale(1.15);transform-origin:center;transform-box:fill-box }
  .lmap{ height:440px;border:1px solid var(--line);border-radius:12px;overflow:hidden }
  .lpin{ width:26px;height:26px;border-radius:50%;color:#fff;font-weight:700;font-size:12px;
    display:flex;align-items:center;justify-content:center;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4) }
  .leaflet-popup-content{ font-size:13px } .leaflet-popup-content a{ color:var(--green);font-weight:600 }
  .legend{ display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:4px 14px;margin-top:12px }
  .lgi{ display:flex;align-items:center;gap:7px;text-decoration:none;color:var(--ink);font-size:12.5px;padding:3px 0 }
  .lgi:hover{ color:var(--green) }
  .lgn{ display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;border-radius:50%;color:#fff;font-size:11px;font-weight:700;flex:none }
  /* 空位列表：宽屏多列网格（列足够宽，卡片不挤），窄屏自动单列 */
  .slotgrid{ display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:8px;margin-bottom:8px }
  @container (max-width:520px){ .slotgrid{ grid-template-columns:1fr } }
  /* 日期行：单行横向滚动，不再堆成好几行 */
  .daterow{ flex-wrap:nowrap!important;overflow-x:auto;width:100%;padding-bottom:5px }
  .daterow .chip{ flex:none }
  .hourhdr{ font-size:13px;font-weight:700;color:var(--sub);margin:18px 0 8px }
  .slot{ display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);
    border-radius:12px;padding:11px 13px;box-shadow:var(--shadow) }
  .slot .time{ font-weight:700;font-size:15px;min-width:58px } .slot .meta{ flex:1;min-width:0 }
  .slot .loc{ font-weight:600 } .slot .sub{ color:var(--sub);font-size:12.5px;margin-top:2px;display:flex;gap:6px;flex-wrap:wrap;align-items:center }
  .badge{ background:var(--chip);border-radius:6px;padding:1px 7px;font-size:11px;color:var(--sub) }
  .badge.in{ background:var(--badge-in-bg);color:var(--badge-in-ink) } .badge.out{ background:var(--green-soft);color:var(--green) }
  .badge.warn{ background:var(--lock-soft);color:var(--lock) } .price{ font-weight:700;color:var(--green) }
  .reserve{ background:var(--green-btn);color:#fff;border:0;border-radius:8px;padding:9px 14px;font-size:13px;
    font-weight:600;text-decoration:none;white-space:nowrap;cursor:pointer } .reserve:hover{ background:var(--green) }
  .reserve.alt{ background:transparent;color:var(--green);border:1px solid var(--green) } .reserve.alt:hover{ background:var(--green-soft) }
  .loccard{ background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:12px;box-shadow:var(--shadow) }
  .loccard .top{ display:flex;justify-content:space-between;align-items:flex-start;gap:12px;cursor:pointer }
  .loccard h3{ margin:0;font-size:16px } .loccard .rg{ color:var(--sub);font-size:13px;margin-top:3px }
  .statechip{ font-size:12px;font-weight:700;border-radius:999px;padding:4px 10px;white-space:nowrap }
  .st-live{ background:var(--green-soft);color:var(--green) } .st-lock{ background:var(--lock-soft);color:var(--lock) }
  .avail-num{ font-weight:800;color:var(--green);font-size:15px }
  .locked-actions{ display:flex;gap:8px;flex-wrap:wrap;margin-top:12px }
  .locked-actions a{ font-size:13px;border:1px solid var(--line);border-radius:8px;padding:8px 12px;text-decoration:none }
  .locked-actions a.primary{ background:var(--ink);color:var(--bg);border-color:var(--ink) }
  .grid-wrap{ overflow-x:auto;margin-top:12px } table.grid{ border-collapse:collapse;width:100%;font-size:12.5px }
  table.grid th,table.grid td{ border:1px solid var(--line);padding:5px 7px;text-align:center } table.grid th{ background:var(--chip) }
  .grid .time{ font-weight:700;white-space:nowrap;background:var(--chip) }
  .c-av a{ display:block;background:var(--green-btn);color:#fff;text-decoration:none;border-radius:5px;padding:5px 3px;font-weight:600;font-size:11px }
  .c-bk{ color:var(--sub) } .c-un{ color:#bbb }
  .datetabs{ display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 10px }
  .empty{ color:var(--sub);text-align:center;padding:40px 0 } .foot{ color:var(--sub);font-size:12px;text-align:center;margin-top:22px }
  .btn[disabled]{ opacity:.6;cursor:default }
  .toast{ position:absolute;left:50%;bottom:16px;transform:translateX(-50%) translateY(8px);
    background:var(--ink);color:var(--bg);padding:9px 16px;border-radius:10px;font-size:13px;
    box-shadow:0 4px 14px rgba(0,0,0,.25);opacity:0;pointer-events:none;transition:.2s;z-index:50 }
  .toast.show{ opacity:.95;transform:translateX(-50%) translateY(0) }
  @container (max-width:560px){ .slot .time{ min-width:56px;font-size:14px } h1{ font-size:17px } }
  `;

  const LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
  const LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
  const esc = s => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtPrice = p => { const n = Number(p); return isNaN(n) ? esc(String(p)) : "$" + (n % 1 ? n.toFixed(2) : n); };
  const agoText = ts => { if (!ts) return "—"; const m = Math.round((Date.now() - new Date(ts)) / 60000);
    return m < 1 ? "刚刚" : m < 60 ? m + " 分钟前" : Math.round(m / 60) + " 小时前"; };
  // 兼容 "7:00 AM" 与 NYC Parks 的 "6:00 a.m." 两种格式
  const toMin = t => { const m = (t || "").match(/(\d+):(\d+)\s*([ap])\.?\s*m/i); if (!m) return 0;
    let h = (+m[1]) % 12; if (/p/i.test(m[3])) h += 12; return h * 60 + (+m[2]); };
  const courtType = n => /indoor/i.test(n) ? "Indoor" : /outdoor/i.test(n) ? "Outdoor" : "";
  // 纽约当前时间（今天日期 + 向下取整到 30 分钟），用于隐藏今日已过去的时段
  const etNow = () => { const p = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York",
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
      .formatToParts(new Date()).reduce((a, x) => (a[x.type] = x.value, a), {});
    let h = +p.hour; if (h === 24) h = 0; const min = h * 60 + (+p.minute);
    return { today: `${p.year}-${p.month}-${p.day}`, floorMin: min - (min % 30) }; };
  const notPast = (x, et) => x.date > et.today || (x.date === et.today && x.min >= et.floorMin);

  class TennisFinder extends HTMLElement {
    connectedCallback() {
      if (this._init) return; this._init = true;
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML =
        `<style>${CSS}</style><div class="root">
          <div class="hrow">
            <h1>🎾 NYC Tennis Finder</h1>
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
              <span class="updated"><span class="dot">●</span> 更新于 <b class="ago"></b></span>
              <span class="updated sources"></span>
              <button class="btn" data-act="reload">↻ 刷新</button>
            </div>
          </div>
          <div class="hrow" style="margin-top:4px">
            <div class="seg">
              <button data-act="view" data-v="time" class="on">按时间 By time</button>
              <button data-act="view" data-v="loc">按地点 By place</button>
            </div>
            <input class="search" placeholder="搜索场馆 Search…">
          </div>
          <div class="filters"></div>
          <div class="content"></div>
          <div class="foot">空位仅供查看；预订请到各场馆官网完成，均需该站账号（如 CourtReserve / NYC Parks）。显示为「开放」以官网规则为准。</div>
        </div>`;
      this.state = { VIEW: "time", D: null, SLOTS: [], DATES: [], REGIONS: [], OPEN: {},
        F: { date: null, tods: new Set(), regions: new Set(), types: new Set() } };
      this._wire();
      // 有 src 立即拉取；内联数据需等文档解析完（DOMContentLoaded 后子节点才完整）
      if (this.getAttribute("src")) this.load();
      else if (document.readyState === "loading")
        document.addEventListener("DOMContentLoaded", () => this.load(), { once: true });
      else this.load();
      const poll = +this.getAttribute("poll");
      if (poll > 0) this._timer = setInterval(() => this.load(true), poll * 1000);
    }
    disconnectedCallback() { if (this._timer) clearInterval(this._timer); }

    $(s) { return this.shadowRoot.querySelector(s); }

    _wire() {
      this.shadowRoot.addEventListener("click", e => {
        const el = e.target.closest("[data-act]"); if (!el) return;
        const act = el.dataset.act;
        if (act === "reload") this._refresh(el);
        else if (act === "view") { this.state.VIEW = el.dataset.v;
          this.shadowRoot.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.v === el.dataset.v));
          this.render(); }
        else if (act === "setf") { this.state.F[el.dataset.k] = el.dataset.v; this.render(); }
        else if (act === "toggleset") { const s = this.state.F[el.dataset.k], v = el.dataset.v;
          v === "__all__" ? s.clear() : (s.has(v) ? s.delete(v) : s.add(v)); this.render(); }
        else if (act === "toggleloc") { const id = el.dataset.id;
          this.state.OPEN[id] = !this.state.OPEN[id]; this.render(); }
        else if (act === "locdate") { e.stopPropagation();
          this.state.OPEN["d" + el.dataset.id] = +el.dataset.i; this.render(); }
      });
      this.$(".search").addEventListener("input", () => this.render());
    }

    async load(refresh) {
      const src = this.getAttribute("src");
      try {
        let D;
        if (src) {
          const url = src + (src.includes("?") ? "&" : "?") + "_=" + Date.now(); // 破缓存
          const r = await fetch(url, { cache: "no-store" });
          if (!r.ok) throw new Error("HTTP " + r.status);
          D = await r.json();
        } else {
          const inline = this.querySelector('script[type="application/json"]');
          if (inline) D = JSON.parse(inline.textContent);
        }
        if (!D || !D.public) throw new Error("数据为空或格式不符");
        // 混合模式：另拉登录场馆数据（Mac 端产出），并入 public 并解锁对应锁定卡
        const loginSrc = this.getAttribute("login-src");
        if (loginSrc) {
          try {
            const lr = await fetch(loginSrc + (loginSrc.includes("?") ? "&" : "?") + "_=" + Date.now(), { cache: "no-store" });
            if (lr.ok) {
              const ld = await lr.json(), locs = (ld && ld.locations) || [];
              if (locs.length) {
                const keys = new Set(locs.map(l => l.source));
                D.public = [...(D.public || []), ...locs];
                D.locked = (D.locked || []).filter(l => !keys.has(l.key));
                D.sources = [...(D.sources || []), ...((ld && ld.sources) || [])];
              }
            }
          } catch (e) { /* 登录数据不可用则忽略，公开数据照常显示 */ }
        }
        this.state.D = D; this._prep(); this.render();
      } catch (e) {
        if (!refresh || !this.state.D) this.$(".content").innerHTML =
          `<div class="empty">加载数据失败：${esc(e.message)}<br><small>请检查 src 与 CORS 设置。</small></div>`;
      }
    }

    async _refresh(btn) {
      if (this._refreshing) return;
      this._refreshing = true;
      const before = this.state.D && this.state.D.generated_at;
      if (btn) { btn.disabled = true; btn.textContent = "⟳ 刷新中…"; }
      await this.load(true);
      if (btn) { btn.disabled = false; btn.textContent = "↻ 刷新"; }
      const after = this.state.D && this.state.D.generated_at;
      const msg = after && after !== before ? "已更新到最新数据"
        : "已是最新 · 数据更新于 " + agoText(after) + "（后台每小时刷新一次）";
      this._toast(msg);
      this._refreshing = false;
    }

    _toast(msg) {
      let t = this.$(".toast");
      if (!t) { t = document.createElement("div"); t.className = "toast"; this.$(".root").appendChild(t); }
      t.textContent = msg; t.classList.add("show");
      clearTimeout(this._toastT);
      this._toastT = setTimeout(() => t.classList.remove("show"), 2600);
    }

    _prep() {
      const D = this.state.D;
      this.$(".ago").textContent = agoText(D.generated_at);
      const dot = { fresh: "🟢", stale: "⚠️", error: "❌" };
      this.$(".sources").innerHTML = (D.sources || []).map(s => `${dot[s.status] || "•"} ${esc(s.label)}`).join("　");
      const S = [];
      (D.public || []).forEach(loc => (loc.dates || []).forEach(d => {
        const courts = d.courts || [];
        courts.forEach(c => (d.times || []).forEach(tm => {
          const cell = ((d.grid || {})[c] || {})[tm];
          if (!cell || cell.status !== "available") return;
          S.push({ locId: loc.id, loc: loc.name, region: loc.region, court: c, date: d.date,
            dateLabel: d.label, time: tm, min: toMin(tm), type: courtType(c) || loc.default_type || "", price: cell.price,
            href: cell.href || loc.url, kind: loc.book_kind, site: loc.site });
        }));
      }));
      this.state.SLOTS = S;
      const et = etNow();
      // 只保留今天及以后的日期（数据陈旧时也不会显示过去的日子）
      this.state.DATES = [...new Set(S.map(s => s.date))].filter(d => d >= et.today).sort();
      this.state.REGIONS = [...new Set((D.public || []).map(l => l.region))].sort();
      // 选中日期失效/跨天则重置，优先选“还有未过时段”的最早一天
      const firstOpen = this.state.DATES.find(dt => S.some(s => s.date === dt && notPast(s, et)));
      if (!this.state.DATES.includes(this.state.F.date)) this.state.F.date = firstOpen || this.state.DATES[0];
    }

    render() {
      if (!this.state.D) return;
      this._renderFilters();
      this.state.VIEW === "time" ? this._renderTime() : this._renderLoc();
    }

    // 多选组：All 清空集合；其余在集合里增删（区域也用它 → 天然多选）
    _setGroup(label, k, opts) {
      const s = this.state.F[k];
      let h = `<div class="fgroup"><span class="flabel">${label}</span>`;
      h += `<span class="chip ${s.size === 0 ? "on" : ""}" data-act="toggleset" data-k="${k}" data-v="__all__">全部 All</span>`;
      opts.forEach(([v, txt]) => h += `<span class="chip ${s.has(v) ? "on" : ""}" data-act="toggleset" data-k="${k}" data-v="${esc(v)}">${txt}</span>`);
      return h + "</div>";
    }
    _regionGroup() {
      let h = '<div class="fgroup"><span class="flabel">区域 Area</span>';
      const s = this.state.F.regions;
      h += `<span class="chip ${s.size === 0 ? "on" : ""}" data-act="toggleset" data-k="regions" data-v="__all__">全部 All</span>`;
      this.state.REGIONS.forEach(r => h += `<span class="chip ${s.has(r) ? "on" : ""}" data-act="toggleset" data-k="regions" data-v="${esc(r)}">${esc(r)}</span>`);
      return h + "</div>";
    }
    _renderFilters() {
      const el = this.$(".filters"), st = this.state;
      if (st.VIEW === "loc") { el.innerHTML = this._regionGroup(); return; }  // 按地点也能筛区域
      const et = etNow();
      let h = '<div class="fgroup daterow"><span class="flabel">日期 Date</span>';
      st.DATES.forEach(dt => { const n = st.SLOTS.filter(s => s.date === dt && notPast(s, et)).length;
        const lbl = new Date(dt + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
        h += `<span class="chip ${st.F.date === dt ? "on" : ""}" data-act="setf" data-k="date" data-v="${dt}">${lbl}<span class="n">${n}</span></span>`; });
      h += "</div>";
      h += this._setGroup("时段 Time", "tods", [["am", "上午 Morning"], ["pm", "下午 Afternoon"], ["eve", "晚上 Evening"]]);
      h += this._regionGroup();
      h += this._setGroup("类型 Type", "types", [["Indoor", "室内 Indoor"], ["Outdoor", "室外 Outdoor"]]);
      el.innerHTML = h;
    }

    _lockedBanner() {
      const L = this.state.D.locked || []; if (!L.length) return "";
      const links = L.map(l => `<a href="${esc(l.login_url)}" target="_blank" rel="noopener" class="lockln">${esc(l.name.split(" ")[0])} ↗</a>`).join(" · ");
      return `<div class="banner">🔒 <span>连接账号解锁 Connect to unlock：${links}</span></div>`;
    }

    _renderTime() {
      const st = this.state, q = this.$(".search").value.trim().toLowerCase();
      const bucket = m => m < 720 ? "am" : (m < 1020 ? "pm" : "eve");
      const et = etNow();
      let s = st.SLOTS.filter(x => x.date === st.F.date && notPast(x, et)
        && (st.F.tods.size === 0 || st.F.tods.has(bucket(x.min)))
        && (st.F.regions.size === 0 || st.F.regions.has(x.region))
        && (st.F.types.size === 0 || st.F.types.has(x.type))
        && (!q || x.loc.toLowerCase().includes(q)));
      s.sort((a, b) => a.min - b.min || a.loc.localeCompare(b.loc) || a.court.localeCompare(b.court));
      const dl = s.length ? s[0].dateLabel : (st.F.date ? new Date(st.F.date + "T00:00:00").toDateString() : "");
      let h = this._lockedBanner() + `<div class="count">${esc(dl)} · 共 ${s.length} 个空位</div>`;
      if (!s.length) { this.$(".content").innerHTML = h + '<div class="empty">该筛选下暂无空位，换个日期或时段试试。</div>'; return; }
      let last = null, open = false;
      s.forEach(x => {
        const hr = Math.floor(x.min / 60);
        if (hr !== last) { if (open) h += "</div>"; last = hr;
          h += `<div class="hourhdr">${new Date(0, 0, 0, hr).toLocaleTimeString("en-US", { hour: "numeric" })}</div><div class="slotgrid">`; open = true; }
        const tb = x.type === "Indoor" ? '<span class="badge in">Indoor</span>' : x.type === "Outdoor" ? '<span class="badge out">Outdoor</span>' : "";
        const pr = x.price != null && x.price !== "" ? `<span class="price">${fmtPrice(x.price)}</span>` : "";
        const facility = x.kind === "facility";
        const note = facility ? '<span class="badge warn">官网订·需账号</span>' : "";
        const btn = facility
          ? `<a class="reserve alt" href="${esc(x.href)}" target="_blank" rel="noopener" title="跳转到 ${esc(x.site)} 官网预订。该站不支持直达此时段，请在官网选 ${esc(x.dateLabel)} · ${esc(x.type || "")} · ${esc(x.court)}。">在 ${esc(x.site)} 订 ↗</a>`
          : `<a class="reserve" href="${esc(x.href)}" target="_blank" rel="noopener">Reserve ↗</a>`;
        h += `<div class="slot"><div class="time">${esc(x.time)}</div>
          <div class="meta"><div class="loc">${esc(x.loc)}</div>
          <div class="sub"><span class="badge">${esc(x.region)}</span>${tb}<span>${esc(x.court)}</span>${pr}${note}</div></div>${btn}</div>`;
      });
      if (open) h += "</div>";
      this.$(".content").innerHTML = h;
    }

    _gridFor(loc) {
      const st = this.state, dates = loc.dates || []; if (!dates.length) return '<div class="rg">暂无日程</div>';
      const di = Math.min(st.OPEN["d" + loc.id] || 0, dates.length - 1), d = dates[di];
      let h = '<div class="datetabs">';
      dates.forEach((dd, i) => h += `<span class="chip ${i === di ? "on" : ""}" data-act="locdate" data-id="${loc.id}" data-i="${i}">${esc(dd.date)}<span class="n">${dd.available_count}</span></span>`);
      h += '</div><div class="grid-wrap"><table class="grid"><thead><tr><th></th>';
      const chdr = c => /court/i.test(c) || /[^0-9]/.test(c) ? esc(c) : "Court " + esc(c);
      (d.courts || []).forEach(c => h += `<th>${chdr(c)}</th>`); h += "</tr></thead><tbody>";
      const facility = loc.book_kind === "facility";
      const ttl = facility ? ` title="在 ${esc(loc.site)} 官网预订（该站不支持直达，请自选日期/场地）"` : "";
      (d.times || []).forEach(tm => { h += `<tr><td class="time">${esc(tm)}</td>`;
        (d.courts || []).forEach(c => { const cell = ((d.grid || {})[c] || {})[tm] || { status: "un" };
          if (cell.status === "available") { const p = cell.price != null && cell.price !== "" ? "· " + fmtPrice(cell.price) : (facility ? "官网↗" : "Reserve");
            h += `<td class="c-av"><a href="${esc(cell.href || loc.url)}" target="_blank" rel="noopener"${ttl}>${p}</a></td>`; }
          else if (cell.status === "booked") h += '<td class="c-bk">Booked</td>';
          else h += '<td class="c-un">—</td>'; });
        h += "</tr>"; });
      return h + "</tbody></table></div>";
    }

    _venues(pub, lock) {
      const all = [...pub, ...lock.map(l => ({ ...l, _locked: true }))].filter(l => l.lat != null && l.lng != null);
      all.sort((a, b) => (a.region || "").localeCompare(b.region || "") || a.name.localeCompare(b.name));
      return all;
    }
    _gmapUrl(l) { return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(l.name + " tennis " + (l.region || "")); }
    _legendHtml(all) {
      return '<div class="legend">' + all.map((l, i) => {
        const col = l._locked ? "#c79a2e" : "#3f9c46";
        return `<a class="lgi" href="${this._gmapUrl(l)}" target="_blank" rel="noopener"><span class="lgn" style="background:${col}">${i + 1}</span><span>${esc(l.name)} <span class="rg">${esc(l.region || "")}</span></span></a>`;
      }).join("") + "</div>";
    }
    _schematicSvg(all) {  // Leaflet 不可用时的自包含回退（示意图）
      const W = 720, H = 460, pad = 40;
      const lats = all.map(l => l.lat), lngs = all.map(l => l.lng);
      const laMin = Math.min(...lats), laMax = Math.max(...lats), lgMin = Math.min(...lngs), lgMax = Math.max(...lngs);
      const dLa = (laMax - laMin) || 0.01, dLg = (lgMax - lgMin) || 0.01;
      const X = l => (pad + (l.lng - lgMin) / dLg * (W - 2 * pad)).toFixed(0);
      const Y = l => (pad + (laMax - l.lat) / dLa * (H - 2 * pad)).toFixed(0);
      let grid = "";
      for (let i = 1; i < 5; i++) { const gx = (W / 5 * i).toFixed(0), gy = (H / 5 * i).toFixed(0);
        grid += `<line x1="${gx}" y1="0" x2="${gx}" y2="${H}" style="stroke:var(--line)" opacity=".5"/><line x1="0" y1="${gy}" x2="${W}" y2="${gy}" style="stroke:var(--line)" opacity=".5"/>`; }
      let pins = "";
      all.forEach((l, i) => { const x = X(l), y = Y(l), col = l._locked ? "#c79a2e" : "#3f9c46";
        pins += `<a href="${this._gmapUrl(l)}" target="_blank" rel="noopener"><circle cx="${x}" cy="${y}" r="13" fill="${col}" stroke="#fff" stroke-width="2"/><text x="${x}" y="${+y + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">${i + 1}</text><title>${esc(l.name)}</title></a>`; });
      return `<div class="grid-wrap"><svg viewBox="0 0 ${W} ${H}" class="map">${grid}${pins}</svg></div>`;
    }
    _mapSection(all) {
      if (all.length < 2) return "";
      const body = this._leafletReady ? '<div class="lmap"></div>' : this._schematicSvg(all);
      return `<div class="mapbox"><div class="maphd">🗺 场馆位置 Map <span class="rg">· 🟢 空位可见 · 🟡 需账号才能查看 · 点标记查看</span></div>${body}${this._legendHtml(all)}</div>`;
    }
    async _ensureLeaflet() {  // 按需从 CDN 加载 Leaflet（嵌入环境可用；Artifact 被 CSP 挡则回退示意图）
      if (this._leafletReady) return true;
      if (this._leafletTried) return false;
      this._leafletTried = true;
      try {
        if (!window.L) await new Promise((res, rej) => { const s = document.createElement("script"); s.src = LEAFLET_JS; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
        const css = await (await fetch(LEAFLET_CSS)).text();
        const st = document.createElement("style"); st.textContent = css; this.shadowRoot.appendChild(st);
        this._leafletReady = !!window.L;
        return this._leafletReady;
      } catch (e) { return false; }
    }
    _initLeaflet(all) {
      const el = this.$(".lmap"), L = window.L; if (!el || !L) return;
      if (this._map) { try { this._map.remove(); } catch (e) {} this._map = null; }
      const map = L.map(el, { scrollWheelZoom: false });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
      all.forEach((l, i) => { const col = l._locked ? "#c79a2e" : "#3f9c46";
        const icon = L.divIcon({ className: "", html: `<div class="lpin" style="background:${col}">${i + 1}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });
        L.marker([l.lat, l.lng], { icon }).addTo(map).bindPopup(`<b>${esc(l.name)}</b><br>${esc(l.region || "")}<br><a href="${this._gmapUrl(l)}" target="_blank" rel="noopener">Google 地图 ↗</a>`);
      });
      try { map.fitBounds(all.map(l => [l.lat, l.lng]), { padding: [30, 30], maxZoom: 13 }); } catch (e) {}
      this._map = map;
      setTimeout(() => map.invalidateSize(), 60);
    }

    _renderLoc() {
      const st = this.state, q = this.$(".search").value.trim().toLowerCase();
      const inRegion = l => st.F.regions.size === 0 || st.F.regions.has(l.region);
      const match = l => (!q || (l.name + l.region).toLowerCase().includes(q)) && inRegion(l);
      const pub = (st.D.public || []).filter(match);
      const lock = (st.D.locked || []).filter(match);
      const mapVenues = this._venues(pub, lock);
      let h = this._mapSection(mapVenues);
      pub.sort((a, b) => (b.available_total || 0) - (a.available_total || 0))
        .forEach(loc => {
          const open = !!st.OPEN[loc.id];
          const fresh = loc.stale ? '<span class="statechip st-lock">⚠️ 数据较旧</span>'
            : `<span class="statechip st-live">🟢 ${agoText(loc.updated_at)}</span>`;
          h += `<div class="loccard"><div class="top" data-act="toggleloc" data-id="${loc.id}">
            <div><h3>${esc(loc.name)}</h3><div class="rg">${esc(loc.region)} · ${loc.reservation_courts || "?"} 片场</div></div>
            <div style="text-align:right">${fresh}<div style="margin-top:6px"><span class="avail-num">${loc.available_total || 0}</span> <span class="rg">空位</span></div></div>
            </div>${open ? this._gridFor(loc) : ""}</div>`;
        });
      lock.forEach(l => {
        h += `<div class="loccard"><div class="top">
          <div><h3>${esc(l.name)}</h3><div class="rg">${esc(l.region)} · ${esc(l.blurb)}${l.has_price ? " 💲" : ""}</div></div>
          <span class="statechip st-lock">🔒 需连接账号</span></div>
          <div class="locked-actions"><a class="primary" href="${esc(l.login_url)}" target="_blank" rel="noopener">去官网登录 / 注册 ↗</a></div></div>`;
      });
      this.$(".content").innerHTML = h;
      if (mapVenues.length >= 2) {
        if (this._leafletReady) this._initLeaflet(mapVenues);
        else this._ensureLeaflet().then(ok => { if (ok && this.state.VIEW === "loc") this.render(); });
      }
    }
  }

  if (!customElements.get("tennis-finder")) customElements.define("tennis-finder", TennisFinder);
})();
