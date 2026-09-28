# PianoForge

MP3 / WAV / M4A 음원을 분석해 난이도별(초급·중급·고급) 피아노 편곡을 생성하고
MIDI, MusicXML, PDF 악보, 피아노 렌더링 오디오(WAV/MP3)로 제공하는 웹 서비스.

## 진행 상태

| Phase | 내용 | 상태 |
|---|---|---|
| 1 | 아키텍처 · 디렉토리 구조 · DB 스키마 | 완료 |
| 2 | FastAPI · Celery · 오디오 전처리 · 분석 Adapter | 완료 (검토 대기) |
| 3 | 난이도별 피아노 편곡 엔진 | 대기 |
| 4 | Next.js UI (업로드, 실시간 상태, 피아노 롤, 악보 뷰어) | 대기 |
| 5 | Docker / docker-compose · 로컬 실행 가이드 | 대기 |

- 설계: [docs/architecture.md](docs/architecture.md)
- API 계약: [docs/api.md](docs/api.md)
- 백엔드 실행 및 테스트: [backend/README.md](backend/README.md)
