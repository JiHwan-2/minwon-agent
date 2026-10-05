"""판넬 HTML을 제출용 PNG(2배 해상도)·PDF로 뽑는다. 넘친 칸이 있으면 알려 준다.

사용 (저장소 폴더에서):
  backend\\.venv\\Scripts\\python docs\\submission\\panel\\render.py
결과: docs/submission/panel/AI민원길잡이_개발완료보고서_판넬1.png · _판넬2.png · AI민원길잡이_개발완료보고서.pdf (2쪽)
"""

import base64
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from capture_screens import BROWSERS, Page  # noqa: E402

W, H = 1754, 1240
PANELS = ["panel1.html", "panel2.html"]  # 판넬 1: 예시처럼 01~04, 판넬 2: 테스트·평가·신규개발분·한계 상세
NAME = "AI민원길잡이_개발완료보고서"

# 칸 안에서 글자·그림이 넘쳐 잘린 곳 찾기 (카드·표·목록)
OVERFLOW = """[...document.querySelectorAll('.card, .who, .step, .tri .box, .flow5 .box, .shot .img')]
  .filter(e => e.scrollHeight > e.clientHeight + 2 && !e.classList.contains('img'))
  .map(e => (e.querySelector('h2,h4,.cap')?.innerText || e.className).slice(0, 30) + ` (+${e.scrollHeight - e.clientHeight}px)`)"""


def main() -> int:
    exe = next(b for b in BROWSERS if Path(b).exists())
    profile = Path(tempfile.mkdtemp(prefix="minwon-panel-"))
    port = 9334
    proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--hide-scrollbars", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
                if any(t["type"] == "page" for t in targets):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        page = Page(next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=2, mobile=False)
        pdfs = []
        for i, name in enumerate(PANELS, 1):
            if not (HERE / name).exists():
                continue
            page.call("Page.navigate", url=(HERE / name).as_uri())
            page.wait("document.readyState === 'complete'", 30, 0.3)
            page.js("document.fonts.ready.then(() => true)")
            time.sleep(1.0)
            over = page.js(OVERFLOW)
            print(f"{name}: " + (f"넘친 칸 {over}" if over else "넘친 칸 없음"))
            png = page.call("Page.captureScreenshot", format="png", clip={"x": 0, "y": 0, "width": W, "height": H, "scale": 1})["data"]
            png_name = f"{NAME}.png" if len(PANELS) == 1 else f"{NAME}_판넬{i}.png"
            (HERE / png_name).write_bytes(base64.b64decode(png))
            pdf = page.call("Page.printToPDF", printBackground=True, paperWidth=W / 96, paperHeight=H / 96,
                            marginTop=0, marginBottom=0, marginLeft=0, marginRight=0, preferCSSPageSize=True)["data"]
            pdfs.append(base64.b64decode(pdf))
        # 판넬 두 장을 PDF 하나로: 브라우저가 만든 각 PDF를 그대로 이어 붙이지 않고, 두 장을 담은 인쇄용 페이지를 따로 뽑는다
        both = HERE / "_print.html"
        frames = "".join(f'<iframe src="{n}" style="width:{W}px;height:{H}px;border:0;display:block;page-break-after:always"></iframe>'
                         for n in PANELS if (HERE / n).exists())
        both.write_text(f"<!doctype html><meta charset='utf-8'><style>@page{{size:{W}px {H}px;margin:0}}body{{margin:0}}</style>{frames}",
                        encoding="utf-8")
        page.call("Page.navigate", url=both.as_uri())
        page.wait("document.readyState === 'complete'", 30, 0.3)
        time.sleep(2.0)
        pdf = page.call("Page.printToPDF", printBackground=True, paperWidth=W / 96, paperHeight=H / 96,
                        marginTop=0, marginBottom=0, marginLeft=0, marginRight=0, preferCSSPageSize=True)["data"]
        (HERE / f"{NAME}.pdf").write_bytes(base64.b64decode(pdf))
        both.unlink()
        print("저장:", ", ".join(p.name for p in sorted(HERE.glob(f"{NAME}*"))))
    finally:
        proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
