# PianoForge — Phase 1 시스템 설계

> 상태: Phase 1–3 승인 · **Phase 4 구현 완료** (Next.js UI). API 계약은 [api.md](api.md) 참고.

## 1. 설계 원칙

- **분석과 편곡 분리**: 무거운 단계(분리·전사·분석)는 오디오당 1회만 수행하고 결과를 캐시한다. 난이도·파라미터 변경 시 편곡·내보내기 단계만 재실행한다 (재생성 수 초 단위).
- **Adapter + Fallback 체인**: 모든 ML/DSP 엔진은 인터페이스 뒤에 둔다. 런타임에 설치 여부를 감지해 `Demucs → HPSS(librosa) → Passthrough` 식으로 자동 강등한다. 결과에는 사용한 엔진과 버전을 기록한다.
- **중간 표현(IR) 중심**: 분석 결과는 `AnalysisIR`(JSON), 편곡 결과는 `ScoreIR`(JSON)로 표준화한다. MIDI·MusicXML·PDF·오디오는 모두 `ScoreIR`에서 파생된다.
- **대용량 데이터는 S3, 메타데이터는 PostgreSQL**: 노트 이벤트·비트 그리드·코드 시퀀스는 S3 JSON(gzip), DB에는 요약값과 객체 키만 저장한다.
- **보안 기본값**: 원본 파일명 미사용(UUID 키), presigned 업로드 크기 제한, 워커에서 ffprobe 검증, 짧은 TTL 다운로드 URL, 비루트 컨테이너.

## 2. 시스템 아키텍처

```mermaid
flowchart LR
    subgraph Client["브라우저"]
        UI["Next.js App Router<br/>TanStack Query"]
        PR["피아노 롤 (Canvas)<br/>Tone.js 재생"]
        SV["악보 뷰어<br/>OpenSheetMusicDisplay"]
    end

    subgraph Edge["Edge"]
        RP["Reverse Proxy<br/>Caddy / Nginx<br/>TLS · rate limit"]
    end

    subgraph App["Application"]
        WEB["Next.js Server<br/>SSR · 정적 자산"]
        API["FastAPI<br/>REST /api/v1<br/>WebSocket /ws"]
    end

    subgraph Async["비동기 처리"]
        RB[("Redis<br/>broker · result<br/>pub/sub · rate limit")]
        WCPU["Celery Worker: cpu<br/>ingest · analysis<br/>arrange · export"]
        WGPU["Celery Worker: ml<br/>Demucs · Basic Pitch<br/>(GPU 선택)"]
        BEAT["Celery Beat<br/>보존기한 정리 · 쿼터 리셋"]
    end

    subgraph Data["데이터"]
        PG[("PostgreSQL<br/>SQLAlchemy 2 · Alembic")]
        S3[("S3 호환 스토리지<br/>로컬: RustFS")]
    end

    UI --> RP
    RP --> WEB
    RP --> API
    UI -- "presigned PUT<br/>(size 제한)" --> S3
    UI -- "presigned GET<br/>(TTL 5분)" --> S3
    API --> PG
    API --> RB
    API -- "presign" --> S3
    RB --> WCPU
    RB --> WGPU
    BEAT --> RB
    WCPU --> PG
    WGPU --> PG
    WCPU <--> S3
    WGPU <--> S3
    WCPU -- "progress publish" --> RB
    WGPU -- "progress publish" --> RB
    RB -- "subscribe job:{id}" --> API
    API -- "WS push" --> UI
```

### 2.1 처리 파이프라인 (Celery chain)

```mermaid
flowchart TD
    A["1. ingest<br/>ffprobe 검증 · 44.1kHz 변환<br/>loudness 정규화 · sha256"] --> B["2. separate<br/>Demucs htdemucs<br/>vocals / drums / bass / other"]
    B --> C1["3a. rhythm<br/>tempo · beats · downbeats<br/>time signature"]
    C1 --> C2["3b. tonal<br/>key (Krumhansl) · chords<br/>(chroma + HMM Viterbi) · sections"]
    C1 --> C3["3c. transcribe<br/>Basic Pitch<br/>melody(vocals) · bass · harmony(other)"]
    C2 --> D["4. merge → AnalysisIR<br/>비트 그리드 매핑 · skyline 단선율화"]
    C3 --> D
    D --> E["5. arrange<br/>난이도 엔진 → ScoreIR"]
    E --> F1["6a. MIDI<br/>pretty_midi"]
    E --> F2["6b. MusicXML<br/>music21"]
    F2 --> F3["6c. PDF<br/>Verovio → SVG → PDF"]
    F1 --> F4["6d. Audio<br/>FluidSynth + Piano SF2<br/>→ WAV / MP3 (ffmpeg)"]

    R(["파라미터 조절 후 재생성"]) -. "AnalysisIR 재사용" .-> E
```

