# PianoForge Backend

FastAPI API + Celery 워커 + 오디오 분석 파이프라인. 하나의 Python 패키지(`pianoforge`)를 두 방식으로 실행한다.

| 프로세스 | 명령 | 역할 |
|---|---|---|
| API | `uvicorn pianoforge.api.main:app` | REST, WebSocket, presigned URL 발급 |
| 워커 (cpu) | `celery -A pianoforge.worker.celery_app worker -Q cpu` | ingest, rhythm, tonal, merge, finalize, 유지보수 |
| 워커 (ml) | `celery -A pianoforge.worker.celery_app worker -Q ml -c 1` | 음원 분리, 음 전사 (GPU 선택) |
| beat | `celery -A pianoforge.worker.celery_app beat` | 보존기한 정리, 멈춘 작업 회수 (인스턴스 1개만) |

## 요구 사항

- Python 3.11+
- ffmpeg / ffprobe
- libcairo2 (PDF 변환), 선택: fluidsynth + 피아노 SoundFont (예: `fluid-soundfont-gm`)
- PostgreSQL 14+ (`citext` 확장)
- Redis 6+
- S3 호환 스토리지 (개발 환경: MinIO)

## 설치

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # DSP fallback 엔진만 설치
pip install -e ".[dev,ml]"       # + Demucs, Basic Pitch (torch 포함, 수 GB)
```

`ml` extra가 없어도 파이프라인은 동작한다. 다만 결과의 `warnings`와 `engines`에 강등된 엔진이 기록된다.

## 로컬 실행 (Docker 없이)

```bash
cp ../.env.example .env          # PF_* 값 확인
alembic upgrade head
uvicorn pianoforge.api.main:app --reload --port 8000
celery -A pianoforge.worker.celery_app worker -Q cpu,ml -c 2 --prefetch-multiplier 1
```

Docker Compose 기반 전체 스택은 Phase 5에서 `infra/`에 제공한다.

## 분석 엔진과 Fallback

설정 값은 쉼표 구분 체인이다. 설치되어 있고 실패하지 않은 첫 번째 엔진을 사용한다.

| 설정 | 기본값 | 비고 |
|---|---|---|
| `PF_SEPARATOR_CHAIN` | `demucs,hpss,passthrough` | Demucs 실패(OOM 등) 시 HPSS로 자동 전환 |
| `PF_TRANSCRIBER_CHAIN` | `basic_pitch,pyin` | pYIN은 단선율 전용. 화성은 코드 인식 결과로 합성 |
| `PF_BEAT_TRACKER_CHAIN` | `madmom,librosa,fixed` | madmom 0.16은 최신 numpy에서 import가 실패해 자동으로 건너뜀 |
| `PF_KEY_DETECTOR_CHAIN` | `krumhansl` | |
| `PF_CHORD_RECOGNIZER_CHAIN` | `hmm,template` | |
| `PF_ENGRAVER_CHAIN` | `verovio,musescore` | PDF 악보. 둘 다 실패하면 MusicXML만 제공하고 경고를 남김 |
| `PF_RENDERER_CHAIN` | `fluidsynth,synth` | 피아노 오디오. FluidSynth에는 SoundFont가 필요 (`PF_SOUNDFONT_PATH`) |

워커는 기동 시 `adapter_availability` 로그로 가용성 매트릭스를 출력한다.

### 알려진 한계 (DSP fallback)

- **librosa 비트 추적기의 옥타브 모호성:** 8분음표 하이햇이 계속되는 곡은 매우 느리거나(<75 BPM) 빠른(>140 BPM) 템포에서 2배 또는 1/2로 추적될 수 있다. 87–128 BPM 합성 테스트에서는 템포 오차 ±0.1%, 비트 오차 중앙값 약 30ms이다.
- **HPSS 분리:** 보컬과 반주가 겹치는 대역에서는 누설이 크다. 멜로디 추출 정확도는 Demucs + Basic Pitch 조합이 가장 높다.

## 테스트

```bash
ruff check src tests && ruff format --check src tests
mypy src
pytest tests/unit                               # 외부 서비스 불필요

# 통합 테스트: 실제 PostgreSQL + Redis, S3는 moto 서버, Celery는 eager 모드
PF_TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/pianoforge_test \
PF_TEST_REDIS_URL=redis://localhost:6379/15 \
pytest tests
```

통합 테스트는 매 세션마다 테스트 DB를 `downgrade base → upgrade head`로 초기화한다. **운영 DB를 지정하지 않도록 주의한다.**

## 디렉토리

```text
src/pianoforge/
├── config.py, logging.py, events.py
├── api/          # FastAPI: main, deps, security, ratelimit, errors, schemas, routers/
├── db/           # SQLAlchemy 모델, enum, 세션
├── storage/      # S3 클라이언트, 키 규칙
├── audio/        # ffprobe 검증, ffmpeg 디코딩, 라우드니스 정규화
├── analysis/     # IR, Adapter 인터페이스, Registry, adapters/, merge, structure, service
├── arrangement/  # 편곡 엔진: profiles, timeline, melody, harmony, voicing, patterns,
│                 #   texture, playability, fingering, engine → ScoreIR
├── export/       # midi, musicxml, engrave(PDF), render_audio(WAV), exporter
└── worker/       # Celery 앱, 베이스 태스크, 진행률, 파이프라인, tasks/
```
