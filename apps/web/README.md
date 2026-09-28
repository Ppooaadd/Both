# PianoForge Web

Next.js 16 (App Router, TypeScript strict) · React 19 · Tailwind CSS 4 · shadcn/ui (Radix) · TanStack Query 5 · zod 4.

## 실행

```bash
npm install
# 백엔드(API :8000, 워커, 스토리지)가 떠 있어야 한다. backend/README.md 참고.
BACKEND_ORIGIN=http://localhost:8000 NEXT_PUBLIC_WS_ORIGIN=ws://localhost:8000 npm run dev
```

| 변수 | 시점 | 설명 |
|---|---|---|
| `BACKEND_ORIGIN` | 빌드 | `/api/v1/*`, `/healthz`를 백엔드로 rewrite한다. 기본값 `http://localhost:8000`. 운영에서는 리버스 프록시가 `/api`를 직접 라우팅한다 |
| `NEXT_PUBLIC_WS_ORIGIN` | 빌드 | WebSocket 주소. 비워 두면 현재 페이지와 같은 출처(`wss://host`)를 쓴다 |

- API는 같은 출처(rewrite)로 호출하므로 세션 쿠키와 CSRF 쿠키가 그대로 동작한다.
- WebSocket은 rewrite로 프록시되지 않으므로, 1회용 티켓으로 인증해 백엔드에 직접 연결한다.
- 업로드와 악보(MusicXML) 로드는 브라우저가 스토리지와 직접 통신한다. 스토리지에 웹 출처를 허용하는 CORS 설정이 필요하다 (MinIO는 기본 허용).

## 구조

```text
src/
├── app/                 # 라우트: / (업로드), /login, /signup, /projects, /projects/[id]
├── components/
│   ├── ui/              # shadcn/ui 컴포넌트
│   ├── upload/          # 드래그 앤 드롭, 검증, presigned 업로드 진행률
│   ├── job/             # 실시간 진행 (WebSocket → 폴링 fallback), 단계 타임라인
│   ├── pianoroll/       # Canvas 피아노 롤: geometry(순수 함수) · draw · 컴포넌트
│   ├── score/           # OpenSheetMusicDisplay 악보 + 재생 커서
│   ├── player/          # 렌더링된 MP3를 공유 시계로 사용하는 재생기
│   ├── arrange/         # 파라미터 패널, 편곡 버전 선택
│   ├── analysis/ export/ project/ auth/ layout/
└── lib/
    ├── api/             # fetch 래퍼(CSRF, refresh 재시도), zod 스키마, Query 훅, 업로드
    ├── ws/              # JobSocket(재접속·중복 제거·폴링 전환), useJobStream
    └── music.ts         # 음이름, 코드명, 라벨, 경고 한국어화
```

### 재생 방식

브라우저 신디사이저(Tone.js) 대신, 서버가 렌더링한 피아노 MP3를 재생한다. 들리는 소리가 다운로드 파일과 같고, 브라우저용 샘플을 따로 호스팅하지 않아도 된다. 이 `<audio>` 요소 하나가 피아노 롤 재생 헤드와 악보 커서의 공통 시계 역할을 한다. 재생 중에는 requestAnimationFrame 루프에서 캔버스만 다시 그리므로 React 리렌더가 일어나지 않는다.

## 검사

```bash
npm run typecheck   # next typegen + tsc --noEmit (strict)
npm run lint        # eslint (next core-web-vitals + typescript, React Compiler 규칙)
npm test            # vitest: API 클라이언트, WebSocket, 피아노 롤 기하, 컴포넌트
npm run build

# 풀스택 E2E: 스택이 떠 있는 상태에서 실행
E2E_BASE_URL=http://localhost:3000 npm run test:e2e
```
