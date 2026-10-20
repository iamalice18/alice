"""설정 불러오기: 기본값 위에 config.yaml을 덮어씁니다."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "series_title": "문학으로 알아보는 대구 학부모 교육",
    "series_accent": "학부모 교육",   # 시리즈 제목 중 강조색으로 크게 보일 부분
    # 기준 영상에서 잘라낸 마스코트·로고·모서리 장식 (tools/extract_brand.py)
    "brand": {"enabled": True, "dir": "assets/brand", "scale": 1.28, "logo_scale": 1.05},
    "video": {"width": 1080, "height": 1920, "fps": 30, "crossfade": 0.6, "min_scene": 4.0, "crf": 18},
    "colors": {
        "paper": "#F2F2F2",
        "text": "#242424",
        "accent": "#4A51C4",       # 섹션 제목
        "highlight": "#E8452C",    # 인트로 강조 박스
        "quote": "#392206",
        "muted": "#6B5E50",
        "decor": ["#E8452C", "#2F4BC9", "#FFC22E", "#47C96A", "#FF6FA8", "#8A5CF6"],
    },
    "fonts": {},
    "logos": [],  # [{path: assets/logo.png, position: top-left|top-right|bottom-left|bottom-right|center, height: 90}]
    "openai": {
        # 앞의 모델이 계정에서 안 되면 다음 모델로 자동 전환
        "text_models": ["gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini"],
        "image_models": ["gpt-image-2", "gpt-image-1"],
        "image_size": "1024x1536",
        "image_quality": "high",
        "tts_model": "gpt-4o-mini-tts",
    },
    "style": {
        "prompt": (
            "Warm painterly illustration that looks like an oil painting made over a realistic photograph: "
            "visible canvas grain and soft brush strokes, gentle film-like softness, warm golden-hour palette "
            "(amber, ochre, muted teal), natural light, nostalgic and tender mood, East Asian (Korean) people with "
            "realistic proportions and natural expressions, cinematic depth of field. "
            "Vertical 2:3 composition. Keep the lower 40% of the image calm, soft and uncluttered "
            "(sky, wall, ground or blurred background) so text can be placed over it. "
            "Absolutely no text, letters, captions, logos or watermarks."
        ),
        "reference_image": None,  # 예: assets/style_ref.png (이 그림의 화풍을 따라 그림)
    },
    "narration": {
        "enabled": True,
        "voice": "coral",
        "instructions": (
            "한국어 교육 영상의 내레이터. 따뜻하고 차분하며 신뢰감 있는 목소리. "
            "문학 인용구는 한 박자 쉬고 천천히, 감정을 담아 낭독하고, 해설 문장은 또렷하게 읽기."
        ),
        "speed_hint": 1.0,
        "lead": 0.6,   # 장면 시작 후 음성 시작까지(초)
        "tail": 0.9,   # 음성 끝난 후 여유(초)
    },
    "bgm": {"path": None, "volume": 0.22, "duck": True, "fade_out": 2.5},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    user = {}
    if path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _merge(DEFAULTS, user)


def resolve(p: str | None) -> Path | None:
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else (ROOT / q)
