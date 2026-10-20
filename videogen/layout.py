"""9:16 화면 구성 요소를 그립니다 (정지 레이어).

화면 배치 (1080x1920 기준, 기준 영상의 가로 배치를 세로로 재배치)
  0~230     상단 종이 띠: 양쪽 마스코트 + 시리즈 제목(2줄)
  230~350   흰 띠: 양쪽 로고 + 섹션 제목 (마스코트가 이 띠 뒤에서 살짝 보이는 구조)
  350~1560  그림 패널 (천천히 움직이는 그림 + 하단 인용구)
  1560~1920 하단 종이 띠: 해설 자막 + 아래 모서리 장식
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import fonts

W, H = 1080, 1920
TOP_H = 230                      # 상단 종이 띠
BAND_Y0, BAND_Y1 = 230, 350      # 흰 제목 띠
PANEL_Y0, PANEL_Y1 = 350, 1560
PANEL_H = PANEL_Y1 - PANEL_Y0
CAPTION_CY = 1722


# ───────────────────────── 기본 도구 ─────────────────────────
def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@dataclass
class Layer:
    """화면 위 (x, y) 위치에 놓이는 반투명 조각."""
    x: int
    y: int
    rgb: np.ndarray    # h x w x 3 float32
    a: np.ndarray      # h x w x 1 float32 (0~1)

    @staticmethod
    def from_rgba(img: Image.Image, x: int = 0, y: int = 0) -> "Layer | None":
        bbox = img.getbbox()
        if not bbox:
            return None
        crop = img.crop(bbox)
        arr = np.asarray(crop, dtype=np.float32)
        return Layer(x + bbox[0], y + bbox[1], arr[..., :3], arr[..., 3:4] / 255.0)

    def draw_on(self, frame: np.ndarray, opacity: float = 1.0, dy: int = 0) -> None:
        if opacity <= 0.001:
            return
        y0 = self.y + dy
        h, w = self.a.shape[:2]
        fy0, fy1 = max(0, y0), min(frame.shape[0], y0 + h)
        fx0, fx1 = max(0, self.x), min(frame.shape[1], self.x + w)
        if fy1 <= fy0 or fx1 <= fx0:
            return
        ly0, lx0 = fy0 - y0, fx0 - self.x
        a = self.a[ly0:ly0 + fy1 - fy0, lx0:lx0 + fx1 - fx0] * opacity
        rgb = self.rgb[ly0:ly0 + fy1 - fy0, lx0:lx0 + fx1 - fx0]
        region = frame[fy0:fy1, fx0:fx1]
        frame[fy0:fy1, fx0:fx1] = region * (1 - a) + rgb * a


def wrap(text: str, font, max_w: int) -> list[str]:
    """한글 줄바꿈: 직접 넣은 줄바꿈은 지키고, 넘치면 띄어쓰기 기준(없으면 글자 단위)으로 나눔."""
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for word in words:
            cand = word if not cur else cur + " " + word
            if font.getlength(cand) <= max_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            cur = ""
            # 단어 하나가 너무 길면 글자 단위로 자름
            for ch in word:
                if font.getlength(cur + ch) > max_w and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
        lines.append(cur)
    return [l for l in lines if l is not None]


def wrap_balanced(text: str, font, max_w: int) -> list[str]:
    """줄 수는 최소로 하되 줄 길이를 고르게 (마지막 줄에 한두 글자만 남는 것 방지)."""
    lines = wrap(text, font, max_w)
    if len(lines) <= 1 or "\n" in str(text):
        return lines
    n = len(lines)
    lo, hi = max_w * 0.5, max_w
    for _ in range(14):
        mid = (lo + hi) / 2
        if len(wrap(text, font, int(mid))) <= n:
            hi = mid
        else:
            lo = mid
    return wrap(text, font, int(hi) + 1)


def text_block(draw: ImageDraw.ImageDraw, lines, font, cx: int, top: int, fill, spacing=1.32,
               align="center", left: int | None = None, shadow=None) -> int:
    """여러 줄 글자를 그리고 끝난 y 좌표를 돌려줌."""
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * spacing)
    y = top
    for line in lines:
        w = font.getlength(line)
        x = cx - w / 2 if align == "center" else (left or 0)
        if shadow:
            draw.text((x + 2, y + 3), line, font=font, fill=shadow)
        draw.text((x, y), line, font=font, fill=fill)
        y += lh
    return y


def block_height(lines, font, spacing=1.32) -> int:
    asc, desc = font.getmetrics()
    return int((asc + desc) * spacing) * len(lines)


def fit_lines(text: str, role: str, size: int, max_w: int, max_h: int, min_size: int = 30, spacing=1.32):
    """주어진 칸에 들어갈 때까지 글자 크기를 줄임."""
    while True:
        f = fonts.font(role, size)
        lines = wrap_balanced(text, f, max_w)
        if block_height(lines, f, spacing) <= max_h or size <= min_size:
            return f, lines
        size -= 2


# ───────────────────────── 배경 ─────────────────────────
_paper_cache: dict = {}


def paper(colors: dict) -> Image.Image:
    key = colors["paper"]
    if key in _paper_cache:
        return _paper_cache[key].copy()
    base = np.zeros((H, W, 3), np.float32) + np.array(hex2rgb(colors["paper"]), np.float32)
    rng = np.random.default_rng(7)
    # 종이 섬유 질감
    noise = rng.normal(0, 1, (H // 4, W // 4)).astype(np.float32)
    noise = np.asarray(Image.fromarray(((noise * 18) + 128).clip(0, 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), np.float32) - 128
    fine = rng.normal(0, 1.3, (H, W)).astype(np.float32)
    base += (noise * 0.22 + fine)[..., None]
    # 공책처럼 아주 옅은 가로줄
    for y in range(40, H, 96):
        base[y:y + 2] -= 5
    img = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    _paper_cache[key] = img
    return img.copy()


def _star(draw, cx, cy, r, fill, rot=0.0):
    pts = []
    for i in range(10):
        rr = r if i % 2 == 0 else r * 0.45
        ang = rot + math.pi / 2 + i * math.pi / 5
        pts.append((cx + rr * math.cos(ang), cy - rr * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def _heart(draw, cx, cy, s, fill):
    draw.ellipse((cx - s, cy - s * 0.6, cx, cy + s * 0.4), fill=fill)
    draw.ellipse((cx, cy - s * 0.6, cx + s, cy + s * 0.4), fill=fill)
    draw.polygon([(cx - s * 0.97, cy + 0.05 * s), (cx + s * 0.97, cy + 0.05 * s), (cx, cy + s * 1.05)], fill=fill)


def _torn_corner(draw, corner: str, color, size: int, seed: int):
    """종이를 찢어 붙인 듯한 모서리 색 조각."""
    rnd = random.Random(seed)
    pts = []
    steps = 14
    for i in range(steps + 1):
        t = i / steps
        jitter = rnd.uniform(-10, 10)
        pts.append((t * size + jitter * 0.3, (1 - t) * size + jitter))
    if corner == "tl":
        poly = [(0, 0)] + pts
    elif corner == "br":
        poly = [(W, H)] + [(W - p[0], H - p[1]) for p in pts]
    elif corner == "tr":
        poly = [(W, 0)] + [(W - p[0], p[1]) for p in pts]
    else:
        poly = [(0, H)] + [(p[0], H - p[1]) for p in pts]
    draw.polygon(poly, fill=color)


def decorate(img: Image.Image, colors: dict) -> None:
    """모서리 장식: 색종이 조각, 별, 하트, 동그라미 (원본 브랜드 캐릭터 대신 중립 장식)."""
    d = colors["decor"]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    _torn_corner(dr, "tl", hex2rgb(d[0]) + (255,), 150, 1)
    _torn_corner(dr, "tl", hex2rgb(d[1]) + (255,), 95, 2)
    _torn_corner(dr, "br", hex2rgb(d[1]) + (255,), 170, 3)
    _torn_corner(dr, "br", hex2rgb(d[0]) + (255,), 100, 4)
    # 왼쪽 위
    dr.ellipse((118, 48, 178, 108), fill=hex2rgb(d[2]) + (255,))
    _star(dr, 205, 140, 24, hex2rgb(d[2]) + (255,), 0.2)
    dr.ellipse((36, 190, 62, 216), fill=hex2rgb(d[5]) + (230,))
    # 오른쪽 위
    _heart(dr, 950, 92, 30, hex2rgb(d[4]) + (255,))
    _star(dr, 1030, 175, 30, hex2rgb(d[2]) + (255,), -0.25)
    dr.ellipse((995, 30, 1043, 78), fill=hex2rgb(d[3]) + (255,))
    # 아래쪽
    dr.ellipse((48, 1838, 90, 1880), fill=hex2rgb(d[3]) + (255,))
    _star(dr, 128, 1868, 22, hex2rgb(d[2]) + (255,), 0.4)
    _heart(dr, 900, 1872, 18, hex2rgb(d[4]) + (255,))
    # 살짝 그림자로 종이 붙인 느낌
    shadow = layer.split()[3].filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.28))
    sh = Image.new("RGBA", img.size, (60, 40, 20, 0))
    sh.putalpha(shadow)
    img.paste(sh, (3, 5), sh)
    img.paste(layer, (0, 0), layer)


_brand_cache: dict = {}


def brand_piece(cfg: dict, resolve, name: str, scale: float | None = None) -> Image.Image | None:
    """assets/brand/ 의 투명 PNG (tools/extract_brand.py 로 만든 것)."""
    b = cfg.get("brand") or {}
    if not b.get("enabled", True):
        return None
    d = resolve(b.get("dir", "assets/brand"))
    p = d / name if d else None
    if not p or not p.exists():
        return None
    s = float(scale if scale is not None else b.get("scale", 1.28))
    key = (str(p), s)
    if key not in _brand_cache:
        im = Image.open(p).convert("RGBA")
        _brand_cache[key] = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return _brand_cache[key]


def place_logos(img: Image.Image, logos: list, resolve) -> None:
    """config.yaml의 logos: 로 추가하는 로고."""
    for item in logos or []:
        p = resolve(item.get("path"))
        if not p or not p.exists():
            continue
        lg = Image.open(p).convert("RGBA")
        h = int(item.get("height", 90))
        lg = lg.resize((max(1, int(lg.width * h / lg.height)), h), Image.LANCZOS)
        pos = item.get("position", "top-right")
        m = int(item.get("margin", 36))
        xy = {
            "top-left": (m, m), "top-right": (W - lg.width - m, m),
            "bottom-left": (m, H - lg.height - m), "bottom-right": (W - lg.width - m, H - lg.height - m),
            "center": ((W - lg.width) // 2, H - lg.height - m),
            "band-left": (20, (BAND_Y0 + BAND_Y1 - lg.height) // 2),
            "band-right": (W - lg.width - 20, (BAND_Y0 + BAND_Y1 - lg.height) // 2),
        }.get(pos, (m, m))
        img.paste(lg, xy, lg)


def header(img: Image.Image, scene: dict, cfg: dict, side_w: int) -> None:
    """상단 띠: 시리즈 제목 2줄(일반 + 강조색), 흰 띠: 섹션 제목."""
    colors = cfg["colors"]
    dr = ImageDraw.Draw(img)
    text = hex2rgb(colors["text"])
    accent = hex2rgb(colors["accent"])
    series = cfg["series_title"]
    acc = cfg.get("series_accent") or series.rpartition(" ")[2]
    first = series[: series.rfind(acc)].strip() if acc in series else series
    max_w = W - 2 * side_w - 10
    f1, l1 = fit_lines(first, "sans_bold", 42, max_w, 60, 26, 1.1)
    f2, l2 = fit_lines(acc, "sans_bold", 64, max_w, 80, 34, 1.1)
    h1 = block_height(l1[:1], f1, 1.1) if first else 0
    h2 = block_height(l2[:1], f2, 1.1)
    top = (TOP_H - (h1 + 6 + h2)) // 2 + 4
    if first:
        text_block(dr, l1[:1], f1, W // 2, top, text, 1.1)
    text_block(dr, l2[:1], f2, W // 2, top + h1 + 6, accent, 1.1)

    section = scene.get("section")
    if section:
        f3, l3 = fit_lines(section, "sans_bold", 66, W - 2 * 200, BAND_Y1 - BAND_Y0 - 20, 36, 1.0)
        hh = block_height(l3[:1], f3, 1.0)
        text_block(dr, l3[:1], f3, W // 2, (BAND_Y0 + BAND_Y1 - hh) // 2 - 4, accent, 1.0)


def caption_layer(text: str, colors: dict) -> Layer | None:
    if not text:
        return None
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    f, lines = fit_lines(text, "sans", 46, W - 170, 150, 32, 1.4)
    hgt = block_height(lines, f, 1.4)
    text_block(dr, lines, f, W // 2, CAPTION_CY - hgt // 2, hex2rgb(colors["text"]) + (255,), 1.4)
    return Layer.from_rgba(img)


def base_frame(scene: dict, cfg: dict, resolve) -> np.ndarray:
    colors = cfg["colors"]
    img = paper(colors)
    ml = brand_piece(cfg, resolve, "mascot_left.png")
    mr = brand_piece(cfg, resolve, "mascot_right.png")
    if ml is not None and mr is not None:
        # 기준 영상의 마스코트·모서리 장식을 그대로 사용
        img.paste(ml, (0, TOP_H - ml.height), ml)
        img.paste(mr, (W - mr.width, TOP_H - mr.height), mr)
        bl = brand_piece(cfg, resolve, "corner_bottom_left.png")
        br = brand_piece(cfg, resolve, "corner_bottom_right.png")
        if bl is not None:
            img.paste(bl, (0, H - bl.height), bl)
        if br is not None:
            img.paste(br, (W - br.width, H - br.height), br)
        side_w = max(ml.width, mr.width)
    else:
        decorate(img, colors)
        side_w = 230
    dr = ImageDraw.Draw(img)
    # 흰 제목 띠 (패널 윗부분과 이어짐)
    dr.rectangle((0, BAND_Y0, W, BAND_Y1), fill=(255, 255, 255))
    for name, side in (("logo_left.png", "l"), ("logo_right.png", "r")):
        lg = brand_piece(cfg, resolve, name, (cfg.get("brand") or {}).get("logo_scale", 1.05))
        if lg is not None:
            x = 18 if side == "l" else W - lg.width - 18
            img.paste(lg, (x, (BAND_Y0 + BAND_Y1 - lg.height) // 2), lg)
    header(img, scene, cfg, side_w)
    line = tuple(int(c * 0.93) for c in hex2rgb(colors["paper"]))
    for y in (CAPTION_CY - 112, CAPTION_CY + 112):
        dr.line((0, y, W, y), fill=line, width=2)
    place_logos(img, cfg.get("logos"), resolve)
    return np.asarray(img, dtype=np.float32)


# ───────────────────────── 그림 패널 ─────────────────────────
def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    return img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)


def tone_of(img: Image.Image) -> tuple[int, int, int]:
    """그림 아래쪽 평균색을 밝게 → 인용구 바탕색."""
    small = img.convert("RGB").resize((32, 48))
    arr = np.asarray(small, np.float32)[28:]
    c = arr.reshape(-1, 3).mean(0)
    paper = np.array([238, 226, 206], np.float32)
    c = c * 0.45 + paper * 0.55
    return tuple(int(v) for v in c.clip(0, 255))  # type: ignore[return-value]


def quote_layers(scene: dict, img: Image.Image, colors: dict) -> tuple[Layer | None, Layer | None]:
    """(바탕 그라데이션, 인용구 글자) 두 겹."""
    tone = tone_of(img)
    q = scene.get("quote", "")
    src = scene.get("source", "")
    orig = scene.get("original", "")
    if not (q or src or orig):
        return None, None

    max_w = W - 150
    fq, ql = fit_lines(f"“{q}”" if q else "", "serif", 62, max_w, 400, 36, 1.2)
    fs = fonts.font("sans", 30)
    fo, ol = fit_lines(orig, "latin_italic", 30, max_w, 140, 22, 1.3) if orig else (fonts.font("latin_italic", 30), [])
    h_q = block_height(ql, fq, 1.2)
    h_s = 52 if src else 0
    h_o = (block_height(ol, fo, 1.3) + 22) if ol else 0
    total = h_s + h_q + h_o
    top = PANEL_H - 70 - total

    # 그라데이션: 글자 시작보다 위에서부터 서서히
    g0 = max(0, top - 260)
    grad = np.zeros((PANEL_H, W, 4), np.float32)
    grad[..., :3] = tone
    yy = np.arange(PANEL_H, dtype=np.float32)
    t = ((yy - g0) / max(1, (top + 120) - g0)).clip(0, 1)
    t = t * t * (3 - 2 * t)
    grad[..., 3] = (t * 0.93)[:, None] * 255
    grad_img = Image.fromarray(grad.astype(np.uint8), "RGBA")

    txt = Image.new("RGBA", (W, PANEL_H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(txt)
    muted = hex2rgb(colors["muted"]) + (255,)
    y = top
    if src:
        w = fs.getlength(src)
        dr.text(((W - w) / 2, y), src, font=fs, fill=muted)
        y += h_s
    y = text_block(dr, ql, fq, W // 2, y, hex2rgb(colors["quote"]) + (255,), 1.2)
    if ol:
        text_block(dr, ol, fo, W // 2, y + 22, muted, 1.3)
    return Layer.from_rgba(grad_img, 0, PANEL_Y0), Layer.from_rgba(txt, 0, PANEL_Y0)


def intro_panel(scene: dict, colors: dict, bg_img: Image.Image | None) -> Image.Image:
    peach = (243, 222, 203)
    panel = Image.new("RGB", (W, PANEL_H), peach)
    if bg_img is not None:
        faded = cover(bg_img.convert("RGB"), W, PANEL_H).crop((0, 0, W, PANEL_H))
        panel = Image.blend(panel, faded, 0.22)
    return panel


def intro_layers(scene: dict, colors: dict) -> tuple[Layer | None, Layer | None]:
    """키워드 구름(먼저) + 강조 박스 헤드라인(나중)."""
    kw = Image.new("RGBA", (W, PANEL_H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(kw)
    words = scene.get("keywords") or []
    rnd = random.Random(3)
    slots = [(0.3, 0.1), (0.72, 0.15), (0.24, 0.24), (0.7, 0.29), (0.28, 0.7), (0.74, 0.75), (0.34, 0.84), (0.68, 0.9), (0.5, 0.95)]
    for i, wd in enumerate(words[: len(slots)]):
        f = fonts.font("sans_bold" if i % 2 == 0 else "sans", rnd.choice([40, 46, 54]))
        x, y = slots[i]
        a = rnd.choice([110, 140, 170])
        tw = f.getlength(wd)
        dr.text((x * W - tw / 2, y * PANEL_H), wd, font=f, fill=(120, 100, 85, a))

    head = Image.new("RGBA", (W, PANEL_H), (0, 0, 0, 0))
    dh = ImageDraw.Draw(head)
    headline = scene.get("headline", "")
    rest = scene.get("text", "")
    # "을 문학으로…"처럼 조사로 시작하면 조사는 박스 바로 오른쪽에 붙임
    particle = ""
    for p_ in ("을", "를", "이", "가", "은", "는", "의", "과", "와", "로", "으로"):
        if rest.startswith(p_ + " ") or rest == p_:
            particle, rest = p_, rest[len(p_):].strip()
            break
    fp = fonts.font("sans_bold", 56)
    p_w = fp.getlength(particle) + 30 if particle else 0
    fh, hl = fit_lines(headline, "sans_bold", 64, int(W - 200 - p_w), 200, 36, 1.25)
    box_w = max(fh.getlength(l) for l in hl) + 64 if hl else 0
    box_h = block_height(hl, fh, 1.25) + 40
    fr, rl = fit_lines(rest, "sans_bold", 56, W - 160, 220, 34, 1.3) if rest else (fp, [])
    total = box_h + (40 + block_height(rl, fr, 1.3) if rl else 0)
    top = PANEL_H // 2 - total // 2
    bx0 = (W - box_w - p_w) / 2
    hl_rgb = hex2rgb(colors["highlight"])
    edge = (60, 60, 60, 255)
    # 입체 박스 (윗면, 옆면, 앞면)
    dh.polygon([(bx0 + box_w, top), (bx0 + box_w + 22, top - 16), (bx0 + box_w + 22, top + box_h - 16), (bx0 + box_w, top + box_h)], fill=(250, 250, 250, 255), outline=edge)
    dh.polygon([(bx0, top), (bx0 + 22, top - 16), (bx0 + box_w + 22, top - 16), (bx0 + box_w, top)], fill=(255, 255, 255, 255), outline=edge)
    dh.rectangle((bx0, top, bx0 + box_w, top + box_h), fill=hl_rgb + (255,), outline=edge, width=2)
    text_block(dh, hl, fh, int(bx0 + box_w / 2), top + 14, (255, 255, 255, 255), 1.25)
    dark = hex2rgb(colors["text"]) + (255,)
    if particle:
        asc, desc = fp.getmetrics()
        dh.text((bx0 + box_w + 34, top + box_h - (asc + desc) - 4), particle, font=fp, fill=dark)
    if rl:
        text_block(dh, rl, fr, W // 2, top + box_h + 40, dark, 1.3)
    return Layer.from_rgba(kw, 0, PANEL_Y0), Layer.from_rgba(head, 0, PANEL_Y0)


def outro_panel(images: list[Image.Image], colors: dict) -> Image.Image:
    """앞 장면 그림들을 폴라로이드처럼 흩뿌린 콜라주."""
    panel = Image.new("RGB", (W, PANEL_H), hex2rgb(colors["paper"]))
    rnd = random.Random(11)
    spots = [(0.22, 0.2), (0.7, 0.18), (0.45, 0.42), (0.18, 0.62), (0.78, 0.58), (0.4, 0.82), (0.72, 0.86), (0.12, 0.92)]
    for img, (x, y) in zip(images, spots):
        ph = cover(img.convert("RGB"), 360, 420).crop((0, 0, 360, 420))
        card = Image.new("RGB", (390, 500), (252, 250, 246))
        card.paste(ph, (15, 15))
        card = card.convert("RGBA").rotate(rnd.uniform(-14, 14), resample=Image.BICUBIC, expand=True)
        sh = Image.new("RGBA", card.size, (40, 30, 20, 0))
        sh.putalpha(card.split()[3].filter(ImageFilter.GaussianBlur(8)).point(lambda v: int(v * 0.35)))
        px, py = int(x * W - card.width / 2), int(y * PANEL_H - card.height / 2)
        panel.paste(sh, (px + 6, py + 10), sh)
        panel.paste(card, (px, py), card)
    return panel


def outro_layers(scene: dict, colors: dict) -> tuple[Layer | None, Layer | None]:
    veil = Image.new("RGBA", (W, PANEL_H), (250, 246, 240, 205))
    txt = Image.new("RGBA", (W, PANEL_H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(txt)
    headline = scene.get("headline", "")
    sub = scene.get("text", "")
    fh, hl = fit_lines(headline, "brush", 92, W - 140, 260, 48, 1.2)
    fs, sl = fit_lines(sub, "brush", 76, W - 140, 220, 40, 1.25)
    total = block_height(hl, fh, 1.2) + 30 + block_height(sl, fs, 1.25)
    y = PANEL_H // 2 - total // 2
    hl_rgb = hex2rgb(colors["highlight"]) + (255,)
    dark = (35, 35, 35, 255)
    for line in hl:
        w = fh.getlength(line)
        x = (W - w) / 2
        # 첫 글자만 강조색
        if line:
            dr.text((x, y), line[0], font=fh, fill=hl_rgb)
            dr.text((x + fh.getlength(line[0]), y), line[1:], font=fh, fill=dark)
        asc, desc = fh.getmetrics()
        y += int((asc + desc) * 1.2)
    text_block(dr, sl, fs, W // 2, y + 30, dark, 1.25)
    return Layer.from_rgba(veil, 0, PANEL_Y0), Layer.from_rgba(txt, 0, PANEL_Y0)


def end_card(scene: dict, colors: dict, resolve) -> Image.Image:
    """기관명/로고 엔딩 패널."""
    panel = Image.new("RGB", (W, PANEL_H), (255, 255, 255))
    logo = resolve(scene.get("logo") or "assets/brand/logo_end.png")
    if logo and logo.exists():
        lg = Image.open(logo).convert("RGBA")
        s = min(880 / lg.width, 320 / lg.height)
        lg = lg.resize((int(lg.width * s), int(lg.height * s)), Image.LANCZOS)
        panel.paste(lg, ((W - lg.width) // 2, (PANEL_H - lg.height) // 2), lg)
    else:
        dr = ImageDraw.Draw(panel)
        f, lines = fit_lines(scene.get("headline", ""), "sans_bold", 64, W - 200, 300, 36)
        hgt = block_height(lines, f)
        text_block(dr, lines, f, W // 2, PANEL_H // 2 - hgt // 2, hex2rgb(colors["text"]))
    return panel


def placeholder(prompt: str, seed: int, w=1024, h=1536) -> Image.Image:
    """AI 없이 시험할 때 쓰는 그림 자리표시 (따뜻한 색 붓터치 느낌)."""
    rnd = np.random.default_rng(seed)
    palettes = [[(214, 160, 96), (120, 150, 150), (238, 205, 160)], [(170, 120, 80), (230, 190, 140), (90, 110, 120)],
                [(200, 140, 110), (245, 220, 180), (110, 130, 100)]]
    pal = palettes[seed % len(palettes)]
    yy = np.linspace(0, 1, h)[:, None, None]
    top, mid, bot = (np.array(c, np.float32) for c in pal)
    img = np.where(yy < 0.5, top * (1 - yy * 2) + mid * yy * 2, mid * (2 - yy * 2) + bot * (yy * 2 - 1))
    img = np.broadcast_to(img, (h, w, 3)).copy()
    pil = Image.fromarray(img.clip(0, 255).astype(np.uint8))
    dr = ImageDraw.Draw(pil, "RGBA")
    for _ in range(260):
        x, y = rnd.integers(0, w), rnd.integers(0, int(h * 0.7))
        r = int(rnd.integers(12, 70))
        c = tuple(int(v) for v in rnd.choice(np.array(pal + [(250, 235, 210)]), 1)[0]) + (int(rnd.integers(30, 90)),)
        dr.ellipse((x - r, y - r * 0.5, x + r, y + r * 0.5), fill=c)
    # 두 사람 실루엣
    for i, (cx, s) in enumerate([(0.38, 1.0), (0.6, 0.72)]):
        x, base = int(cx * w), int(h * 0.62)
        hh = int(380 * s)
        dr.ellipse((x - 45 * s, base - hh - 90 * s, x + 45 * s, base - hh), fill=(60, 45, 35, 200))
        dr.rounded_rectangle((x - 80 * s, base - hh, x + 80 * s, base), radius=int(50 * s), fill=(70, 55, 45, 200))
    return pil.filter(ImageFilter.GaussianBlur(1.5))
