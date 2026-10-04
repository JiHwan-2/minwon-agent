"""제출물(판넬·발표자료)에 넣을 실제 서비스 화면을 고해상도로 캡처한다.

Edge(또는 Chrome)를 화면 없이 띄워 실행 중인 서비스(화면 5173 + 서버 8000)에 시나리오를 실제로 입력하고,
처리가 끝나면 화면 요소를 2배 해상도 PNG로 저장한다. 목업이 아니라 실제 실행 화면이다.
사용 (저장소 폴더에서, 서버·화면을 켠 상태):
  backend\\.venv\\Scripts\\python docs\\submission\\capture_screens.py --only traffic,vi,service
결과: docs/submission/panel/img/*.png
"""

import argparse
import base64
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

OUT = Path(__file__).resolve().parent / "panel" / "img"
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"]

# 시나리오: 첫 입력 → Agent가 되물으면 answers를 차례로 (없으면 '모름'). shots: 끝난 뒤 찍을 화면 요소
SCENARIOS = {
    "traffic": {
        "messages": ["학교 앞 횡단보도가 너무 위험해요.",
                     "김해시 삼계동 삼계초등학교 정문 앞이에요. 평일 아침 등교 시간에 차들이 쌩쌩 달려요.",
                     "거의 매일이요"],
        "shots": {"traffic_page": "main.layout", "traffic_chat": "section.panel.chat", "traffic_log": "section.panel.log",
                  "traffic_package": ".package"},
    },
    "vi": {
        "messages": ["Đèn an ninh ở con hẻm phía sau trường tiểu học Hapseong, phường Hapseong-dong, quận Masanhoewon-gu, Changwon "
                     "đã tắt mỗi đêm suốt một tuần."],
        "shots": {"vi_package": ".package"},
        "toggle": {"text": "tiếng Hàn", "shots": {"vi_package_korean": ".package"}},
    },
    "service": {
        "messages": ["주민등록등본 어디서 떼요?", "창원시 성산구 상남동"],
        "shots": {"service_chat": "section.panel.chat", "service_card": ".guide-card", "service_log": "section.panel.log"},
    },
}


class Page:
    def __init__(self, ws_url: str):
        self.ws = connect(ws_url, max_size=None)
        self.n = 0

    def call(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    def wait(self, expr: str, timeout: float, every: float = 1.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.js(expr):
                return True
            time.sleep(every)
        return False

    def shot(self, selector: str, path: Path) -> bool:
        rect = self.js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return null;
            el.scrollIntoView({{block: 'start'}}); const r = el.getBoundingClientRect();
            return {{x: r.left + window.scrollX, y: r.top + window.scrollY, width: r.width, height: r.height}}; }})()""")
        if not rect:
            print(f"    (없음: {selector})")
            return False
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                         clip={**{k: round(v) for k, v in rect.items()}, "scale": 1})["data"]
        path.write_bytes(base64.b64decode(data))
        print(f"    → {path.name} ({round(rect['width'])}×{round(rect['height'])})")
        return True


BUSY = "!!document.querySelector('.bubble-busy') || !!document.querySelector('textarea')?.disabled"
DONE = "!!document.querySelector('.package') || !!document.querySelector('.guide-card')"


def send(page: Page, text: str) -> None:
    page.js("document.querySelector('textarea').focus()")
    page.call("Input.insertText", text=text)
    for kind in ("keyDown", "keyUp"):
        page.call("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                  **({"text": "\r"} if kind == "keyDown" else {}))
    page.wait(BUSY, 10, 0.3)  # 보낸 뒤 처리 시작을 기다림
    if not page.wait(f"!({BUSY})", 300):
        raise TimeoutError(f"5분 안에 끝나지 않음: {text[:30]}")


def run(page: Page, name: str, base_ui: str) -> None:
    sc = SCENARIOS[name]
    print(f"[{name}]")
    page.call("Page.navigate", url=base_ui)
    page.wait("!!document.querySelector('textarea') && document.readyState === 'complete'", 30)
    time.sleep(1.5)
    queue = list(sc["messages"])
    send(page, queue.pop(0))
    for _ in range(4):
        if page.js(DONE):
            break
        send(page, queue.pop(0) if queue else "모름")
    if not page.js(DONE):
        raise RuntimeError("결과 화면까지 가지 못함")
    time.sleep(1.5)
    fallback = page.js("['대체 경로', 'Fallback', '备用路径', 'Đường dự phòng'].some(w => document.body.innerText.includes(w))")
    if fallback:
        print("    주의: 작업 기록에 대체 경로가 있음 → 이 회차는 쓰지 말 것")
    # 대화창은 화면 높이에 맞춰 안에서 스크롤되므로, 캡처할 때만 펼쳐서 카드가 잘리지 않게 한다 (내용은 그대로)
    page.js("""(() => { const s = document.createElement('style');
        s.textContent = '.chat{height:auto!important;position:static!important}.chat-log{overflow:visible!important}';
        document.head.appendChild(s); })()""")
    time.sleep(0.5)
    for file, selector in sc["shots"].items():
        page.shot(selector, OUT / f"{file}.png")
    if toggle := sc.get("toggle"):
        clicked = page.js(f"""(() => {{ const b = [...document.querySelectorAll('.package button')]
            .find(b => b.innerText.includes({json.dumps(toggle['text'])})); if (!b) return false; b.click(); return true; }})()""")
        time.sleep(1)
        if clicked:
            for file, selector in toggle["shots"].items():
                page.shot(selector, OUT / f"{file}.png")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui", default="http://localhost:5173")
    ap.add_argument("--only", default=",".join(SCENARIOS))
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--port", type=int, default=9333)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    exe = next(b for b in BROWSERS if Path(b).exists())
    profile = Path(tempfile.mkdtemp(prefix="minwon-capture-"))
    proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={args.port}", f"--user-data-dir={profile}",
                             "--hide-scrollbars", "--lang=ko-KR", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = httpx.get(f"http://127.0.0.1:{args.port}/json/list", timeout=2).json()
                if any(t["type"] == "page" for t in targets):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        page = Page(next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"])
        page.call("Emulation.setDeviceMetricsOverride", width=args.width, height=1000, deviceScaleFactor=2, mobile=False)
        page.call("Page.enable")
        for name in args.only.split(","):
            run(page, name.strip(), args.ui)
    finally:
        proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