- 3a(rhythm) 이후 3b/3c를 Celery `group`으로 병렬 실행하고, 4에서 `chord`로 합류한다. 코드 인식은 비트 단위 크로마를 쓰므로 비트 그리드가 먼저 필요하다 (Phase 2 구현 중 조정).
- 제어 흐름 예외(취소 `JobStopped`, Celery soft time limit)는 Adapter fallback을 건너뛰고 즉시 단계를 중단시킨다.
- 각 단계는 멱등(idempotent). 입력 해시 기준으로 S3 결과가 있으면 스킵한다.
- 단계 진행률은 `job:{id}` Redis 채널에 publish → API가 WebSocket으로 중계한다. WS 불가 시 TanStack Query 폴링(`GET /jobs/{id}`)으로 대체한다.

### 2.2 Adapter와 Fallback

| 인터페이스 | 1순위 | Fallback | 최종 Fallback |
|---|---|---|---|
| `SourceSeparator` | Demucs (htdemucs) | librosa HPSS + 저역 필터 | Passthrough (mix 그대로) |
| `NoteTranscriber` | Basic Pitch (ONNX/TFLite) | librosa pYIN (단선율) | — (오류) |
| `BeatTracker` | Beat This! (ISMIR 2024 트랜스포머) | madmom DBN (설치 시) → librosa 시변 템포 DP | 고정 120 BPM 그리드 |
| `KeyDetector` | Krumhansl-Schmuckler (chroma CQT) | — | C major (신뢰도 0) |
| `ChordRecognizer` | chroma 템플릿 + HMM Viterbi | 비트 단위 템플릿 매칭 | — |
| `ScoreEngraver` | Verovio | MuseScore CLI (설치 시) | PDF 미제공 (MusicXML만) |
| `AudioRenderer` | FluidSynth + SF2 | 사인파 합성 (numpy) | — |

- `AdapterRegistry`가 기동 시 `is_available()`로 가용성을 검사하고, 설정(`PF_SEPARATOR=demucs,hpss,passthrough`)의 순서대로 체인을 구성한다.
- 사용된 엔진은 `analyses.engine_versions` / `stems.engine`에 기록되어 UI에 "품질 강등" 배지로 노출된다.

### 2.3 요청 흐름 (업로드 → 결과)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as FastAPI
    participant S as S3 스토리지
    participant R as Redis
    participant W as Worker
    participant D as PostgreSQL

    B->>A: POST /api/v1/uploads (filename, size, mime)
    A->>D: INSERT audio_assets(status=pending)
    A-->>B: presigned POST (content-length-range, 15분)
    B->>S: PUT 원본 오디오
    B->>A: POST /api/v1/projects {upload_id, difficulty, params}
    A->>D: INSERT projects, jobs(status=queued)
    A->>R: enqueue chain(ingest…export)
    A-->>B: 202 {project_id, job_id, ws_ticket}
    B->>A: WS /ws/jobs/{job_id}?ticket=…
    loop 각 단계
        W->>S: 입력 읽기 / 결과 쓰기
        W->>D: UPDATE jobs(stage, progress)
        W->>R: PUBLISH job:{id}
        R-->>A: message
        A-->>B: {stage, progress, eta}
    end
    W->>D: INSERT analyses, arrangements, exports
    A-->>B: {status: succeeded}
    B->>A: GET /api/v1/arrangements/{id}
    A-->>B: ScoreIR + presigned 다운로드 URL
