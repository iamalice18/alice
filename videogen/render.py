"""장면을 움직이는 프레임으로 만들어 ffmpeg로 인코딩."""
from __future__ import annotations

import math
import multiprocessing as mp
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import layout as L
from .config import resolve

try:  # 있으면 훨씬 빠름 (pip install opencv-python-headless)
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class Anim:
    layer: L.Layer
    start: float = 0.0     # 나타나기 시작(초)
    fade: float = 0.0      # 나타나는 데 걸리는 시간
    rise: int = 0          # 아래에서 떠오르는 거리(px)


@dataclass
class Plan:
    duration: float
    base: np.ndarray
    panel: Image.Image          # 패널보다 약간 큰 원본 (움직임용)
    motion: str = "zoom_in"     # zoom_in | zoom_out | tilt | still
    anims: list[Anim] = field(default_factory=list)
    _src_np: np.ndarray | None = None


def _ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, t)))


def _panel_view(plan: Plan, t: float) -> np.ndarray:
    src = plan.panel
    pw, ph = L.W, L.PANEL_H
    p = _ease(t / plan.duration) if plan.duration > 0 else 0
    if plan.motion == "zoom_in":
        z, cy = 1.0 + 0.09 * p, 0.46 - 0.04 * p
    elif plan.motion == "zoom_out":
        z, cy = 1.09 - 0.09 * p, 0.44 + 0.02 * p
    elif plan.motion == "tilt":
        z, cy = 1.04, 0.38 + 0.12 * p
    else:
        z, cy = 1.0 + 0.03 * p, 0.5
    ww, wh = pw / z, ph / z
    cx = src.width / 2
    cyp = min(max(cy * src.height, wh / 2), src.height - wh / 2)
    x0, y0 = cx - ww / 2, cyp - wh / 2
    if cv2 is not None:
        if plan._src_np is None:
            plan._src_np = np.asarray(src, dtype=np.uint8)
        m = np.array([[z, 0, -x0 * z], [0, z, -y0 * z]], dtype=np.float64)
        view = cv2.warpAffine(plan._src_np, m, (pw, ph), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        return view.astype(np.float32)
    view = src.transform((pw, ph), Image.AFFINE, (1 / z, 0, x0, 0, 1 / z, y0), resample=Image.BILINEAR)
    return np.asarray(view, dtype=np.float32)


def frame(plan: Plan, t: float) -> np.ndarray:
    f = plan.base.copy()
    f[L.PANEL_Y0:L.PANEL_Y1] = _panel_view(plan, t)
    for a in plan.anims:
        if t < a.start:
            continue
        k = 1.0 if a.fade <= 0 else _ease((t - a.start) / a.fade)
        a.layer.draw_on(f, k, int(round(a.rise * (1 - k))))
    return f


def build_plans(scenes: list[dict], images: dict[int, Image.Image], cfg: dict) -> list[Plan]:
    colors = cfg["colors"]
    plans: list[Plan] = []
    motions = ["zoom_in", "tilt", "zoom_out"]
    quote_imgs = [images[i] for i, s in enumerate(scenes) if s.get("type", "quote") == "quote" and i in images]
    for i, sc in enumerate(scenes):
        kind = sc.get("type", "quote")
        base = L.base_frame(sc, cfg, resolve)
        anims: list[Anim] = []
        if kind == "intro":
            panel = L.intro_panel(sc, colors, images.get(i))
            kw, head = L.intro_layers(sc, colors)
            if kw:
                anims.append(Anim(kw, 0.2, 1.2))
            if head:
                anims.append(Anim(head, 0.5, 0.8, 24))
            motion = "still"
        elif kind == "outro":
            panel = L.outro_panel(quote_imgs, colors)
            veil, txt = L.outro_layers(sc, colors)
            if veil:
                anims.append(Anim(veil, 0.8, 1.0))
            if txt:
                anims.append(Anim(txt, 1.3, 0.9, 20))
            motion = "zoom_out"
        elif kind == "end":
            panel = L.end_card(sc, colors, resolve)
            motion = "still"
        else:
            img = images.get(i)
            if img is None:
                img = L.placeholder(sc.get("image_prompt", ""), i)
            panel = img.convert("RGB")
            grad, txt = L.quote_layers(sc, panel, colors)
            if grad:
                anims.append(Anim(grad, 0.0, 0.6))
            if txt:
                anims.append(Anim(txt, 0.5, 0.9, 22))
            motion = motions[i % len(motions)]
        cap = L.caption_layer(sc.get("caption", ""), colors)
        if cap:
            anims.append(Anim(cap, 0.8, 0.7, 12))
        # 움직일 여유를 두고 패널을 덮도록 크기 맞춤
        panel = L.cover(panel, L.W, L.PANEL_H)
        plans.append(Plan(float(sc["_duration"]), base, panel, motion, anims))
    return plans


def timeline(durations: list[float], xf: float) -> tuple[list[float], float]:
    starts, t = [], 0.0
    for d in durations:
        starts.append(t)
        t += d - xf
    return starts, t + xf


_G: dict = {}


def _init(plans, starts, xf, fps):
    _G.update(plans=plans, starts=starts, xf=xf, fps=fps)


def _compose(n: int) -> bytes:
    plans, starts, xf, fps = _G["plans"], _G["starts"], _G["xf"], _G["fps"]
    t = n / fps
    active = [(i, t - s) for i, s in enumerate(starts) if s <= t < s + plans[i].duration]
    if not active:
        active = [(len(plans) - 1, plans[-1].duration - 1e-3)]
    i, lt = active[0]
    img = frame(plans[i], lt)
    if len(active) > 1:
        j, lt2 = active[1]
        k = _ease(lt2 / xf)
        img = img * (1 - k) + frame(plans[j], lt2) * k
    return img.clip(0, 255).astype(np.uint8).tobytes()


def render_video(plans: list[Plan], out: Path, cfg: dict, preview_dir: Path | None = None, workers: int | None = None) -> float:
    v = cfg["video"]
    fps, xf = int(v["fps"]), float(v["crossfade"])
    starts, total = timeline([p.duration for p in plans], xf)
    n_frames = int(round(total * fps))
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{L.W}x{L.H}",
        "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(v.get("crf", 18)),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin
    previews = {int((s + min(p.duration - 0.3, 3.2)) * fps) for s, p in zip(starts, plans)}
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    t0 = time.time()

    def frames():
        if workers <= 1:
            _init(plans, starts, xf, fps)
            for n in range(n_frames):
                yield _compose(n)
        else:
            ctx = mp.get_context("spawn" if sys.platform == "win32" else "fork")
            with ctx.Pool(workers, initializer=_init, initargs=(plans, starts, xf, fps)) as pool:
                yield from pool.imap(_compose, range(n_frames), chunksize=4)

    try:
        for n, buf in enumerate(frames()):
            proc.stdin.write(buf)
            if preview_dir is not None and n in previews:
                Image.frombytes("RGB", (L.W, L.H), buf).save(preview_dir / f"preview_{n:05d}.jpg", quality=88)
            if n % (fps * 2) == 0:
                el = time.time() - t0
                eta = el / max(1, n) * (n_frames - n)
                sys.stdout.write(f"\r  영상 렌더링 {n / n_frames * 100:5.1f}%  (남은 시간 약 {eta:4.0f}초)   ")
                sys.stdout.flush()
    finally:
        proc.stdin.close()
        proc.wait()
    print(f"\r  영상 렌더링 100.0%  ({total:.1f}초 분량, {time.time() - t0:.0f}초 걸림)          ")
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 인코딩 실패")
    return total
