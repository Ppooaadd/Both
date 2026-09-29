# 정확도 벤치마크

분석·편곡 파이프라인의 정확도를 정답이 있는 곡으로 수치화한다. 알고리즘을 바꿀 때마다 이 숫자로 효과를 확인한다.

```bash
cd backend
pip install -e ".[dev,ml]" mir_eval && pip install --no-deps basic-pitch==0.4.0
python -m bench.fetch_vocadito        # 실제 노래 데이터 (선택, 약 60 MB)
python -m bench.run                   # 합성곡 10개
python -m bench.run --real            # + 실제 노래 12곡
python -m bench.run --beats librosa,fixed   # ML 없는 fallback 박자 추적 평가
python -m bench.compare a.json b.json # 결과 파일 비교
```

음원 분리 결과는 `bench/.cache/`에 곡별로 캐시된다(`--fresh`로 다시 계산).

## 곡 구성

| 곡 | 확인하는 것 |
|---|---|
| `pop_drift` | 사람 연주처럼 흔들리는 템포(±3 %)와 박자 흔들림 |
| `ballad_nodrums` | 드럼 없는 발라드, 아르페지오 반주, 못갖춘마디 |
| `waltz`, `inst_waltz` | 3/4 박자 |
| `fast_minor` | 164 BPM 단조 |
| `swing` | 스윙 8분음표 |
| `sixteenths` | 16분음표 멜로디 |
| `intro_pickup` | 4마디 전주 + 2박 못갖춘마디 |
| `tempo_change` | 곡 중간 템포 변화 (90 → 120 BPM) |
| `inst_pop` | 보컬 없는 곡 (멜로디가 반주 트랙에 섞임) |
| `vocadito_*` | 실제 사람 노래(vocadito, CC BY 4.0) + 합성 반주 |

## 지표

| 지표 | 의미 |
|---|---|
| `beat_f`, `downbeat_f` | 박자·마디 첫 박 F-measure (±70 ms) |
| `mel_f` | 멜로디 채보 F1 (음 시작 ±50 ms, 음높이 ±50 cent) |
| `chord_acc` | 코드 근음·장단조 일치율 |
| `beg/int/adv_recall_grid` | 난이도 격자 위의 원곡 멜로디 음이 편곡에 남은 비율 (빠진 음 측정) |
| `adv_precision` | 편곡 멜로디 음 중 원곡에 있는 음의 비율 (불필요한 음 측정) |
| `adv_onset_err_ms` | 편곡 음과 원곡 음의 시작 시각 차이 중앙값 |
| `adv_render_drift90_ms` | 피아노 음원에서 들리는 음과 원곡 음의 시각 차이 (90 백분위) |

실제 노래 곡은 가수가 반주 박자에 맞춰 부르지 않았으므로 멜로디 지표만 의미가 있다.