```

## 3. 디렉토리 구조

```text
pianoforge/
├── README.md
├── Makefile                         # dev, test, lint, migrate 단축 명령
├── .env.example
├── docs/
│   ├── architecture.md              # 본 문서
│   ├── api.md                       # REST/WS 계약
│   └── adr/                         # Architecture Decision Records
│       ├── 0001-celery-over-dramatiq.md
│       └── 0002-ir-centric-pipeline.md
├── apps/
│   └── web/                         # Next.js (App Router, TS strict)
│       ├── package.json
│       ├── next.config.ts
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── components.json          # shadcn/ui
│       ├── public/
│       │   └── soundfonts/          # 브라우저 재생용 피아노 샘플
│       └── src/
│           ├── app/
│           │   ├── layout.tsx
│           │   ├── page.tsx                     # 랜딩 + 업로드
│           │   ├── (auth)/login/page.tsx
│           │   ├── (auth)/signup/page.tsx
│           │   ├── projects/page.tsx            # 내 프로젝트 목록
│           │   └── projects/[id]/
│           │       ├── page.tsx                 # 분석 요약 · 진행 상태
│           │       ├── arrange/page.tsx         # 피아노 롤 · 악보 · 파라미터
│           │       └── loading.tsx
│           ├── components/
│           │   ├── ui/                          # shadcn 생성 컴포넌트
│           │   ├── upload/UploadDropzone.tsx
│           │   ├── upload/UploadProgress.tsx
│           │   ├── job/JobStatusStream.tsx      # WS + 폴링 fallback
│           │   ├── job/StageTimeline.tsx
│           │   ├── analysis/AnalysisSummary.tsx # key · tempo · chords
│           │   ├── analysis/ChordLane.tsx
│           │   ├── pianoroll/PianoRoll.tsx      # Canvas 렌더러
│           │   ├── pianoroll/usePianoRollViewport.ts
│           │   ├── score/ScoreViewer.tsx        # OSMD
│           │   ├── player/TransportBar.tsx      # Tone.js
│           │   ├── arrange/ParameterPanel.tsx
│           │   └── export/DownloadMenu.tsx
│           ├── lib/
│           │   ├── api/client.ts                # fetch 래퍼, 에러 정규화
│           │   ├── api/schemas.ts               # zod 스키마 (API 계약)
│           │   ├── api/queries.ts               # TanStack Query 훅
│           │   ├── ws/jobSocket.ts              # 재연결 · 백오프
│           │   ├── audio/player.ts
│           │   └── score-ir.ts                  # ScoreIR 타입
│           └── styles/globals.css
├── backend/                         # Python 3.12, 단일 패키지 · 2개 엔트리포인트
│   ├── pyproject.toml               # extras: [ml], [render], [dev]
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── src/pianoforge/
│   │   ├── config.py                # pydantic-settings
│   │   ├── logging.py               # structlog JSON
│   │   ├── api/
│   │   │   ├── main.py              # FastAPI 앱 팩토리
│   │   │   ├── deps.py              # DB 세션, 현재 사용자
│   │   │   ├── security.py          # JWT, 비밀번호 해시(argon2), WS ticket
│   │   │   ├── ratelimit.py
│   │   │   ├── errors.py
│   │   │   ├── routers/
│   │   │   │   ├── auth.py
│   │   │   │   ├── uploads.py
│   │   │   │   ├── projects.py
│   │   │   │   ├── jobs.py
│   │   │   │   ├── arrangements.py
│   │   │   │   ├── exports.py
│   │   │   │   ├── health.py
│   │   │   │   └── ws.py
│   │   │   └── schemas/             # Pydantic v2 요청/응답 모델
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── session.py
│   │   │   ├── models/              # users, audio_assets, projects, jobs, …
│   │   │   └── repositories/
│   │   ├── storage/
│   │   │   ├── s3.py                # boto3, presign, 키 규칙
│   │   │   └── keys.py
│   │   ├── worker/
│   │   │   ├── celery_app.py        # 큐 라우팅: cpu, ml
│   │   │   ├── progress.py          # Redis publish + DB 갱신
│   │   │   ├── pipeline.py          # chain/group/chord 조립
│   │   │   ├── beat_schedule.py
│   │   │   └── tasks/
│   │   │       ├── ingest.py
│   │   │       ├── separate.py
│   │   │       ├── analyze.py
│   │   │       ├── arrange.py
│   │   │       ├── export.py
│   │   │       └── maintenance.py
│   │   ├── audio/
│   │   │   ├── probe.py             # ffprobe 검증
│   │   │   ├── decode.py            # ffmpeg → float32 WAV
│   │   │   └── normalize.py         # LUFS 정규화
│   │   ├── analysis/
│   │   │   ├── ir.py                # AnalysisIR (pydantic)
│   │   │   ├── registry.py          # AdapterRegistry, fallback 체인
│   │   │   ├── interfaces.py        # Protocol 정의
│   │   │   ├── adapters/
│   │   │   │   ├── separation_demucs.py
│   │   │   │   ├── separation_hpss.py
│   │   │   │   ├── separation_passthrough.py
│   │   │   │   ├── transcribe_basic_pitch.py
│   │   │   │   ├── transcribe_pyin.py
│   │   │   │   ├── beats_beat_this.py
│   │   │   │   ├── beats_madmom.py
│   │   │   │   ├── beats_librosa.py
│   │   │   │   ├── key_krumhansl.py
│   │   │   │   └── chords_hmm.py
│   │   │   └── merge.py             # 비트 양자화, 멜로디 선택
│   │   ├── arrangement/
│   │   │   ├── score_ir.py          # ScoreIR (pydantic)
│   │   │   ├── params.py            # 난이도 프리셋 + 사용자 파라미터
│   │   │   ├── engine.py            # 오케스트레이션
│   │   │   ├── melody.py            # 오른손 멜로디 추출·옥타브 보정
│   │   │   ├── voicing.py           # 왼손 보이싱 (근음·5도·전위)
│   │   │   ├── patterns.py          # 반주 패턴 (블록·알베르티·아르페지오)
│   │   │   ├── rhythm.py            # 양자화·단순화
│   │   │   ├── playability.py       # 손 뻗기·동시음 제약 검사
│   │   │   └── fingering.py         # 기본 운지 추정
│   │   └── export/
│   │       ├── midi.py
│   │       ├── musicxml.py
│   │       ├── engrave.py           # ScoreEngraver adapters
│   │       └── render_audio.py      # AudioRenderer adapters
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/                # 짧은 합성 오디오 (저작권 무관)
│       ├── unit/
│       └── integration/
├── infra/
│   ├── docker/
│   │   ├── web.Dockerfile           # Next.js standalone
│   │   └── backend.Dockerfile       # target api | worker (ffmpeg, fluidsynth, SF2, Demucs, Basic Pitch)
│   ├── docker-compose.yml           # caddy, web, api, worker-cpu, worker-ml, beat, postgres, redis, storage(RustFS)
│   ├── docker-compose.gpu.yml       # NVIDIA 런타임 오버레이
│   ├── caddy/Caddyfile
│   ├── scripts/init-env.sh          # infra/.env 생성 (무작위 비밀값)
│   └── .env.example
└── .github/
    └── workflows/
        ├── backend.yml              # ruff, mypy --strict, pytest
        └── web.yml                  # eslint, tsc, vitest
