"""한글 폰트 찾기.

우선순위: config에 지정한 파일 → fonts/ 폴더(setup_fonts.py로 받은 Noto) → OS 기본 폰트.
.ttc(폰트 묶음) 파일은 이름에 'KR'이 들어간 글꼴을 골라 씁니다.
"""
from __future__ import annotations

import os
import platform
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "fonts"

# 역할별 후보 (앞에 있을수록 우선)
CANDIDATES: dict[str, list[str]] = {
    "sans_bold": [
        str(FONT_DIR / "NotoSansKR-Bold.otf"),
        str(FONT_DIR / "Pretendard-Bold.otf"),
        "C:/Windows/Fonts/malgunbd.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    ],
    "sans": [
        str(FONT_DIR / "NotoSansKR-Medium.otf"),
        str(FONT_DIR / "Pretendard-Medium.otf"),
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ],
    "serif": [
        str(FONT_DIR / "NotoSerifKR-SemiBold.otf"),
        "C:/Windows/Fonts/batang.ttc",
        "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-SemiBold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc",
        "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc",
    ],
    "latin_italic": [
        str(FONT_DIR / "NotoSerif-Italic.ttf"),
        "C:/Windows/Fonts/georgiai.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    ],
    "brush": [  # 마무리 장면 손글씨 느낌 (없으면 sans_bold 사용)
        str(FONT_DIR / "NanumBrushScript-Regular.ttf"),
        str(FONT_DIR / "NanumPenScript-Regular.ttf"),
        "C:/Windows/Fonts/NanumBrush.ttf",
    ],
}

_overrides: dict[str, str] = {}


def set_overrides(fonts_cfg: dict | None) -> None:
    """config.yaml의 fonts: 항목으로 경로를 직접 지정."""
    _overrides.clear()
    for role, path in (fonts_cfg or {}).items():
        if path:
            _overrides[role] = str((ROOT / path) if not os.path.isabs(path) else path)
    font.cache_clear()


def _ttc_index(path: str) -> int:
    """폰트 묶음에서 한국어(KR) 글꼴 번호 찾기."""
    if not path.lower().endswith(".ttc"):
        return 0
    for i in range(12):
        try:
            name = " ".join(ImageFont.truetype(path, 20, index=i).getname())
        except OSError:
            break
        if "KR" in name or "Korean" in name or "Gothic Neo" in name:
            return i
    return 0


def find(role: str) -> str | None:
    if role in _overrides and os.path.exists(_overrides[role]):
        return _overrides[role]
    for p in CANDIDATES.get(role, []):
        if os.path.exists(p):
            return p
    return None


@lru_cache(maxsize=256)
def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    path = find(role)
    if path is None:
        fallback = {"brush": "sans_bold", "latin_italic": "serif", "serif": "sans", "sans": "sans_bold"}
        if role in fallback:
            return font(fallback[role], size)
        raise RuntimeError(
            "한글 폰트를 찾지 못했습니다. `python setup_fonts.py`로 폰트를 받거나 "
            "config.yaml의 fonts: 항목에 폰트 경로를 지정하세요. "
            f"(OS: {platform.system()})"
        )
    return ImageFont.truetype(path, size, index=_ttc_index(path))
