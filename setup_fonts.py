"""무료 한글 폰트(Noto Sans KR, Noto Serif KR, 나눔손글씨 붓)를 fonts/ 에 받습니다.

    python setup_fonts.py

Windows의 맑은 고딕/바탕 등이 있으면 받지 않아도 동작하지만,
받아 두면 어느 컴퓨터에서나 같은 모양으로 나옵니다.
"""
import urllib.request
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fonts"
BASE = "https://github.com/notofonts/noto-cjk/raw/main/"
FILES = {
    "NotoSansKR-Bold.otf": BASE + "Sans/SubsetOTF/KR/NotoSansKR-Bold.otf",
    "NotoSansKR-Medium.otf": BASE + "Sans/SubsetOTF/KR/NotoSansKR-Medium.otf",
    "NotoSerifKR-SemiBold.otf": BASE + "Serif/SubsetOTF/KR/NotoSerifKR-SemiBold.otf",
    "NotoSerif-Italic.ttf": "https://github.com/google/fonts/raw/main/ofl/notoserif/NotoSerif-Italic%5Bwdth,wght%5D.ttf",
    "NanumBrushScript-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/nanumbrushscript/NanumBrushScript-Regular.ttf",
}

DIR.mkdir(exist_ok=True)
for name, url in FILES.items():
    out = DIR / name
    if out.exists():
        print("  있음:", name)
        continue
    try:
        urllib.request.urlretrieve(url, out)
        print("  받음:", name)
    except Exception as e:  # noqa: BLE001
        print("  실패:", name, e)
