# alice — 원고로 만드는 9:16 문학 인용 영상

원고만 넣으면 **ChatGPT(OpenAI)** 가 장면을 나누고, 유화풍 그림과 내레이션을 만들어
기준 영상(「문학으로 알아보는 대구 학부모 교육」)과 같은 구성·브랜딩의 **세로 1080×1920 영상**을 자동으로 완성합니다.

```
원고.txt ──▶ ① 장면 구성 (GPT) ──▶ ② 장면별 그림 (gpt-image) ──▶ ③ 내레이션 (gpt-4o-mini-tts)
                    │                                                      │
                    └──── work/원고/scenes.yaml (검토·수정 가능) ──────────┘
                                         ▼
                 ④ 세로 템플릿 합성 (마스코트·로고·인용구·자막, 줌·전환) ──▶ ⑤ BGM 믹스 ──▶ output/원고.mp4
```

## 화면 구성

| 영역 | 내용 |
|---|---|
| 상단 | 양쪽 마스코트 + 시리즈 제목 (「학부모 교육」 강조색) |
| 흰 띠 | 양쪽 로고 + 섹션 제목 (예: 학습지원) |
| 그림 패널 | 천천히 줌·이동하는 그림 + 아래쪽 인용구, 출처, 원어 문장 |
| 하단 | 해설 자막 + 모서리 장식 |

장면 종류: `intro`(빨간 강조 박스 + 키워드), `quote`(인용 장면), `outro`(앞 장면 그림 콜라주 + 슬로건), `end`(기관 로고).

## 처음 한 번 설정

1. [Python 3.10+](https://www.python.org/downloads/)과 [ffmpeg](https://www.gyan.dev/ffmpeg/builds/)을 설치합니다. (ffmpeg는 PATH에 추가)
2. 이 폴더에서:
   ```bash
   pip install -r requirements.txt
   python setup_fonts.py          # 한글 폰트 받기 (선택, 권장)
   ```
3. `.env.example`을 `.env`로 복사하고 OpenAI API 키를 넣습니다. ([키 발급](https://platform.openai.com/api-keys))

## 사용법

```bash
# 원고 → 영상 (한 번에)
python make_video.py examples/원고_예시.txt

# 장면 구성만 먼저 보고 고치기
python make_video.py 내원고.txt --plan-only
#   → work/내원고/scenes.yaml 을 열어 인용구·자막·그림 묘사를 수정
python make_video.py work/내원고/scenes.yaml

# 배경음악 넣기
python make_video.py 내원고.txt --bgm assets/bgm.mp3

# API 없이 레이아웃만 시험 (자리표시 그림)
python make_video.py examples/scenes_example.yaml --no-ai
```

Windows에서는 원고 파일을 **`영상만들기.bat` 위로 끌어다 놓으면** 됩니다.

결과: `output/<원고이름>.mp4`, 장면별 미리보기: `work/<원고이름>/preview/`

## 품질을 기준 영상에 더 가깝게

- **화풍 고정**: 기준 영상 장면을 캡처해 `assets/style_ref.png`로 저장하고 `config.yaml`의 `style.reference_image`에 지정하면, 모든 그림이 그 화풍을 따라 그려집니다.
- **그림이 마음에 안 들 때**: `scenes.yaml`에서 그 장면의 `image_prompt`만 고쳐 다시 실행하면 그 장면만 새로 그립니다. 나머지는 캐시를 재사용합니다.
- **직접 고른 그림 쓰기**: 장면에 `image: 경로.png`를 넣으면 AI 대신 그 그림을 씁니다.
- **목소리**: `config.yaml`의 `narration.voice`, `narration.instructions`(말투 지시)로 바꿉니다.

## 브랜딩 (마스코트·로고·모서리 장식)

`assets/brand/`의 PNG는 기준 영상에서 그대로 잘라낸 것입니다. 다른 템플릿 영상을 기준으로 바꾸려면:

```bash
python tools/extract_brand.py 새기준영상.mp4
```

자르는 위치는 `tools/extract_brand.py`의 `CROPS`에서 조정합니다. 브랜딩 없이 중립 장식을 쓰려면 `config.yaml`에서 `brand.enabled: false`.

## 비용 참고 (대략)

장면 10개 기준: 그림 10장(high 품질 기준 수천 원 수준) + 원고 분석·내레이션(수십 원). 같은 내용은 캐시되어 다시 과금되지 않습니다.
정확한 요금은 [OpenAI 가격표](https://openai.com/api/pricing/)를 확인하세요. 시험할 때는 `image_quality: low`가 저렴합니다.

## 폴더

```
make_video.py        실행 파일
config.yaml          설정 (모델, 목소리, 색, 브랜딩, BGM)
videogen/            파이프라인 (ai.py: OpenAI, layout.py: 화면, render.py: 움직임·인코딩, audio.py: 소리)
assets/brand/        기준 영상에서 잘라낸 마스코트·로고
examples/            원고 예시, 장면 파일 예시
tools/extract_brand.py  브랜딩 추출 도구
```