```

## 4. DB 스키마

```mermaid
erDiagram
    users ||--o{ refresh_tokens : has
    users ||--o{ audio_assets : uploads
    users ||--o{ projects : owns
    users ||--o{ usage_records : consumes
    audio_assets ||--o{ projects : "source of"
    audio_assets ||--o{ analyses : "analyzed by"
    projects ||--o{ jobs : runs
    projects ||--o{ arrangements : contains
    analyses ||--o{ stems : produces
    analyses ||--o{ arrangements : "input to"
    arrangements ||--o{ exports : renders
    jobs ||--o{ job_events : logs

    users {
        uuid id PK
        citext email UK
        text password_hash "argon2id"
        text display_name
        enum plan "free|pro"
        bool email_verified
        timestamptz created_at
        timestamptz deleted_at
    }
    refresh_tokens {
        uuid id PK
        uuid user_id FK
        bytea token_hash UK "sha256"
        uuid family_id "rotation 탐지"
        timestamptz expires_at
        timestamptz revoked_at
        inet ip
        text user_agent
    }
    audio_assets {
        uuid id PK
        uuid user_id FK
        text storage_key UK
        text original_filename "표시용만"
        text mime_type
        bigint size_bytes
        char64 sha256
        float duration_sec
        int sample_rate
        smallint channels
        enum status "pending|uploaded|valid|rejected|purged"
        text reject_reason
        timestamptz created_at
        timestamptz purge_after
    }
    projects {
        uuid id PK
        uuid user_id FK
        uuid audio_asset_id FK
        text title
        uuid current_analysis_id FK
        timestamptz created_at
        timestamptz updated_at
    }
    jobs {
        uuid id PK
        uuid project_id FK
        enum kind "full|rearrange|export"
        enum status "queued|running|succeeded|failed|canceled"
        text stage
        smallint progress "0-100"
        jsonb params
        text celery_root_id
        text error_code
        text error_message
        smallint attempt
        timestamptz created_at
        timestamptz started_at
        timestamptz finished_at
    }
    job_events {
        bigint id PK
        uuid job_id FK
        text stage
        smallint progress
        text level "info|warn|error"
        text message
        timestamptz created_at
    }
    analyses {
        uuid id PK
        uuid audio_asset_id FK
        text pipeline_version
        jsonb engine_versions
        float tempo_bpm
        text time_signature "4/4"
        smallint key_tonic "0-11"
        enum key_mode "major|minor"
        float key_confidence
        jsonb summary "섹션·코드 통계"
        text ir_key "S3 AnalysisIR.json.gz"
        timestamptz created_at
    }
    stems {
        uuid id PK
        uuid analysis_id FK
        enum kind "vocals|drums|bass|other|mix"
        text engine
        text storage_key
        float rms_db
    }
    arrangements {
        uuid id PK
        uuid project_id FK
        uuid analysis_id FK
        enum difficulty "beginner|intermediate|advanced"
        jsonb params
        char64 params_hash
        int revision
        enum status "pending|ready|failed"
        text score_ir_key "S3 ScoreIR.json.gz"
        jsonb stats "노트 수·음역·최대 동시음"
        timestamptz created_at
    }
    exports {
        uuid id PK
        uuid arrangement_id FK
        enum format "midi|musicxml|pdf|wav|mp3"
        text storage_key
        bigint size_bytes
        char64 sha256
        text engine
        timestamptz created_at
    }
    usage_records {
        bigint id PK
        uuid user_id FK
        enum kind "analysis_seconds|rearrange|export"
        numeric amount
        timestamptz created_at
    }
```

### 4.1 제약 조건 및 인덱스

- `audio_assets (user_id, sha256)` UNIQUE WHERE `status <> 'purged'` — 동일 파일 재업로드 시 분석 재사용.
- `analyses (audio_asset_id, pipeline_version)` UNIQUE — 파이프라인 버전이 같으면 캐시 히트.
- `arrangements (analysis_id, difficulty, params_hash)` UNIQUE — 같은 파라미터 재요청 시 기존 결과 반환.
- `exports (arrangement_id, format)` UNIQUE.
- `jobs (project_id, created_at DESC)`, `jobs (status) WHERE status IN ('queued','running')` 부분 인덱스.
- `job_events (job_id, id)` — WS 재접속 시 마지막 이벤트 이후만 재전송.
- 모든 사용자 소유 리소스 조회는 `user_id` 조건을 Repository 계층에서 강제 (IDOR 방지).

### 4.2 S3 키 규칙

```text
raw/{user_id}/{asset_id}                       # 원본 (purge_after 이후 삭제)
work/{asset_id}/normalized.wav
work/{asset_id}/{pipeline_version}/stems/{kind}.flac
work/{asset_id}/{pipeline_version}/analysis.json.gz
arr/{arrangement_id}/score.json.gz
arr/{arrangement_id}/export/{format}
```

## 5. API 개요

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/auth/signup` · `/login` · `/refresh` · `/logout` | httpOnly 쿠키 기반 JWT (access 15분, refresh 14일 rotation) |
| POST | `/api/v1/uploads` | presigned POST 발급 |
| POST | `/api/v1/projects` | 업로드 확정 + 전체 파이프라인 job 생성 |
| GET | `/api/v1/projects` · `/{id}` | 목록 · 상세 (분석 요약 포함) |
| GET | `/api/v1/jobs/{id}` | 상태 조회 (폴링 fallback) |
| POST | `/api/v1/jobs/{id}/cancel` | 취소 (Celery revoke) |
| POST | `/api/v1/projects/{id}/arrangements` | 파라미터 변경 재생성 (`rearrange` job) |
| GET | `/api/v1/arrangements/{id}` | ScoreIR + 통계 |
| GET | `/api/v1/arrangements/{id}/exports/{format}` | 302 → presigned GET |
| POST | `/api/v1/ws-ticket` | WS 인증용 1회성 티켓 (30초) |
| WS | `/ws/jobs/{id}?ticket=` | 진행률 스트림 |
| GET | `/healthz` · `/readyz` | DB·Redis·S3 연결 확인 |

## 6. 난이도 정의 (Phase 3 입력)

| 항목 | 초급 | 중급 | 고급 |
|---|---|---|---|
| 오른손 | 멜로디 단선율, 한 옥타브 이내 이동 | 멜로디 + 강박 3도/6도 보강 | 멜로디 + 화음 보강, 옥타브 더블링 |
| 왼손 | 마디당 근음 1~2개 / 5도 | 블록 코드 · 알베르티 · 간단한 아르페지오 | 스트라이드 · 넓은 아르페지오 · 베이스 라인 추종 |
| 리듬 최소 단위 | 4분음표 | 8분음표 | 16분음표 · 셋잇단 |
| 손당 최대 동시음 | 2 | 3 | 5 |
| 손 뻗기 한계 | 5도 | 옥타브 | 10도 |
| 조성 | C/G/F/Am/Dm로 이조 옵션 | 원조 유지 (옵션 이조) | 원조 유지 |
| 드럼 반영 | 템포·박만 사용 | 액센트 위치 반영 | 싱코페이션 패턴 반영 |

사용자 조절 파라미터: `difficulty`, `transpose`, `tempo_scale`, `melody_source(vocals|other|auto)`, `left_hand_pattern`, `quantize_grid`, `density(0–1)`, `range_low/high`, `include_intro_outro`.

## 7. 보안 설계 요약

- **업로드**: presigned POST에 `content-length-range`(최대 100MB) 및 키 고정. 워커에서 ffprobe로 컨테이너/코덱 화이트리스트(mp3, wav/aiff PCM, aac/alac/m4a, flac, ogg/opus/webm, wma) 및 최대 길이(무료 10분) 검증. 실패 시 `rejected` 후 즉시 삭제.
- **처리 격리**: ffmpeg·ML은 워커 컨테이너에서만 실행, 비루트, read-only rootfs + tmpfs, CPU/메모리 제한, 태스크별 `time_limit`.
- **인증**: argon2id, refresh token rotation + 재사용 탐지(family 폐기), CSRF는 SameSite=Lax + double-submit 토큰.
- **인가**: 모든 조회에 소유자 조건. 다운로드는 5분 TTL presigned URL만 발급.
- **남용 방지**: Redis 토큰 버킷 (IP·사용자), 사용자별 동시 job 수 제한, 월간 분석 초 쿼터.
- **데이터 보존**: 원본 오디오 기본 7일 후 purge (Celery Beat), 사용자 삭제 요청 시 S3 prefix 일괄 삭제.
- **헤더**: CSP, HSTS, X-Content-Type-Options, Referrer-Policy. CORS는 웹 오리진만 허용.

## 8. 주요 기술 결정

| 결정 | 선택 | 이유 |
|---|---|---|
| 작업 큐 | **Celery** (vs Dramatiq) | chain/group/chord로 병렬 분석 후 합류 표현이 직접적. 큐별 라우팅(cpu/ml), revoke, beat 스케줄 내장 |
| 악보 렌더 | **Verovio** | pip 설치 가능, 헤드리스, MusicXML → SVG 품질 양호. MuseScore는 선택적 fallback |
| 오디오 렌더 | **FluidSynth + FluidR3_GM SF2** (`PF_SOUNDFONT_PATH`로 교체 가능) | Debian 패키지로 설치, 라이선스 허용(MIT), 오프라인 렌더 안정 |
| 웹 악보 | **OpenSheetMusicDisplay** | MusicXML 직접 렌더, 커서 API로 재생 위치 동기화 |
| 웹 재생 | **서버 렌더링 MP3** (Phase 4에서 Tone.js 대신 채택) | 들리는 소리가 다운로드 파일과 같고 샘플 호스팅이 필요 없음. `<audio>` 하나가 피아노 롤·악보 커서의 공통 시계 |
| 비트 추적 | Beat This! 기본, librosa fallback | 벤치마크에서 박 F 0.87 → 0.98, 마디 첫 박 0.73 → 1.00. madmom은 최신 numpy와 호환되지 않아 선택 사항으로만 남김 |
| 로컬 오브젝트 스토리지 | **RustFS** (S3 호환, Apache-2.0) | MinIO 공식 이미지가 더 이상 공개 배포되지 않음. 버킷·CORS 설정은 `pianoforge.storage.bootstrap`이 S3 API로 수행해 서버 종류에 묶이지 않음 |
| Basic Pitch 설치 | `--no-deps` + ONNX 모델 | 패키지 메타데이터가 TensorFlow와 numpy<2를 요구함. ONNX 추론은 onnxruntime만 필요해 이미지가 약 1.5 GB 작고 numpy 2 유지 |
| 진입점 | **Caddy** 하나 (`:3000`) | 웹·API·WebSocket·스토리지가 같은 origin이라 쿠키 세션·CSRF가 교차 사이트 규칙 없이 동작하고, 공개할 포트가 하나뿐 (Codespaces 등 포트 포워딩 환경) |

## 9. 편곡 엔진 (Phase 3)

```mermaid
flowchart LR
    IR["AnalysisIR"] --> K["1. key<br/>이조 · 초급 쉬운 조"]
    K --> T["2. timeline<br/>비트 → 마디 정렬 tick<br/>격자 선택 (직선/셋잇단)"]
    T --> M["3. melody<br/>양자화 · 장식음 흡수<br/>레가토 · 음역 맞춤 · 도약 접기"]
    T --> H["4. harmony<br/>난이도별 화성 리듬"]
    H --> L["5. left hand<br/>root · block · alberti<br/>arpeggio · stride<br/>보이스 리딩 · 페달"]
    M --> X["6. texture<br/>멜로디 아래 화음음"]
    H --> X
    L --> P["7. playability<br/>음역 · 동시음 · 뻗기<br/>손 충돌"]
    X --> P
    P --> F["8. finish<br/>운지 DP · 셈여림 · 코드 심볼<br/>섹션 · 통계"]
    F --> S["ScoreIR"]
    S --> E1["MIDI (mido)"]
    S --> E2["MusicXML (music21)"]
    E2 --> E3["PDF (Verovio → cairosvg)"]
    S --> E4["WAV/MP3 (FluidSynth → numpy 합성)"]
```

- **ScoreIR 불변식:** 한 손 안에서 음이 겹치지 않는다 (chord stream). 덕분에 MusicXML은 보표당 1성부로 표기되고, 피아노 롤은 음을 그대로 그린다.
- **난이도 프로필** (`arrangement/profiles.py`): 격자, 손당 최대 동시음(2/3/5), 뻗기(5도/옥타브/10도), 음역, 화성 리듬, 오른손 보강 성부 수, 페달, 운지 표기 여부를 정의한다. 사용자 파라미터(`density`, `quantize_grid`, `range_*`)로 조절한다.
- **운지:** 선율선에 손가락 1–5 Viterbi를 적용한다 (Parncutt식 전이 비용). 화음을 잡을 손가락과 뻗기를 비용에 포함하고, 왼손은 음높이를 반전해 같은 모델을 쓴다.
- **내보내기 fallback:** PDF는 Verovio → MuseScore → (없으면 MusicXML만 제공) 순이다. 오디오는 FluidSynth + SoundFont → numpy 가산 합성 순이다.
- **동일 파라미터 캐시:** `(project, analysis, difficulty, params_hash)` UNIQUE (마이그레이션 0002).

## 10. 컨테이너 구성 (Phase 5)

```mermaid
flowchart LR
    B["브라우저"] -->|":3000"| C["caddy"]
    C -->|"/api, /ws, /healthz"| A["api<br/>uvicorn ×2"]
    C -->|"/버킷 (presigned URL)"| ST[("storage<br/>RustFS")]
    C -->|"그 외"| W["web<br/>Next.js standalone"]
    W -->|"rewrites (SSR)"| A
    A --> PG[("postgres")]
    A --> R[("redis")]
    A --> ST
    R --> WC["worker-cpu<br/>-Q cpu"]
    R --> WM["worker-ml<br/>-Q ml -c 1<br/>Demucs · Basic Pitch"]
    BT["beat"] --> R
    WC --> ST
    WM --> ST
    WC --> PG
    WM --> PG
    MI["migrate<br/>alembic upgrade head"] -.1회.-> PG
    SI["storage-init<br/>버킷 · CORS"] -.1회.-> ST
```

| 이미지 | 기반 | 크기(대략) | 내용 |
|---|---|---|---|
| `pianoforge/api` | python:3.12-slim | 1.4 GB | FastAPI, Alembic. 마이그레이션·스토리지 초기화 작업에도 사용 |
| `pianoforge/worker` | python:3.12-slim | 3.9 GB (ML 포함) | + ffmpeg, FluidSynth, FluidR3_GM, cairo, torch(CPU), Demucs `htdemucs` 가중치, Basic Pitch ONNX |
| `pianoforge/web` | node:22-bookworm-slim | 0.4 GB | Next.js standalone 서버 |

- 모든 애플리케이션 컨테이너는 비루트 사용자로 실행된다. api와 워커는 읽기 전용 루트 파일시스템에 `/tmp` tmpfs만 쓴다.
- 기동 순서는 healthcheck와 `service_completed_successfully`로 강제한다: postgres·redis·storage → migrate·storage-init → api·워커 → web → caddy.
- GPU 오버레이(`docker-compose.gpu.yml`)는 워커를 CUDA torch로 빌드하고 `PF_DEMUCS_DEVICE=cuda`로 worker-ml에 GPU 1장을 할당한다.
- **네트워크 자동 선택:** `make up`은 시작 전에 새 bridge 네트워크에서 컨테이너 두 개가 서로 통신되는지 확인한다(`infra/scripts/netcheck.sh`). 통신이 막힌 환경(일부 GitHub Codespaces)이면 `infra/.host-network` 표시 파일을 만들고 `docker-compose.host.yml`을 겹쳐 모든 컨테이너를 호스트 네트워크로 실행한다. 서비스 이름은 `extra_hosts`로 127.0.0.1에 매핑해 설정 변경이 필요 없다.

## 11. 정확도 개선 (박자·빠진 음·원곡 재현)

측정은 `backend/bench/`의 벤치마크로 한다: 정답이 있는 합성곡 10개(템포 흔들림, 템포 변화, 3/4, 스윙, 16분음표, 드럼 없는 발라드, 전주·못갖춘마디, 보컬 없는 곡)와 실제 노래 12곡(vocadito, CC BY 4.0, 합성 반주와 혼합).

| 지표 | 이전 | 이후 |
|---|---|---|
| 박 위치 F-measure | 0.87 | 0.98 |
| 마디 첫 박 F-measure | 0.73 | 1.00 |
| 코드 일치율 | 0.95 | 0.995 |
| 멜로디 채보 F1, 실제 노래 | 0.28 | 0.48 |
| 원곡 멜로디 음 보존율 (초급 / 중급 / 고급) | 0.61 / 0.68 / 0.70 | 0.81 / 0.82 / 0.77 |
| 편곡 멜로디 정밀도 (고급) | 0.54 | 0.64 |
| 음 시작 오차 중앙값 | 31 ms | 7 ms |
| 피아노 음원의 원곡 대비 어긋남 (p90) | 평균 69 ms, 템포 변화 곡 최대 수 초 | 0 ms |

변경 내용:

- **박자:** Beat This! 트랜스포머 추적기를 1순위로 추가했다. 20 ms 프레임을 포물선 보간으로 세분하고, 빠진 박을 채우고 중복 박을 지운다. 박자표와 마디 첫 박은 3박/4박 각각의 마디 위치 Viterbi 경로 중 우도가 높은 쪽으로 정한다(네트워크의 첫 박 확률 + 저음 어택·화성 변화 단서). librosa fallback은 시변 템포(6초 중앙값 평활, 2배·절반 박 오류 보정)로 템포 변화를 따라간다(ML 없는 이미지 기준 박 F 0.87 → 0.93, 마디 첫 박 0.73 → 0.85).
- **원곡 타이밍 재현:** 악보는 일정한 박으로 쓰되, 연주(MP3/WAV/MIDI, 웹 피아노 롤·악보 커서)는 원곡의 박 시각(`performance_beats`)을 따른다. `timing=steady`로 연습용 일정 템포를 고를 수 있다.
- **스윙:** 뒷박 8분음표 위치 분포로 스윙 비율을 찾아, 악보에는 스트레이트 8분음표 + "Swing"으로 쓰고 연주에는 원곡 비율을 적용한다.
- **멜로디 정리:** 낮은 목소리가 한 옥타브 올라가던 음역 제한을 E2까지 넓혔다. 윗성부 선택 뒤 옥타브 오류를 선율 흐름 기준 Viterbi로 바로잡는다. 어택 없이 이어지는 같은 음(비브라토로 쪼개진 음)과 짧은 글라이드 음은 앞 음에 합친다. 어택 세기는 원 음원의 onset 강도를 3초 구간 90 백분위로 정규화한 값이다.
- **빠진 음:** 여러 음이 한 격자 칸에 모이면 음량보다 칸에 가까운 음을 우선한다. 정박 음이 옆 엇박의 큰 음에 밀려 사라지던 문제다.
- **입력 형식:** MP3, WAV, M4A/AAC 외에 FLAC, OGG(Vorbis/Opus), WebM(오디오), AIFF, WMA를 받는다. 업로드 한도는 100 MB.

한계: 실제 노래의 음 단위 채보는 Basic Pitch 모델 자체가 상한이다(깨끗한 보컬에서도 F1 약 0.5). 설정 조정으로는 정밀도와 빠진 음 사이의 교환만 일어나서, 빠진 음이 적은 쪽을 택했다.

