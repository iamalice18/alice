"""원고 → 9:16 문학 인용 영상 자동 생성.

사용법
  python make_video.py 원고.txt                 # 원고(자유 형식) → ChatGPT가 장면 구성 → 그림·음성 → 영상
  python make_video.py 원고.txt --plan-only     # 장면 구성(scenes.yaml)만 만들고 멈춤 (검토·수정용)
  python make_video.py work/원고/scenes.yaml    # 고친 장면 파일로 영상 만들기 (이미 만든 그림·음성은 재사용)
  python make_video.py examples/scenes_example.yaml --no-ai   # API 없이 자리표시 그림으로 시험

옵션
  --bgm 음악.mp3        배경음악 (config.yaml의 bgm.path 대신)
  --no-narration        내레이션 없이 (배경음악만)
  --style-ref 그림.png  이 그림의 화풍을 따라 그리기
  --out 결과.mp4        결과 파일 경로 (기본: output/<원고이름>.mp4)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from PIL import Image

from videogen import audio, config, fonts, render
from videogen import layout as L

ROOT = Path(__file__).resolve().parent


def clean(s: str) -> str:
    s = re.sub(r"[『』「」]", "", s or "")
    s = s.replace("by.", "").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def default_narration(sc: dict) -> str:
    if sc.get("narration") is not None:
        return clean(sc["narration"])
    t = sc.get("type", "quote")
    if t == "quote":
        return clean(f"{sc.get('quote', '')} {sc.get('caption', '')}")
    if t == "intro":
        return clean(f"{sc.get('headline', '')}{sc.get('text', '')} {sc.get('caption', '')}")
    if t == "outro":
        return clean(f"{sc.get('headline', '')}. {sc.get('text', '')}")
    return ""


def estimate(sc: dict, cfg: dict) -> float:
    """내레이션이 없을 때 장면 길이: 읽을 글자 수 기준."""
    t = sc.get("type", "quote")
    if t == "end":
        return 3.5
    chars = len(clean(sc.get("quote", "") + sc.get("caption", "") + sc.get("headline", "") + sc.get("text", "")))
    return max(float(cfg["video"]["min_scene"]), 2.2 + chars / 8.5)


def load_scenes(src: Path, cfg: dict, work: Path, no_ai: bool) -> dict:
    if src.suffix.lower() in (".yaml", ".yml", ".json"):
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        if isinstance(data, list):
            data = {"scenes": data}
        return data
    if no_ai:
        sys.exit("--no-ai 모드에서는 장면 파일(.yaml)이 필요합니다. examples/scenes_example.yaml 참고")
    from videogen import ai
    data = ai.script_to_scenes(src.read_text(encoding="utf-8"), cfg)
    work.mkdir(parents=True, exist_ok=True)
    plan = work / "scenes.yaml"
    plan.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"  장면 구성 저장: {plan}")
    review = [i + 1 for i, s in enumerate(data["scenes"]) if s.get("needs_review")]
    if review:
        print(f"  ※ 확인 필요 장면(보충된 인용구 등): {review}  → scenes.yaml에서 확인하세요")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--bgm", default=None)
    ap.add_argument("--style-ref", default=None)
    ap.add_argument("--no-ai", action="store_true", help="API 없이 자리표시 그림, 음성 없음")
    ap.add_argument("--no-narration", action="store_true")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--workers", type=int, default=3, help="그림 동시 생성 수")
    a = ap.parse_args()

    t0 = time.time()
    cfg = config.load(a.config)
    fonts.set_overrides(cfg.get("fonts"))
    if a.bgm:
        cfg["bgm"]["path"] = a.bgm
    if a.style_ref:
        cfg["style"]["reference_image"] = a.style_ref
    if a.no_narration or a.no_ai:
        cfg["narration"]["enabled"] = False

    src = Path(a.input).resolve()
    stem = src.parent.name if src.name == "scenes.yaml" and src.parent.parent.name == "work" else src.stem
    work = ROOT / "work" / stem
    work.mkdir(parents=True, exist_ok=True)

    print("[1/5] 장면 구성")
    data = load_scenes(src, cfg, work, a.no_ai)
    if data.get("series_title"):
        cfg["series_title"] = data["series_title"]
        if cfg.get("series_accent") and cfg["series_accent"] not in data["series_title"]:
            cfg["series_accent"] = data.get("series_accent") or data["series_title"].rpartition(" ")[2]
    scenes: list[dict] = [s for s in data["scenes"] if s]
    print(f"  장면 {len(scenes)}개")
    if a.plan_only:
        print("검토 후 다음 명령으로 영상을 만드세요:\n  python make_video.py", work / "scenes.yaml")
        return

    print("[2/5] 그림 생성")
    images: dict[int, Image.Image] = {}
    need = [i for i, s in enumerate(scenes) if s.get("image") or (s.get("image_prompt") and s.get("type", "quote") in ("quote", "intro"))]
    if a.no_ai:
        for i in need:
            if scenes[i].get("image") and config.resolve(scenes[i]["image"]).exists():
                images[i] = Image.open(config.resolve(scenes[i]["image"])).convert("RGB")
            elif scenes[i].get("type", "quote") == "quote":
                images[i] = L.placeholder(scenes[i].get("image_prompt", ""), i)
    else:
        from videogen import ai

        def job(i: int):
            sc = scenes[i]
            if sc.get("image"):
                p = config.resolve(sc["image"])
                if p and p.exists():
                    return i, p
            return i, ai.generate_image(sc, i, cfg, work)

        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            for i, p in ex.map(job, need):
                images[i] = Image.open(p).convert("RGB")
                print(f"  장면 {i + 1}: {Path(p).name}")

    print("[3/5] 내레이션")
    n = cfg["narration"]
    voice: dict[int, tuple[Path, float]] = {}
    if n.get("enabled"):
        from videogen import ai
        for i, sc in enumerate(scenes):
            p = ai.tts(default_narration(sc), cfg, work)
            if p:
                voice[i] = (p, ai.duration(p))
                print(f"  장면 {i + 1}: {voice[i][1]:.1f}초")
    else:
        print("  (끔)")

    xf = float(cfg["video"]["crossfade"])
    for i, sc in enumerate(scenes):
        if sc.get("duration"):
            d = float(sc["duration"])
        elif i in voice:
            d = max(float(cfg["video"]["min_scene"]), n["lead"] + voice[i][1] + n["tail"])
        else:
            d = estimate(sc, cfg)
        sc["_duration"] = d + (xf if 0 < i < len(scenes) - 1 else xf / 2)

    print("[4/5] 영상 렌더링")
    plans = render.build_plans(scenes, images, cfg)
    silent = work / "video_silent.mp4"
    prev = work / "preview"
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir()
    total = render.render_video(plans, silent, cfg, prev)

    print("[5/5] 소리 합치기")
    starts, _ = render.timeline([p.duration for p in plans], xf)
    narr = [(voice[i][0], starts[i] + n["lead"]) for i in sorted(voice)]
    bgm = config.resolve(cfg["bgm"].get("path"))
    if bgm and not bgm.exists():
        print(f"  ! 배경음악 파일 없음: {bgm} (건너뜀)")
        bgm = None
    mixed = audio.mix(narr, bgm, total, cfg, work / "audio.m4a")
    out = Path(a.out) if a.out else ROOT / "output" / f"{stem}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    audio.mux(silent, mixed, out)
    print(f"\n완료: {out}  ({total:.1f}초, {L.W}x{L.H}, {time.time() - t0:.0f}초 소요)")
    print(f"미리보기 장면 이미지: {prev}")


if __name__ == "__main__":
    main()
