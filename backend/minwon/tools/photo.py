"""시민이 올린 현장 사진: 받아서 줄여 두고(prepare), 사진 정보(EXIF)에서 촬영 위치(GPS)·시각을 읽는다(read_exif).

원본은 저장하지 않는다. AI에 보낼 크기로 줄인 JPEG(메타데이터 없음)과 EXIF 부분만 메모리에 잠시 둔다.
"""

import io
import math
import uuid
from collections import OrderedDict
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError

from minwon.tools import tool_result

MAX_BYTES = 15 * 1024 * 1024
MAX_EDGE = 1568  # Claude가 줄이지 않고 그대로 보는 긴 변 길이
FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}  # MPO: 일부 휴대폰 카메라의 JPEG
KEEP = 64  # 메모리에 둘 최근 사진 수 (서버를 다시 켜면 세션과 함께 사라진다)

GPS_IFD, EXIF_IFD = 0x8825, 0x8769
DATETIME, DATETIME_ORIGINAL = 306, 36867

_store: "OrderedDict[str, dict]" = OrderedDict()


class PhotoError(ValueError):
    """사진으로 읽을 수 없거나 너무 큰 파일. code는 i18n 안내문 키."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def prepare(raw: bytes, name: str = "") -> dict:
    """사진을 확인하고 줄여 저장한다. 돌려주는 값(id·크기)만 대화 상태에 남는다."""
    if len(raw) > MAX_BYTES:
        raise PhotoError("photo.too_big")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise PhotoError("photo.unreadable") from e
    if img.format not in FORMATS:
        raise PhotoError("photo.unreadable")

    exif = img.getexif()
    small = ImageOps.exif_transpose(img).convert("RGB")  # 휴대폰 사진이 누워 보이지 않게 회전을 먼저 적용
    small.thumbnail((MAX_EDGE, MAX_EDGE))
    out = io.BytesIO()
    small.save(out, "JPEG", quality=85)  # exif를 넘기지 않으므로 위치 정보가 빠진 사본

    photo_id = uuid.uuid4().hex
    _store[photo_id] = {"jpeg": out.getvalue(), "exif": exif.tobytes() if len(exif) else b""}
    while len(_store) > KEEP:
        _store.popitem(last=False)
    return {"id": photo_id, "name": name[:100], "width": small.width, "height": small.height}


def image(photo_id: str) -> bytes | None:
    """AI에 보낼 줄인 사진 (메타데이터 없음)."""
    return (_store.get(photo_id) or {}).get("jpeg")


def _degrees(value, ref) -> float | None:
    try:
        d, m, s = (float(v) for v in value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    deg = d + m / 60 + s / 3600
    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    if str(ref).strip().upper() in ("S", "W"):
        deg = -deg
    return deg if math.isfinite(deg) else None


def gps(exif: Image.Exif) -> dict | None:
    """EXIF의 GPS 위도·경도 (없거나 값이 이상하면 None)."""
    info = exif.get_ifd(GPS_IFD)
    lat, lon = _degrees(info.get(2), info.get(1)), _degrees(info.get(4), info.get(3))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:  # 위치를 못 잡은 카메라가 0,0을 넣는 경우
        return None
    return {"lat": round(lat, 7), "lon": round(lon, 7)}


def taken_at(exif: Image.Exif) -> str:
    """촬영 시각 'YYYY-MM-DD HH:MM' (없으면 빈 문자열)."""
    raw = exif.get_ifd(EXIF_IFD).get(DATETIME_ORIGINAL) or exif.get(DATETIME) or ""
    try:
        return datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


def read_exif(photo_id: str) -> dict:
    """Tool: 사진 정보(EXIF)에서 촬영 위치(GPS)와 촬영 시각을 읽는다."""
    stored = _store.get(photo_id)
    if stored is None:
        return tool_result("photo_meta", False, "error", "사진을 찾을 수 없음 (서버가 다시 시작됨)", {"gps": None, "taken_at": ""})
    try:
        exif = Image.Exif()
        if stored["exif"]:
            exif.load(stored["exif"])
        found = {"gps": gps(exif), "taken_at": taken_at(exif)}
    except Exception as e:  # 기기마다 EXIF가 망가져 있을 수 있다 (Pillow가 여러 종류의 오류를 낸다)
        return tool_result("photo_meta", True, "exif", "사진 정보(EXIF)를 읽지 못함 → 대화로 위치 확인",
                           {"gps": None, "taken_at": ""}, error=f"{type(e).__name__}: {e}"[:150])
    parts = []
    if found["gps"]:
        parts.append(f"촬영 위치 있음 (위도 {found['gps']['lat']:.5f}, 경도 {found['gps']['lon']:.5f})")
    else:
        parts.append("촬영 위치(GPS) 정보 없음 → 대화로 위치 확인")
    if found["taken_at"]:
        parts.append(f"촬영 시각 {found['taken_at']}")
    return tool_result("photo_meta", True, "exif", " · ".join(parts), found)


def korean_time(value: str) -> str:
    """'2026-10-02 14:30' → '2026년 10월 2일 오후 2시 30분' (민원 문장·시간 추출에 쓰는 표기)."""
    try:
        t = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return ""
    half = "오전" if t.hour < 12 else "오후"
    hour = t.hour % 12 or 12
    minute = f" {t.minute}분" if t.minute else ""
    return f"{t.year}년 {t.month}월 {t.day}일 {half} {hour}시{minute}"
