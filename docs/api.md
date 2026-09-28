# PianoForge API 계약 (v1)

- Base URL: `/api/v1` (WebSocket만 루트 `/ws`)
- 형식: JSON (UTF-8). 오디오 파일은 API를 거치지 않고 S3에 직접 업로드한다.
- 인증: httpOnly 쿠키 세션(웹) 또는 `Authorization: Bearer <access_token>`(비브라우저 클라이언트)
- 개발 환경에서 OpenAPI: `GET /openapi.json`, Swagger UI: `/docs` (prod에서는 비활성)

## 1. 공통 규칙

### 오류 응답

모든 오류는 같은 envelope을 사용한다.

```json
{ "error": { "code": "upload_incomplete", "message": "업로드가 아직 완료되지 않았습니다.", "request_id": "3f0c…" } }
```

| HTTP | code 예시 | 의미 |
|---|---|---|
| 401 | `unauthorized`, `token_expired`, `token_reuse`, `invalid_credentials` | 인증 필요 또는 실패 |
| 403 | `csrf_failed` | 쿠키 세션의 변경 요청에 CSRF 헤더 누락 또는 불일치 |
| 404 | `not_found`, `analysis_not_ready` | 없음 (타인 리소스도 404) |
| 409 | `email_taken`, `upload_incomplete`, `upload_consumed`, `job_finished` | 상태 충돌 |
| 413 | `payload_too_large` | 크기 제한 초과 |
| 415 | `unsupported_media_type` | 허용되지 않은 MIME |
| 422 | `validation_error` (+ `details[]`) | 요청 값 검증 실패 |
| 429 | `rate_limited`, `too_many_active_jobs` | 요청 한도 초과 (`Retry-After` 헤더 포함) |
| 503 | `service_unavailable` | 작업 대기열 연결 불가 |

### 인증과 CSRF

- 로그인·가입·갱신 응답은 쿠키 3개를 설정한다.
  - `pf_access`: httpOnly, 15분
  - `pf_refresh`: httpOnly, path `/api/v1/auth`, 14일, 사용 시 교체(rotation)
  - `pf_csrf`: JS에서 읽을 수 있는 CSRF 토큰
- 쿠키 세션으로 `POST/PATCH/DELETE`를 보낼 때는 `X-CSRF-Token: <pf_csrf 값>` 헤더가 필수다.
- Bearer 토큰으로 요청할 때는 CSRF 검사를 하지 않는다.
- 이미 교체된 refresh 토큰이 다시 제출되면, 같은 계열(family)의 토큰을 모두 폐기하고 `401 token_reuse`를 반환한다.

### Rate limit

| 범위 | 기준 | 기본값 |
|---|---|---|
| `auth/*` | IP | 10회/분 |
| 업로드·프로젝트 생성·WS 티켓 | 사용자 | 60회/분 |
| 동시 활성 작업 | 사용자 | free 2개 / pro 5개 |
| 월간 분석 시간 | 사용자(free) | 60분 |

## 2. 인증

| Method | Path | Body | 응답 |
|---|---|---|---|
| POST | `/auth/signup` | `{email, password(10–128, 문자 종류 2가지 이상), display_name}` | 201 `SessionOut` |
| POST | `/auth/login` | `{email, password}` | 200 `SessionOut` |
| POST | `/auth/refresh` | (쿠키) | 200 `SessionOut` |
| POST | `/auth/logout` | — | 204 |
| GET | `/auth/me` | — | 200 `UserOut` |
| DELETE | `/auth/me` | `{password}` | 204. 계정을 즉시 삭제하고, 스토리지 객체는 비동기로 삭제한다 |

```ts
type SessionOut = { user: UserOut; csrf_token: string; access_expires_in: number; access_token: string; token_type: "bearer" };
type UserOut = { id: string; email: string; display_name: string; plan: "free" | "pro"; email_verified: boolean; created_at: string };
```

## 3. 업로드 → 프로젝트 생성

