# 로컬 실행 가이드

`docker compose` 한 번으로 PianoForge 전체 서비스(웹, API, 워커, DB, 큐, 스토리지)를 띄운다.

## 1. 요구 사항

| 항목 | 최소 | 비고 |
|---|---|---|
| Docker Engine | 24+ | Docker Desktop(macOS·Windows) 가능 |
| Docker Compose | v2.20+ | `docker compose version` |
| 메모리 | 8 GB (Docker에 할당) | Demucs가 곡 전체를 메모리에 올린다. 4분 곡 기준 워커 최대 약 3 GB |
| 디스크 | 12 GB | 이미지 약 6 GB + 빌드 캐시 |
| 포트 | 3000, 9000 | `infra/.env`의 `APP_PORT`, `STORAGE_PORT`로 변경 |
| GPU (선택) | NVIDIA + Container Toolkit | 음원 분리가 수 분 → 수 초 |

## 2. 실행

```bash
git clone <repo> && cd Both
make up
```

`make up`은 다음을 순서대로 수행한다.

1. `infra/.env`가 없으면 `infra/.env.example`을 복사하고 비밀번호·JWT 비밀값을 무작위로 채운다. 이미 있으면 건드리지 않는다.
2. 이미지 3개(`pianoforge/api`, `pianoforge/worker`, `pianoforge/web`)를 빌드한다. 첫 빌드는 PyTorch·Demucs 가중치를 포함해 약 4 GB를 받는다(회선에 따라 10–20분).
3. 스택을 백그라운드로 올린다.

기동이 끝나면 http://localhost:3000 을 연다. 회원가입 후 오디오를 올리면 된다.

`make`가 없으면 같은 일을 직접 실행한다.

```bash
sh infra/scripts/init-env.sh
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --build
```

### GPU 사용

```bash
make up-gpu
```

워커를 CUDA 12.6용 PyTorch로 빌드하고 `worker-ml`에 GPU 1장을 할당한다(`PF_DEMUCS_DEVICE=cuda`).

### ML 엔진 없이 (가벼운 이미지)

`infra/.env`에서 `WITH_ML=false`로 바꾸고 `make up`. 워커 이미지가 약 1.5 GB로 줄고, 분석은 DSP fallback(HPSS 분리, pYIN 전사)으로 동작한다. 결과 화면에 강등된 엔진이 경고로 표시된다.

## 3. 기동 순서와 상태 확인

```bash
make ps       # 서비스 상태 (healthy / exited 0 확인)
make logs     # 전체 로그 follow
docker compose -f infra/docker-compose.yml --env-file infra/.env logs -f worker-ml
```

| 서비스 | 역할 | 정상 상태 |
|---|---|---|
| `postgres`, `redis`, `storage` | 데이터 계층 | healthy |
| `migrate` | `alembic upgrade head` | exited (0) |
| `storage-init` | 버킷 생성, CORS 설정 | exited (0) |
| `api` | FastAPI (`/healthz`, `/readyz`) | healthy |
| `worker-cpu` | 전처리, 박자·조성 분석, 편곡, 내보내기 | running |
| `worker-ml` | Demucs 분리, Basic Pitch 전사 (동시 1건) | running |
| `beat` | 보존기한 정리, 멈춘 작업 회수 | running |
| `web` | Next.js | healthy |
| `caddy` | 브라우저 진입점 `:3000` | running |

준비 상태 확인:

```bash
curl -s http://localhost:3000/readyz
# {"status":"ok","checks":{"database":"ok","redis":"ok","storage":"ok"}}
```

## 4. 포트와 접속 경로

| 주소 | 대상 |
|---|---|
| http://localhost:3000 | 웹 UI (Caddy → web) |
| http://localhost:3000/api/v1/* | REST API (Caddy → api) |
| ws://localhost:3000/ws/jobs/{id} | 작업 진행 WebSocket |
| http://localhost:9000 | 오브젝트 스토리지. 브라우저가 presigned URL로 직접 업로드·다운로드 |

