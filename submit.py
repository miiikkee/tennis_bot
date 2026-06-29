#!/usr/bin/env python3
"""批量提交多个日期的预订请求。"""
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
BASE = cfg["account"]["base_url"]
AUTH = ROOT / "auth_state.json"

COURT_SITES = {
    1: "3c9230f0-9e2c-4ff0-8ad7-5300eb475af5",
    2: "f96d68ab-adea-42cb-8b42-c45a89e7ae2b",
    3: "5633e568-7db6-4e84-a02b-3ac827406bfc",
    4: "3e83f44d-ed76-4a95-a73e-e9c5dcfa6e55",
    5: "2158c5f2-8734-4755-b2ef-2627d4a5f0b1",
    6: "f3794e38-71ac-4440-9f3b-1adce02df1d7",
}


def submit_permits(court: int, slots: list, num_people: int) -> dict:
    """
    为一个 court 批量提交多个日期的预订。

    Args:
        court: 1-6
        slots: [{"date": "2026-06-27", "start": "18:00", "end": "20:00"}, ...]
        num_people: 活动人数

    Returns:
        {"success": True} 或 {"success": False, "error": "..."}
    """
    def log(msg):
        print(f"[submit] {msg}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=str(AUTH))
        page = ctx.new_page()

        try:
            # === Step 1: 进入新申请页 ===
            log("Step 1: 进入 /Permits/New")
            page.goto(f"{BASE}/Permits/New", wait_until="networkidle")
            if "/Account/Login" in page.url:
                browser.close()
                return {"success": False, "error": "会话过期"}

            log("Step 1.5: 等待 activity 输入框")
            page.wait_for_selector("#activity", timeout=5000)

            # === Step 2: 填 Activity ===
            log("Step 2: 填 activity = 'tennis play'")
            page.fill("#activity", "tennis play")

            # === Step 3: 点 "Add Facility" ===
            log("Step 3: 点 Add Facility 按钮")
            page.click("#addFacilitySet")
            log("Step 3.5: 等待 #addFacility 出现（可能隐藏）")
            page.wait_for_selector("#addFacility", state="attached", timeout=5000)

            # 强制显示表单（以防被 CSS display:none 隐藏）
            log("Step 3.6: 用 JS 强制显示表单")
            page.evaluate("() => { const f = document.getElementById('addFacility'); if(f) f.style.display = 'block'; }")
            page.wait_for_timeout(500)

            # === Step 4: 选 Site（Court）===
            log(f"Step 4: 选 court {court} (site={COURT_SITES[court]})")
            site_guid = COURT_SITES[court]
            page.select_option("#site", site_guid)
            log("Step 4.5: 等待 facility checkbox 出现（可能隐藏）")
            page.wait_for_selector(".facilityList input[type='checkbox']", state="attached", timeout=5000)
            page.wait_for_timeout(500)

            # === Step 5: 勾选 Tennis Courts ===
            log("Step 5: 勾选 Tennis Courts checkbox")
            checkbox = page.query_selector(".facilityList input[type='checkbox']")
            if checkbox:
                # 用 JavaScript 直接修改 checked 属性（绕过可见性问题）
                log("  5.1: 用 JS 直接设置 checkbox.checked = true")
                page.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles: true})); }", checkbox)
                page.wait_for_timeout(300)
            else:
                browser.close()
                log("ERROR: 找不到 Tennis Courts checkbox")
                return {"success": False, "error": "找不到 Tennis Courts checkbox"}

            # === Step 6: 添加所有日期 ===
            log(f"Step 6: 准备添加 {len(slots)} 个日期")
            for i, slot in enumerate(slots):
                date = slot["date"]
                start = slot["start"]
                end = slot["end"]

                log(f"  6.{i}: 添加日期 {date} {start}-{end}")

                # 如果不是第一个，点 "+ Add another date"
                if i > 0:
                    log(f"    6.{i}.0: 点 Add another date 按钮")
                    add_date_btn = page.query_selector("button:has-text('+ Add another date')")
                    if add_date_btn:
                        add_date_btn.click()
                        page.wait_for_timeout(500)
                    else:
                        log(f"    WARNING: 找不到 Add another date 按钮")

                # 获取或创建日期输入框
                log(f"    6.{i}.1: 获取或创建日期输入框")

                # 先尝试找日期表格
                date_table = page.query_selector("#eventDates tbody")
                if not date_table:
                    log(f"    ERROR: 找不到 #eventDates tbody")
                    browser.close()
                    return {"success": False, "error": "找不到日期表格"}

                # 获取现有的日期输入框
                date_inputs = page.query_selector_all("#eventDates tbody input[type='text']")
                log(f"    6.{i}.1: 找到 {len(date_inputs)} 个日期输入框")

                # 如果没有足够的行，点"+ Add another date"创建新行
                if i >= len(date_inputs):
                    log(f"    6.{i}.1.5: 需要创建第 {i+1} 行，点 '+ Add another date'")
                    for _ in range(i - len(date_inputs) + 1):
                        add_btn = page.query_selector("button:has-text('+ Add another date')")
                        if add_btn:
                            add_btn.click()
                            page.wait_for_timeout(300)
                        else:
                            log(f"    WARNING: 找不到 '+ Add another date' 按钮")
                            break
                    date_inputs = page.query_selector_all("#eventDates tbody input[type='text']")
                    log(f"    6.{i}.1.7: 创建后有 {len(date_inputs)} 个日期输入框")

                date_input = date_inputs[i] if i < len(date_inputs) else None

                if not date_input:
                    browser.close()
                    log(f"    ERROR: 无法找到或创建第 {i+1} 个日期输入框")
                    return {"success": False, "error": f"无法找到或创建第 {i+1} 个日期输入框"}

                # 转换日期格式：2026-06-27 → 6/27/2026
                parts = date.split("-")
                date_str = f"{int(parts[1])}/{int(parts[2])}/{parts[0]}"
                log(f"    6.{i}.2: 填日期 {date_str}")
                date_input.click()
                date_input.fill(date_str)
                page.wait_for_timeout(300)

                # 关闭日期选择器（按 Escape 键）
                log(f"    6.{i}.2.5: 关闭日期选择器（按 Escape）")
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)

                # 设置开始时间
                start_h, start_m = map(int, start.split(":"))
                log(f"    6.{i}.3: 设置开始时间 {start_h}:{start_m}")
                start_hour_sels = page.query_selector_all("#eventDates tbody select[name='startHour']")
                start_min_sels = page.query_selector_all("#eventDates tbody select[name='startMinute']")
                if i < len(start_hour_sels):
                    start_hour_sels[i].select_option(str(start_h))
                if i < len(start_min_sels):
                    start_min_sels[i].select_option(str(start_m).zfill(2))

                # 设置结束时间
                end_h, end_m = map(int, end.split(":"))
                log(f"    6.{i}.4: 设置结束时间 {end_h}:{end_m}")
                end_hour_sels = page.query_selector_all("#eventDates tbody select[name='endHour']")
                end_min_sels = page.query_selector_all("#eventDates tbody select[name='endMinute']")
                if i < len(end_hour_sels):
                    end_hour_sels[i].select_option(str(end_h))
                if i < len(end_min_sels):
                    end_min_sels[i].select_option(str(end_m).zfill(2))

                page.wait_for_timeout(200)

            # === Step 7: 点 "Add & Confirm" ===
            log("Step 7: 准备点 Add & Confirm 按钮")

            # 检查表单是否还可见
            form_visible = page.evaluate("() => document.getElementById('addFacility').style.display !== 'none'")
            log(f"  表单可见: {form_visible}")

            # 所有可能的按钮选择器
            selectors = [
                "button:has-text('Add & Confirm')",
                "button:contains('Add & Confirm')",
                "#addFacility button[type='submit']",
                "button:has-text('Add')",
            ]

            add_confirm_btn = None
            for sel in selectors:
                try:
                    add_confirm_btn = page.query_selector(sel)
                    if add_confirm_btn:
                        log(f"  找到按钮用选择器: {sel}")
                        break
                except:
                    pass

            if not add_confirm_btn:
                # 最后的手段：查找所有按钮，看看哪个有 "Add" 或 "Confirm" 文本
                all_btns = page.query_selector_all("button")
                log(f"  页面共有 {len(all_btns)} 个按钮")
                for i, btn in enumerate(all_btns):
                    text = btn.text_content()
                    log(f"    按钮 {i}: {text[:50]}")
                    if "Add" in text and "Confirm" in text:
                        add_confirm_btn = btn
                        log(f"  找到按钮在位置 {i}")
                        break

            if add_confirm_btn:
                log("Step 7.1: 点击 Add & Confirm")
                add_confirm_btn.click()
                log("Step 7.5: 等待服务器响应 (conflict check)")
                page.wait_for_timeout(2000)
                log(f"  当前 URL: {page.url}")
            else:
                browser.close()
                log("ERROR: 找不到 Add & Confirm 按钮")
                return {"success": False, "error": "找不到 Add & Confirm 按钮"}

            # 检查冲突错误
            log("Step 7.6: 检查冲突错误")
            error_labels = page.query_selector_all("label.error")
            if error_labels and any("not available" in el.text_content() for el in error_labels):
                browser.close()
                log("ERROR: 时段已被占用")
                return {"success": False, "error": "某些时段已被占用"}

            # === Step 8: 等待问卷页面 ===
            log("Step 8: 等待 permitQuestionsForm")
            page.wait_for_selector("#permitQuestionsForm", state="attached", timeout=5000)
            page.wait_for_timeout(500)

            # === Step 9: 填问卷 ===
            log("Step 9: 填问卷")
            inputs = page.query_selector_all("#permitQuestionsForm input[type='text']")
            selects = page.query_selector_all("#permitQuestionsForm select")
            log(f"  找到 {len(inputs)} 个 text inputs，{len(selects)} 个 selects")

            if len(inputs) > 0:
                log(f"    填 inputs[0] = 'tennis play'")
                inputs[0].fill("tennis play")
            if len(inputs) > 1:
                log(f"    填 inputs[1] = '{num_people}'")
                inputs[1].fill(str(num_people))
            for i in range(2, min(6, len(inputs))):
                log(f"    填 inputs[{i}] = 'no'")
                inputs[i].fill("no")

            if len(selects) > 0:
                log(f"    选 selects[0] = 'No'")
                selects[0].select_option("No")
            if len(selects) > 1:
                log(f"    选 selects[1] = 'No'")
                selects[1].select_option("No")

            # === Step 10: 同意条款 ===
            log("Step 10: 勾选同意条款")
            terms_checkbox = page.query_selector("#acceptTerms")
            if terms_checkbox:
                terms_checkbox.check()
                page.wait_for_timeout(200)
            else:
                log("WARNING: 找不到同意条款 checkbox")

            # === Step 11: 提交 ===
            log("Step 11: 点 Submit 按钮")
            submit_btn = page.query_selector("button:has-text('Submit')")
            if submit_btn:
                submit_btn.click()
                log("Step 11.5: 等待页面响应")
                page.wait_for_load_state("networkidle", timeout=15000)
            else:
                browser.close()
                log("ERROR: 找不到 Submit 按钮")
                return {"success": False, "error": "找不到 Submit 按钮"}

            log("Step 12: 检查提交结果")
            page.wait_for_timeout(500)

            if "/Account/Login" in page.url:
                browser.close()
                log("ERROR: 提交中会话过期")
                return {"success": False, "error": "提交中会话过期"}

            errors = page.query_selector_all(".error, [role='alert']")
            if errors:
                for err in errors:
                    text = err.text_content().lower()
                    if "fail" in text or "error" in text:
                        browser.close()
                        log(f"ERROR: {err.text_content()[:100]}")
                        return {"success": False, "error": f"提交失败: {err.text_content()[:100]}"}

            log("✓ 提交成功！")
            log("  关闭浏览器...")
            browser.close()
            log("  浏览器已关闭")
            return {"success": True}

        except Exception as e:
            browser.close()
            err_str = str(e)
            log(f"✗ 异常: {err_str[:200]}")
            if "Timeout" in err_str:
                # 从错误信息提取更多细节
                if "exceeded" in err_str:
                    detail = err_str.split("exceeded")[-1][:100] if "exceeded" in err_str else ""
                    return {"success": False, "error": f"超时: {detail}"}
                return {"success": False, "error": "超时：页面加载缓慢或元素不存在"}
            else:
                return {"success": False, "error": f"自动化错误: {err_str[:100]}"}


if __name__ == "__main__":
    # 测试：一次提交 Court 4 的两个时段
    result = submit_permits(
        court=4,
        slots=[
            {"date": "2026-06-27", "start": "20:00", "end": "21:00"},
            {"date": "2026-06-27", "start": "21:00", "end": "22:00"},
        ],
        num_people=4,
    )
    print(result)