```text
1. POST /uploads            → { upload_id, url, fields, expires_in, max_bytes }
2. POST {url} (multipart)   → fields + file 필드 그대로 S3에 전송 (204)
3. POST /projects           → 202 { project, job } 후 파이프라인 시작
4. POST /ws-ticket          → { ticket } 발급 후 WS /ws/jobs/{job_id}?ticket=… 로 진행률 수신
```

### `POST /uploads`

```json
{ "filename": "song.mp3", "size_bytes": 4813210, "mime_type": "audio/mpeg" }
```

- 확장자: `.mp3 .wav .m4a .aac .mp4`
- MIME: `audio/mpeg`, `audio/wav`, `audio/mp4`, `audio/x-m4a`, `audio/aac` 등
- 최대 50MB. presigned POST 정책의 `content-length-range`로 S3에서도 강제한다.
- 서버 측 객체 키는 `raw/{user_id}/{upload_id}`이며, 원본 파일명은 표시용으로만 저장한다.

### `POST /projects`

```json
{
  "upload_id": "…",
  "title": "선택. 기본값은 파일명",
  "params": {
    "difficulty": "beginner | intermediate | advanced",
    "transpose": 0,
    "simplify_key": false,
    "tempo_scale": 1.0,
    "melody_source": "auto | vocals | other",
    "left_hand_pattern": "auto | root | block | alberti | arpeggio | stride",
    "quantize_grid": "auto | 1/4 | 1/8 | 1/16 | 1/8t",
    "density": 0.5,
    "range_low": 36,
    "range_high": 96,
    "include_intro_outro": true
  }
}
```

- 모든 `params` 필드는 선택이며, 생략 시 위 기본값을 쓴다.
- `range_high - range_low`는 24 이상이어야 한다.
- 오류:
  - `409 upload_incomplete`: 객체가 S3에 없음
  - `409 upload_consumed`: 이미 사용된 업로드
  - `429 too_many_active_jobs`: 동시 작업 한도 초과

### 프로젝트 조회

| Method | Path | 설명 |
|---|---|---|
| GET | `/projects?limit=20&cursor=` | 최신순, 커서 기반 페이지 (`next_cursor`) |
| GET | `/projects/{id}` | `asset`, `analysis`(요약), `latest_job` 포함 |
| GET | `/projects/{id}/analysis` | 전체 `AnalysisIR` (`{analysis_id, ir}`) |
| PATCH | `/projects/{id}` | `{title}` |
| DELETE | `/projects/{id}` | 활성 작업 취소 후 삭제, 참조가 없으면 스토리지 정리 |

## 4. 작업

| Method | Path | 설명 |
|---|---|---|
| GET | `/jobs/{id}` | `JobOut` (WebSocket을 쓸 수 없을 때의 폴링 경로) |
| GET | `/jobs/{id}/events?after_id=0&limit=200` | 단계별 이벤트 로그 |
| POST | `/jobs/{id}/cancel` | 대기·실행 중인 작업 취소. 실행 중 태스크는 다음 진행률 보고 시점에 중단된다 |

```ts
type JobOut = {
  id: string; project_id: string; kind: "full" | "rearrange" | "export";
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  stage: "queued" | "ingest" | "separate" | "rhythm" | "tonal" | "transcribe" | "merge" | "arrange" | "export" | "done";
  progress: number; // 0–100, 단조 증가
  params: object; error_code: string | null; error_message: string | null;
  created_at: string; started_at: string | null; finished_at: string | null;
};
```

### 단계별 진행률 구간

| stage | 구간 | 큐 |
|---|---|---|
| ingest | 0–8 | cpu |
| separate | 8–45 | ml |
| rhythm | 45–52 | cpu |
| tonal | 52–62 | cpu (transcribe와 병렬) |
| transcribe | 52–80 | ml (tonal과 병렬) |
| merge | 80–85 | cpu |
| arrange | 85–92 | cpu (Phase 3) |
| export | 92–99 | cpu (Phase 3) |

