"""OpenAI(ChatGPT) 연동: 원고 분석, 그림 생성, 내레이션 음성.

API 키는 환경변수 OPENAI_API_KEY 또는 프로젝트 폴더의 .env 파일에서 읽습니다.
결과는 work/ 폴더에 캐시되어, 같은 내용은 다시 만들지 않습니다(비용 절약).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

from .config import ROOT, resolve


# ───────────────────────── 공통 ─────────────────────────
def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_client = None


def client():
    global _client
    if _client is None:
        _load_env()
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit(
                "OPENAI_API_KEY가 없습니다. 프로젝트 폴더에 .env 파일을 만들고\n"
                "  OPENAI_API_KEY=sk-...\n를 넣어 주세요. (.env.example 참고)"
            )
        from openai import OpenAI
        _client = OpenAI()
    return _client


def _model_unavailable(err: Exception) -> bool:
    from openai import BadRequestError, NotFoundError, PermissionDeniedError
    if isinstance(err, (NotFoundError, PermissionDeniedError)):
        return True
    if isinstance(err, BadRequestError):
        msg = str(err).lower()
        return "model" in msg and ("not" in msg or "invalid" in msg or "does not exist" in msg or "unsupported" in msg)
    return False


def with_fallback(models: list[str], fn, what: str):
    """앞 모델이 계정에서 안 되면 다음 모델로."""
    last = None
    for m in models:
        try:
            return fn(m)
        except Exception as e:  # noqa: BLE001
            if _model_unavailable(e):
                print(f"  ! {what} 모델 '{m}' 사용 불가 → 다음 모델 시도")
                last = e
                continue
            raise
    raise RuntimeError(f"{what}에 쓸 수 있는 모델이 없습니다. config.yaml의 openai 모델 이름을 확인하세요.") from last


def _h(*parts) -> str:
    return hashlib.sha1("␞".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]


# ───────────────────────── 1. 원고 → 장면 ─────────────────────────
SCENE_GUIDE = """너는 한국 교육기관 홍보 영상(세로 9:16 쇼츠) 구성작가다.
사용자가 준 원고를 아래 형식의 장면 목록 JSON으로 바꿔라. 원고에 있는 문장과 인용구는 최대한 그대로 쓴다.

영상 구성 (기준 영상과 같은 흐름):
1) intro 1개: 빨간 강조 박스 문구(headline) + 이어지는 말(text) + 떠다니는 키워드(keywords, 원고의 주제어들)
2) quote 여러 개: 주제(section)마다 문학 인용구 1개
3) outro 1개: 마무리 슬로건(headline, text)
4) end 1개: 기관 로고 화면 (원고에 기관 문구가 없으면 생략 가능)

각 장면 필드:
- type: "intro" | "quote" | "outro" | "end"
- section: (quote만) 화면 위 큰 제목, 짧게 (예: "학습지원")
- quote: (quote만) 인용구 본문. 따옴표 없이. 세로 화면에서 3~5줄이 되도록 의미 단위로 \\n 줄바꿈을 넣어라 (한 줄 12자 안팎)
- source: (quote만) 『책 제목』 by. 작가
- original: (quote만) 인용구의 원어 문장. 확실할 때만 쓰고 모르면 빈 문자열
- caption: 화면 아래 해설 한 문장 (30자 안팎)
- narration: 내레이션으로 읽을 문장. quote 장면은 "인용구 + 해설"을 자연스럽게 이은 2~3문장. intro는 headline과 text를 이어 읽는 문장. end는 빈 문자열
- image_prompt: (intro 제외 모두 선택, quote는 필수) 영어로 쓴 그림 묘사. 인용구의 의미가 드러나는 한국 가족/아이/부모의 구체적 장면(인물, 행동, 장소, 시간대, 구도). 글자는 넣지 말 것
- headline, text, keywords: intro/outro에서 사용
- needs_review: 원고에 없는 인용구를 네가 보충했거나 원문이 불확실하면 true

원고에 인용구가 없는 주제는 저작권이 끝난 고전 문학(예: 하이디, 이상한 나라의 앨리스, 어린 왕자, 크리스마스 캐럴, 행복한 왕자 등)에서 내용이 정확히 확인되는 구절로 보충하고 needs_review를 true로 둔다.
반드시 {"series_title": "...", "scenes": [...]} 형태의 JSON만 출력한다. series_title은 원고에 시리즈 제목이 있으면 그것, 없으면 null.
"""


def script_to_scenes(text: str, cfg: dict) -> dict:
    c = client()

    def call(model: str):
        r = c.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SCENE_GUIDE}, {"role": "user", "content": text}],
            response_format={"type": "json_object"},
        )
        return r.choices[0].message.content

    print("  원고 분석 중 (ChatGPT)…")
    raw = with_fallback(cfg["openai"]["text_models"], call, "원고 분석")
    data = json.loads(raw)
    if "scenes" not in data:
        raise RuntimeError("원고 분석 결과에 scenes가 없습니다:\n" + raw[:500])
    return data


# ───────────────────────── 2. 그림 ─────────────────────────
def image_prompt(scene: dict, cfg: dict) -> str:
    return f"{scene.get('image_prompt', '').strip()}\n\nArt style: {cfg['style']['prompt']}"


def generate_image(scene: dict, idx: int, cfg: dict, work: Path) -> Path:
    oc = cfg["openai"]
    prompt = image_prompt(scene, cfg)
    ref = resolve(cfg["style"].get("reference_image"))
    key = _h(prompt, oc["image_size"], oc["image_quality"], ref and ref.name, oc["image_models"][0])
    out = work / "images" / f"scene{idx:02d}_{key}.png"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    c = client()

    def call(model: str):
        if ref and ref.exists():
            with open(ref, "rb") as fh:
                return c.images.edit(
                    model=model,
                    image=[fh],
                    prompt=(
                        "Use the attached image ONLY as an art-style reference (brushwork, canvas texture, palette, "
                        "lighting, level of realism). Do not copy its people, faces or composition. Create a new image:\n"
                        + prompt
                    ),
                    size=oc["image_size"],
                    quality=oc["image_quality"],
                )
        return c.images.generate(model=model, prompt=prompt, size=oc["image_size"], quality=oc["image_quality"], n=1)

    r = with_fallback(oc["image_models"], call, "그림 생성")
    item = r.data[0]
    if getattr(item, "b64_json", None):
        out.write_bytes(base64.b64decode(item.b64_json))
    else:  # URL로 주는 모델 대비
        import urllib.request
        urllib.request.urlretrieve(item.url, out)
    return out


# ───────────────────────── 3. 내레이션 ─────────────────────────
def tts(text: str, cfg: dict, work: Path) -> Path | None:
    text = (text or "").strip()
    if not text:
        return None
    n = cfg["narration"]
    model = cfg["openai"]["tts_model"]
    out = work / "voice" / f"{_h(text, model, n['voice'], n['instructions'])}.mp3"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(model=model, voice=n["voice"], input=text, response_format="mp3")
    if n.get("instructions") and "tts-1" not in model:
        kwargs["instructions"] = n["instructions"]
    with client().audio.speech.with_streaming_response.create(**kwargs) as r:
        r.stream_to_file(out)
    return out


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())
