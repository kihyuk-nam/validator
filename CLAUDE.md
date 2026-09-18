# CLAUDE.md — validator 저장소 작업 규칙 (Claude Code 가 세션 시작 시 자동으로 읽는 파일)

## 이 저장소가 무엇인가
자연어 요구사항의 일관성(무모순성)·실현 가능성 검사 도구. `server/` = formalizer(LLM, 자연어→명세, 틀릴 수 있는 곳) + checker(z3, 명세→판정, 틀리지 않는 곳). `client/` = 원문을 들고 서버를 부르고 확인 단계와 원문 인용 리포트를 담당. 구조·API 는 `README.md`, `server/README.md`. 설계 문서(설계-01, LTL·왕복 검증 계획)는 claude.ai 프로젝트 "validator" 의 `claude/validator-design.md` 에 있고 저장소에는 없다.

## 두 작업자
- **Claude Code(이 환경)** — 코드·테스트·배포의 주체. 저장소에 push 하는 유일한 쪽.
- **Cowork 세션(claude.ai 프로젝트 "validator")** — 설계·문서·구조도·노트북·분석. 코드 변경이 필요하면 파일(zip/patch)과 적용 프롬프트를 사용자에게 주고, 사용자가 이 환경에 넘긴다. Cowork 는 이 저장소를 읽기 전용으로 본다(push 는 못 한다). 보는 경로는 두 가지다.
  - **프로젝트 지식 가져오기** — 프로젝트 컨텍스트 패널의 `+` → GitHub 에서 파일을 골라 프로젝트 공간으로 **복사**한다. 가져온 시점의 스냅샷이라 저장소가 바뀌면 낡는다. 별도의 "Sync" 버튼은 확인되지 않았다(2026-09-18) — 갱신은 다시 가져오고 이전 복사본을 지우는 방식이다.
  - **MCP 파일시스템 커넥터** — 데스크탑 앱의 `claude_desktop_config.json` 에 `filesystem` 서버를 등록해 두었다(허용 폴더 `C:\Users\11-2021-4\Downloads\claude-validator-00-임시`). 채팅이 디스크의 파일을 직접 읽으므로 항상 최신이고 가져오기가 필요 없다. 두 가지 주의: 읽기 전용이 아니어서 `write_file`·`edit_file`·`move_file` 도 노출된다(채팅이 로컬 파일을 고칠 수 있다 — push 는 여전히 Claude Code 만). 그리고 서버는 `@modelcontextprotocol/server-filesystem@2025.8.21` 로 고정한다. 그 이후 버전은 도구 스키마를 JSON Schema draft-07 로 선언해 클라이언트가 거부한다.

## 불변 규칙
1. `server/checker.py` 의 판정 로직을 바꾸면 `server/examples/expected_findings.json` 회귀가 그대로 통과해야 한다(구현-00 결과: R3·R5 조건부 모순, R6 공허, R5 중복). 바꿔야 한다면 이유를 STATUS.md 에 적는다.
2. 외부 API 는 `POST /validate` 하나(`/audit` 별칭 유지). 응답 형식을 바꾸면 `server/README.md` 와 `client/` 를 같은 커밋에서 맞춘다.
3. formalizer 의 canned 번역은 입력 해시로만 조회된다. 예제 원문(`client/example_battery.py` 의 DOMAIN_TEXT·REQUIREMENTS, `server/examples/battery_input.json`)을 고치면 `server/formalizer/canned/battery.smt.json` 의 `input_sha` 를 다시 만든다(`python -m formalizer.canned add …`).
4. 커밋 전에 `cd server && python tests/test_api.py http://localhost:8000` PASS.
5. API 키·토큰은 커밋하지 않는다. `ANTHROPIC_API_KEY` 는 환경변수/Render 대시보드에서만.

## 세션을 마칠 때 (한 세트)
1. `STATUS.md` 맨 위에 항목을 추가한다 — 날짜, 바꾼 파일, 판정 결과 변화 유무, 배포 URL, 다음 할 일, 결정하지 못한 것. Cowork 는 이 파일을 제일 먼저 읽으므로 짧고 정확하게.
2. 테스트 PASS 확인 후 commit · push.
3. Cowork 가 낡은 코드를 보지 않도록 마지막 줄에서 사용자에게 갱신을 알린다. MCP 커넥터 경로면 따로 할 일이 없다(디스크를 직접 읽는다). 프로젝트 지식 경로면 "프로젝트 validator 의 컨텍스트에서 바뀐 파일을 GitHub 에서 다시 가져오고 이전 복사본을 지워 달라"고 알린다 — 가져오기는 스냅샷이므로 push 만으로는 갱신되지 않는다.

프로젝트 지식으로 가져올 때 빼는 것(MCP 커넥터 경로에는 해당 없음): `validator_prototype.ipynb`, `docs/*.png`, `server/logs/`, `client/out/` — 프로젝트 지식 한도(2 MB)를 잡아먹고 Cowork 가 코드 판단에 쓰지 않는다. 새로 큰 파일(이미지·데이터·로그)을 추가하면 이 목록에도 적는다.

## 현재 상태 (2026-09-18 기준, 구현 01 첫 단계)
- 완료: 저장소 통합·개명(validator = client + server{formalizer, checker}), `/validate` 2모드, canned·anthropic provider, 확인 단계(y/n/e), 통합 테스트 8항목. **Render 배포** — `https://validator-c6wn.onrender.com` (Blueprint, plan free, rootDir server, Docker; `/healthz` 의 `checker.z3 = true`, backend `z3 5.1.0`). 구 `formalizer-zmm4` 는 suspend 상태(삭제 아님).
- 미완: LTL(`logic: ltl`, 설계-01 §3–§5), 왕복 검증(§8.1), rt-inconsistency(§5.4).
- 배포판 제약: `ANTHROPIC_API_KEY` 미설정이라 provider 는 `canned` 만 — 임의의 자연어는 `400 no canned translation` 이다. 인증 없음·URL 공개이므로 대외비 명세는 사내 Docker 로(`HANDOFF.md` §5). Docker 이미지 빌드·실행은 아직 검증되지 않았다(작업 PC 에 docker 미설치).
