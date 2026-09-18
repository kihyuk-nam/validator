# STATUS.md — 세션 간 인수인계 (Claude Code ↔ Cowork)

각 세션이 끝날 때 맨 위에 항목을 추가하고 push 한 뒤, 프로젝트 "validator" 의 GitHub Sync 를 누른다(Cowork 는 동기화된 이 파일을 읽는다).

## 2026-09-18 — Claude Code
- 바꾼 것: 기본 URL 을 실제 배포 주소로 교체(`client/example_battery.py`·`client/compare_specs.py` 의 `VALIDATOR_URL` 기본값, `validator_prototype.ipynb` 의 `VALIDATOR_URL`, `README.md`·`server/README.md`·`server/tests/test_api.py` 의 placeholder). `HANDOFF.md` 신규(타 개발팀 인수인계: 호출 예·스키마 포인터·통합 테스트·절전·502 재시도·무인증 경고). 노트북 부록 A 를 A-1(API)/A-2(채팅창)로 세분화 — 채팅용 지시문 영어판(`server/formalizer/prompts/smt.txt` 와 바이트 동일 + Additional rules)·한국어판 병기, `Domain:`/`Requirements:` 입력 템플릿(canned 입력과 바이트 동일), 입력 블록 생성 셀, spec 모드 검사 셀. `client/specs/chat_spec.json` 신규(A-2 실행 결과 기록). `.gitignore` 에 `CLAUDE_CODE_PROMPT.md` 추가. `CLAUDE.md`·`STATUS.md` 를 저장소 루트로 편입. `CLAUDE.md` 수정 — 실재하지 않는 "GitHub Sync 버튼" 절차를 실제 방식(프로젝트 지식 재가져오기 = 스냅샷 / MCP 파일시스템 커넥터 = 상시 최신)으로 고치고, §현재 상태의 Render 배포를 미완→완료로 옮기고 배포판 제약을 적었다.
- 판정 결과: **구현-00 과 동일** — z3 5.1.0 백엔드로 확인. R3·R5 조건부 모순, R6 공허, R5 중복. `server/examples/expected_findings.json` 회귀 통과(로컬·배포 양쪽). `server/checker.py` 판정 로직은 건드리지 않았다.
- 배포: **완료** — `https://validator-c6wn.onrender.com` (Render Blueprint, plan free, rootDir server, Docker). `/healthz` 의 `checker.z3 = true`, backend `z3 5.1.0`. `python server/tests/test_api.py <URL>` PASS. providers 는 `canned` 만(`ANTHROPIC_API_KEY` 미설정). 구 `formalizer-zmm4` 는 **suspend** 상태(삭제 아님 — `503 Service Suspended`, 서브도메인 계속 점유).
- 다음: 설계-01 순서 (2)~(8): `smt.py` formula 필드·backends 분리 → `checker/ltl.py` → equiv → rt-inconsistency → 왕복 검증 → 클라이언트 트레이스 리포트. 정리하려면 `formalizer-zmm4` 완전 삭제(대시보드 Settings → Delete Service).
- 미결: 설계-01 D4(⑤ 포함)·D11(fretish) 기본값 유지. 인증 미구현 — 공개 URL·무인증이라 대외비 명세는 사내 Docker 권고(HANDOFF §5). **Docker 컨테이너 검증 못 함** — 이 PC 에 docker 미설치라 이미지 빌드·실행은 확인되지 않았다. **MCP 파일시스템 커넥터**를 데스크탑 앱에 설정했다(`claude_desktop_config.json` 의 `mcpServers.filesystem`, 허용 폴더 `...\claude-validator-00-임시`, `node.exe` + 서버 JS 직접 지정으로 PATH 의존 제거). 서버는 `@modelcontextprotocol/server-filesystem@2025.8.21` 로 고정해야 한다 — 이후 버전은 도구 `outputSchema` 를 JSON Schema draft-07 로 선언해 클라이언트가 `unsupported dialect` 로 거부한다. **앱 재시작 후 호출 검증이 필요하다**(설정·기동·도구 목록은 확인했으나, 재시작 전이라 앱 안에서의 실제 호출은 확인하지 못했다). 읽기 전용이 아니므로 채팅이 로컬 파일을 고칠 수 있다.

## 2026-09-18 — Cowork
- 바꾼 것: `formalizer`+`formalizer-client` → `validator/{client,server}` 통합·개명. `audit.py`→`server/checker.py`(`check()`, `audit` 별칭). 형식화를 `server/formalizer/`(canned·anthropic)로 이동. `server.py` `/validate` 2모드(+`/audit` 별칭). 클라이언트 2단계 호출·확인 단계. 노트북 `validator_prototype.ipynb`(부록 A1 API / A2 채팅창). 구조도 3종 `docs/`. `render.yaml` 서비스명 validator, rootDir server.
- 판정 결과: 구현-00 과 동일 (grid 백엔드로 로컬 확인; z3 실행은 Claude Code 몫).
- 배포: 아직. 기대 URL `https://validator[-xxxx].onrender.com`. 배포 후 `client/*.py`·노트북의 기본 URL 을 실제 주소로 교체.
- 다음: (1) Claude Code 에서 z3 로 `tests/test_api.py` PASS 확인 → Render 재배포 → 구 formalizer-zmm4 삭제. (2) 설계-01 순서 (2)~(8): `smt.py` formula 필드·backends 분리 → `checker/ltl.py` → equiv → rt-inconsistency → 왕복 검증 → 클라이언트 트레이스 리포트.
- 미결: 설계-01 D4(⑤ 포함)·D11(fretish) 기본값 유지 중.
