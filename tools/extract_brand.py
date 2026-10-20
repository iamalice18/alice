"""기준 영상에서 로고·마스코트·테두리 장식을 잘라 투명 PNG로 저장.

    python tools/extract_brand.py 기준영상.mp4

기준 영상(1600x900 가로형)의 고정 위치에서 잘라내므로, 같은 템플릿으로 만든
영상이면 그대로 동작합니다. 위치가 다르면 아래 CROPS 좌표를 고치세요.
결과는 assets/brand/ 에 저장되고 config.yaml에서 자동으로 사용됩니다.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "brand"

# (파일명, 추출 시각(초), 좌표 x0,y0,x1,y1 @1600x900, 배경 종류)
CROPS = [
    ("mascot_left.png", 97, (0, 0, 268, 180), "paper"),
    ("mascot_right.png", 97, (1352, 0, 1600, 180), "paper"),
    ("corner_bottom_left.png", 97, (0, 752, 115, 900), "paper"),
    ("corner_bottom_right.png", 97, (1485, 752, 1600, 900), "paper"),
    ("logo_left.png", 97, (10, 190, 100, 276), "white"),
    ("logo_right.png", 97, (1432, 188, 1595, 270), "white"),
    ("logo_end.png", 101, (488, 388, 1118, 512), "white"),
]


def grab(video: str, t: float, tmp: Path) -> Image.Image:
    p = tmp / f"f_{t}.png"
    if not p.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1",
                        "-vf", "scale=1600:900", str(p)], check=True)
    return Image.open(p).convert("RGB")


def key(img: Image.Image, mode: str) -> Image.Image:
    a = np.asarray(img, np.float32)
    lum = a.mean(2)
    chroma = a.max(2) - a.min(2)
    if mode == "white":
        # 흰 배경 제거, 가장자리는 부드럽게
        alpha = np.clip((252 - lum) / 22, 0, 1)
        alpha = np.maximum(alpha, np.clip((chroma - 12) / 20, 0, 1))
    else:
        # 회백색 종이(약 242) 제거. 흰 띠(250 이상)와 그림자, 색 조각은 남김
        bg = (np.abs(lum - 242) < 7) & (chroma < 9)
        m = Image.fromarray((~bg * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
        alpha = np.asarray(m.filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255
    rgba = np.dstack([a, alpha * 255]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    video = sys.argv[1]
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, t, box, mode in CROPS:
            piece = key(grab(video, t, tmp).crop(box), mode)
            piece.save(OUT / name)
            print("  저장:", OUT / name, piece.size)


if __name__ == "__main__":
    main()
