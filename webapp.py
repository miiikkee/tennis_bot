#!/usr/bin/env python3
"""前端生成器（纯展示层）：把免登录场地生成「按时间找空位」产品页 app.html。

单一 UI 来源：直接内联 tennis-finder.js 组件 + 内联数据快照，避免与组件逻辑重复漂移。
数据由 pipeline.py 产出（public_data.json，已完成分类/兜底/校验/坐标）。

用法:
  python3 pipeline.py && python3 webapp.py --open   # 先刷数据，再生成 app.html
  python3 webapp.py --artifact                       # 额外产出可发布的 Artifact 片段
若 public_data.json 不存在，会自动调用 pipeline 生成一次。
"""
import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "public_data.json"
OUT_HTML = ROOT / "app.html"
OUT_FRAG = ROOT / "app_artifact.html"
COMPONENT = ROOT / "tennis-finder.js"


def build_payload():
    """只读 pipeline 产出的契约文件；缺失则触发一次生成。"""
    if not DATA.exists():
        import pipeline
        pipeline.generate()
    return json.loads(DATA.read_text())


def _inline_data():
    # 转义 </ 防止数据里的 </script> 破坏内联 JSON 脚本块
    return json.dumps(build_payload(), ensure_ascii=False).replace("</", "<\\/")


def _component_js():
    # 防御性转义（组件源码理论上不含 </script>，仍兜底）
    return COMPONENT.read_text().replace("</script", "<\\/script")


def _widget():
    return (f'<script>{_component_js()}</script>\n'
            f'<tennis-finder><script type="application/json">{_inline_data()}</script></tennis-finder>')


def render(title="🎾 NYC Tennis Finder"):
    return (f'<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>'
            f'<style>body{{margin:0;background:#f7f8f7}}'
            f'@media(prefers-color-scheme:dark){{body{{background:#0f1210}}}}</style></head>'
            f'<body>{_widget()}</body></html>')


def render_fragment():
    """Artifact 片段：只含 <script> + <tennis-finder>，无 doctype/html/body 外壳。"""
    return _widget()


def main():
    OUT_HTML.write_text(render())
    print(f"生成 -> {OUT_HTML}")
    if "--artifact" in sys.argv:
        OUT_FRAG.write_text(render_fragment())
        print(f"Artifact 片段 -> {OUT_FRAG}")
    if "--open" in sys.argv:
        webbrowser.open(OUT_HTML.as_uri())


if __name__ == "__main__":
    main()