### 사용자에게 노출되는 실패 코드 (`error_code`)

| code | 원인 |
|---|---|
| `unreadable` | ffprobe가 읽지 못함 (손상되었거나 오디오가 아님) |
| `unsupported_container`, `unsupported_codec` | 허용 목록 밖 |
| `no_audio`, `has_video` | 오디오 스트림이 없거나 영상이 포함됨 |
| `too_short`, `too_long` | 1초 미만, 또는 플랜 한도 초과 (free 10분 / pro 20분) |
| `quota_exceeded` | 월간 분석 시간 초과 |
| `not_uploaded`, `too_large` | 스토리지 상태 불일치 |
| `timeout` | 태스크 시간 제한 초과, 또는 워커 무응답으로 회수됨 |
| `engine_unavailable` | 모든 대체 엔진이 실패 |
| `infrastructure` | DB/S3/Redis 일시 오류 (재시도 3회 후) |
| `internal_error` | 그 외 |

## 5. WebSocket

```text
POST /api/v1/ws-ticket {job_id}  → { ticket, expires_in: 30, url: "/ws/jobs/{job_id}" }
WS   /ws/jobs/{job_id}?ticket=…&last_event_id=0
```

- 티켓은 1회용이며 30초 동안 유효하다. 브라우저는 WebSocket 요청에 헤더를 붙일 수 없어서 티켓으로 인증한다.
- `Origin` 헤더가 CORS 허용 목록에 없으면 1008로 종료한다.
- 재접속 시에는 새 티켓과 `last_event_id`를 전달해, 누락된 이벤트만 받는다.

서버 → 클라이언트 메시지:

```ts
type Msg =
  | { type: "snapshot"; job: JobOut; events: JobEventOut[] }          // 접속 직후 1회
  | { type: "progress"; job_id: string; stage: string; progress: number; status: "running" }
  | { type: "event"; job_id: string; id: number; stage: string; progress: number;
      level: "info" | "warn" | "error"; message: string; created_at: string }
  | { type: "status"; job_id: string; status: "succeeded" | "failed" | "canceled";
      stage: string; progress: number; error_code?: string; error_message?: string; analysis_id?: string }
  | { type: "ping" };                                                  // 20초 무통신 시
```

- 종료 상태의 `status` 메시지를 보낸 뒤 서버가 1000으로 연결을 닫는다.
- 접속 시점에 이미 종료된 작업이면 `snapshot`만 보내고 닫는다.

## 6. AnalysisIR (요약)

```ts
type AnalysisIR = {
  schema_version: 1; pipeline_version: string; duration: number; sample_rate: number;
  engines: Record<string, string>;            // "separator": "demucs@4" 등
  tempo: { bpm: number; confidence: number; curve: [number, number][] };
  time_signature: { numerator: number; denominator: 4 };
  beats: number[]; downbeats: number[];        // 초
  key: { tonic: 0-11; mode: "major" | "minor"; confidence: number; candidates: Record<string, number> };
  chords: { start: number; end: number; root: 0-11 | null; quality: "maj"|"min"|"dim"|"aug"|"sus4"|"7"|"maj7"|"min7"|"N";
            bass: 0-11 | null; confidence: number; start_beat: number; end_beat: number }[];
  sections: { start: number; end: number; label: "A" | "B" | … }[];
  tracks: Record<"melody" | "bass" | "harmony", {
    role: string; source: string; engine: string;
    notes: { start: number; end: number; pitch: number; velocity: number; confidence: number;
             start_beat: number; end_beat: number }[] }>;
  stems: { kind: string; engine: string; rms_db: number; storage_key: string }[];
  warnings: string[];                          // 품질 강등 사유 (UI 배지)
};
```

## 7. 헬스 체크

| Path | 설명 |
|---|---|
| `GET /healthz` | 프로세스 생존 여부 |
| `GET /readyz` | DB, Redis, S3 연결 확인. 하나라도 실패하면 503 |
