# PianoForge

MP3 / WAV / M4A 음원을 분석해 난이도별(초급·중급·고급) 피아노 편곡을 생성하고
MIDI, MusicXML, PDF 악보, 피아노 렌더링 오디오(WAV/MP3)로 제공하는 웹 서비스.

## 진행 상태

| Phase | 내용 | 상태 |
|---|---|---|
| 1 | 아키텍처 · 디렉토리 구조 · DB 스키마 | 완료 |
| 2 | FastAPI · Celery · 오디오 전처리 · 분석 Adapter | 완료 |
| 3 | 난이도별 피아노 편곡 엔진 · MIDI/MusicXML/PDF/오디오 내보내기 | 완료 |
| 4 | Next.js UI (업로드, 실시간 상태, 피아노 롤, 악보 뷰어) | 완료 |
| 5 | Docker / docker-compose · 로컬 실행 가이드 | 완료 |

## 빠른 시작

```bash
make up            # infra/.env 생성 → 이미지 빌드 → 전체 스택 기동
open http://localhost:3000
```

Docker 24+와 Compose v2가 필요하다. 첫 빌드는 ML 모델 포함 약 4 GB를 내려받는다.
자세한 내용은 [docs/local-run.md](docs/local-run.md).

## 문서

- 로컬 실행: [docs/local-run.md](docs/local-run.md)
- 은하계 테마(배경·유리·네온·스크롤·클릭 효과): [docs/galaxy-theme.md](docs/galaxy-theme.md)
- 설계: [docs/architecture.md](docs/architecture.md)
- API 계약: [docs/api.md](docs/api.md)
- 백엔드 실행 및 테스트: [backend/README.md](backend/README.md)
- 웹 실행 및 테스트: [apps/web/README.md](apps/web/README.md)
