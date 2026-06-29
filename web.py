#!/usr/bin/env python3
"""Flask 网页服务：显示空闲场地 + 多选提交。"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

from flask import Flask, render_template_string, request, jsonify
import yaml

from tennis import new_api, ensure_session, scan_once, resolve_dates
from submit import submit_permits

ROOT = Path(__file__).resolve().parent
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
DATA = ROOT / "data.json"

app = Flask(__name__)


def load_available():
    """读取最新的空闲数据。"""
    if not DATA.exists():
        return []
    try:
        return json.loads(DATA.read_text()).get("available", [])
    except Exception:
        return []


HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>网球场预订</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #333; }
        .controls { margin: 20px 0; padding: 15px; background: #f5f5f5; border-radius: 8px; }
        .controls button { padding: 10px 20px; margin-right: 10px; font-size: 16px; }
        button.submit-btn { background: #4CAF50; color: white; border: none; cursor: pointer; border-radius: 4px; }
        button.submit-btn:hover { background: #45a049; }
        button.submit-btn:disabled { background: #ccc; cursor: not-allowed; }
        button.clear-btn { background: #999; color: white; border: none; cursor: pointer; border-radius: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; text-align: center; border: 1px solid #ddd; }
        th { background: #f5f5f5; font-weight: 600; }
        tr:hover { background: #fafafa; }
        .free { background: #e8f5e9; cursor: pointer; }
        .free.selected { background: #81c784; color: white; font-weight: 600; }
        .occupied { background: #f5f5f5; color: #999; }
        .status { margin-top: 20px; padding: 10px; border-radius: 4px; }
        .success { background: #c8e6c9; color: #2e7d32; }
        .error { background: #ffcdd2; color: #c62828; }
        .info { background: #e3f2fd; color: #1565c0; }
        .timestamp { color: #999; font-size: 12px; margin-top: 10px; }
        .counter { font-weight: 600; margin-right: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎾 网球场预订</h1>
        <p>最后更新: <span id="timestamp">未扫描</span></p>

        <div class="controls">
            <span class="counter">已选择: <span id="selected-count">0</span> 个时段</span>
            <button class="submit-btn" id="submit-btn" onclick="submitSelected()" disabled>
                确认预订所有选中项
            </button>
            <button class="clear-btn" onclick="clearSelected()">清空选择</button>
        </div>

        <table>
            <thead>
                <tr>
                    <th>日期</th>
                    <th>时间段</th>
                    <th colspan="6">场地（点击选择）</th>
                </tr>
            </thead>
            <tbody id="table-body">
                <tr><td colspan="8" style="text-align:center; color:#999;">加载中...</td></tr>
            </tbody>
        </table>

        <div id="status" class="status" style="display:none;"></div>
    </div>

    <script>
        let selected = {};  // {key: {date, court, start, end}}
        let availableData = [];

        function loadTable() {
            fetch('/api/available')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('timestamp').textContent =
                        new Date(data.timestamp).toLocaleString('zh-CN');
                    availableData = data.available;

                    const byDate = {};
                    data.available.forEach(item => {
                        const key = item.date;
                        if (!byDate[key]) byDate[key] = {};
                        const slot = `${item.start}-${item.end}`;
                        if (!byDate[key][slot]) byDate[key][slot] = [];
                        byDate[key][slot].push(item.court);
                    });

                    let html = '';
                    Object.entries(byDate).forEach(([date, slots]) => {
                        Object.entries(slots).forEach(([slot, courts]) => {
                            html += `<tr>
                                <td>${date}</td>
                                <td>${slot}</td>`;
                            for (let c = 1; c <= 6; c++) {
                                const cellKey = `${date}|${slot}|${c}`;
                                if (courts.includes(c)) {
                                    const isSelected = cellKey in selected;
                                    const cellClass = isSelected ? 'free selected' : 'free';
                                    html += `<td class="${cellClass}" onclick="toggleSelect('${date}', '${slot}', ${c})" style="cursor:pointer;">C${c}</td>`;
                                } else {
                                    html += `<td class="occupied">-</td>`;
                                }
                            }
                            html += '</tr>';
                        });
                    });
                    document.getElementById('table-body').innerHTML = html || '<tr><td colspan="8" style="text-align:center; color:#999;">暂无空闲</td></tr>';
                });
        }

        function toggleSelect(date, slot, court) {
            const [start, end] = slot.split('-');
            const key = `${date}|${slot}|${court}`;
            if (key in selected) {
                delete selected[key];
            } else {
                selected[key] = {date, court, start, end};
            }
            updateUI();
        }

        function clearSelected() {
            selected = {};
            updateUI();
        }

        function updateUI() {
            document.getElementById('selected-count').textContent = Object.keys(selected).length;
            document.getElementById('submit-btn').disabled = Object.keys(selected).length === 0;
            loadTable();
        }

        function submitSelected() {
            if (Object.keys(selected).length === 0) {
                showStatus('请至少选择一个时段', 'error');
                return;
            }

            document.getElementById('submit-btn').disabled = true;
            showStatus('提交中，请勿关闭页面...', 'info');

            fetch('/api/submit-batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    slots: Object.values(selected),
                    num_people: prompt('请输入参加人数 (默认4人):', '4') || '4',
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    showStatus(`✓ 提交成功！${data.message || ''}`, 'success');
                    clearSelected();
                    setTimeout(loadTable, 2000);
                } else {
                    showStatus(`✗ ${data.error}`, 'error');
                }
            })
            .catch(e => showStatus(`错误: ${e.message}`, 'error'))
            .finally(() => {
                document.getElementById('submit-btn').disabled = Object.keys(selected).length === 0;
            });
        }

        function showStatus(msg, type) {
            const el = document.getElementById('status');
            el.className = `status ${type}`;
            el.textContent = msg;
            el.style.display = 'block';
        }

        // 初始加载和自动刷新
        loadTable();
        setInterval(loadTable, 30000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/available")
def api_available():
    """返回当前可用场地。"""
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "available": load_available(),
    })


@app.route("/api/submit-batch", methods=["POST"])
def api_submit_batch():
    """批量提交多个预订。"""
    data = request.json
    slots = data.get("slots", [])
    num_people = int(data.get("num_people", 4))

    if not slots:
        return jsonify({"success": False, "error": "没有选择任何时段"})

    try:
        # 按 court 分组（同一个 court 可以在一个表单里提交多个日期）
        by_court = {}
        for slot in slots:
            c = slot["court"]
            if c not in by_court:
                by_court[c] = []
            by_court[c].append(slot)

        # 对每个 court，一次性提交所有日期
        results = []
        for court, court_slots in by_court.items():
            result = submit_permits(
                court=court,
                slots=court_slots,  # [{date, start, end}, ...]
                num_people=num_people,
            )
            results.append(result)

        if all(r.get("success") for r in results):
            return jsonify({
                "success": True,
                "message": f"共提交 {sum(len(s) for s in by_court.values())} 个预订请求"
            })
        else:
            failed = [r.get("error", "未知错误") for r in results if not r.get("success")]
            return jsonify({
                "success": False,
                "error": "部分提交失败：" + "; ".join(failed[:2])
            })

    except Exception as e:
        return jsonify({"success": False, "error": f"提交错误: {str(e)[:100]}"})


def background_scan():
    """后台定期扫描。"""
    import sys
    from playwright.sync_api import sync_playwright

    interval = cfg.get("watch", {}).get("interval_minutes", 60)
    print(f"[background_scan] 启动，间隔 {interval} 分钟", file=sys.stderr, flush=True)

    while True:
        try:
            print(f"[background_scan] 准备扫描...", file=sys.stderr, flush=True)
            with sync_playwright() as p:
                api = ensure_session(p)
                scan_once(api)
                api.dispose()
                print(f"[background_scan] 扫描完成", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[background_scan] 出错: {e}", file=sys.stderr, flush=True)

        print(f"[background_scan] 等待 {interval} 分钟后再扫...", file=sys.stderr, flush=True)
        time.sleep(interval * 60)


def run_server(debug=False, port=5000):
    # 注释掉后台扫描线程，避免影响 Flask 服务
    # 用户可以手动运行 python3 tennis.py 来扫描
    # scan_thread = Thread(target=background_scan, daemon=True)
    # scan_thread.start()

    print("⚠️  后台扫描已禁用。请在另一个终端运行: python3 tennis.py --watch", file=sys.stderr, flush=True)
    app.run(debug=debug, port=port, use_reloader=False)


if __name__ == "__main__":
    run_server(debug=True, port=8000)