다른 기기(같은 LAN의 휴대폰 등)에서 접속하려면 `infra/.env`의 주소를 호스트 IP로 바꾼다.

```dotenv
WEB_ORIGIN=http://192.168.0.10:3000
STORAGE_PUBLIC_URL=http://192.168.0.10:9000
```

presigned URL의 서명에 호스트가 포함되므로 `STORAGE_PUBLIC_URL`은 브라우저가 실제로 접속하는 주소와 같아야 한다. 바꾼 뒤 `make up`으로 다시 올린다(`storage-init`이 CORS를 새 origin으로 갱신).

## 5. 설정 (`infra/.env`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_PORT` | 3000 | 웹 진입 포트 |
| `WEB_ORIGIN` | http://localhost:3000 | CORS·스토리지 CORS 허용 origin |
| `STORAGE_PORT` | 9000 | 스토리지 호스트 포트 |
| `STORAGE_PUBLIC_URL` | http://localhost:9000 | presigned URL 서명 대상 주소 |
| `STORAGE_ACCESS_KEY` / `STORAGE_SECRET_KEY` | 무작위 | 스토리지 자격 증명 |
| `S3_BUCKET` | pianoforge | 버킷 이름 |
| `POSTGRES_*` | 무작위 비밀번호 | DB 자격 증명 |
| `PF_JWT_SECRET` | 무작위 | 액세스 토큰 서명 키 |
| `WITH_ML` | true | 워커 이미지에 Demucs·Basic Pitch 포함 |
| `CPU_CONCURRENCY` | 2 | cpu 워커 동시 작업 수 |

그 밖의 백엔드 설정(`PF_*`, 엔진 체인, 업로드 한도 등)은 [backend/README.md](../backend/README.md)의 표를 보고 `infra/docker-compose.yml`의 `x-backend-env`에 추가한다.

## 6. 자주 쓰는 명령

| 명령 | 동작 |
|---|---|
| `make up` | 빌드 후 기동 (변경된 이미지만 다시 빌드) |
| `make down` | 중지 (데이터 유지) |
| `make clean` | 중지 + DB·스토리지·Redis 볼륨 삭제 |
| `make migrate` | 마이그레이션만 실행 |
| `make test` | 백엔드·웹 단위 테스트 (스택 불필요) |
| `make e2e` | 실행 중인 스택에 Playwright 전체 흐름 테스트 |

`make e2e`는 `apps/web`에서 `npm ci`와 `npx playwright install chromium`이 먼저 되어 있어야 한다.

## 7. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| 업로드가 CORS 오류로 실패 | 접속 주소와 `WEB_ORIGIN`이 다름 | `WEB_ORIGIN` 수정 후 `make up` |
| 업로드 403 `SignatureDoesNotMatch` | `STORAGE_PUBLIC_URL`이 브라우저 접속 주소와 다름 | 같은 호스트·포트로 수정 |
| `worker-ml`이 `OOMKilled` | Docker 메모리 부족 | Docker 메모리를 8 GB 이상으로 늘림 |
| 분석이 "음원 분리 강등" 경고 | `WITH_ML=false` 이미지 또는 Demucs 실패 | `make logs`에서 `worker-ml` 오류 확인 |
| 포트 충돌 | 3000·9000 사용 중 | `APP_PORT`, `STORAGE_PORT`, 그리고 두 URL 변수를 함께 변경 |
| 사내 프록시에서 빌드 TLS 오류 | 가로채기 프록시 CA | `docker build --secret id=extra_ca,src=ca.crt` (Dockerfile 주석 참고) |

## 8. 운영 환경과의 차이

로컬 스택은 개발·검증용이다. 운영에서는 다음을 바꾼다.

- `PF_ENV=prod`, `PF_COOKIE_SECURE=true`, HTTPS 종단(Caddy 자동 TLS 또는 로드밸런서).
- 관리형 PostgreSQL·Redis·S3 사용. `storage` 서비스를 빼고 `PF_S3_*`를 실제 엔드포인트로 지정.
- `worker-ml`을 GPU 노드로 분리하고 `worker-cpu`는 수평 확장.
