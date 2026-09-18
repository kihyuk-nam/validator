# CLAUDE.md — validator 저장소 작업 규칙 (Claude Code 가 세션 시작 시 자동으로 읽는 파일)

## 이 저장소가 무엇인가
자연어 요구사항의 일관성(무모순성)·실현 가능성 검사 도구. `server/` = formalizer(LLM, 자연어→명세, 틀릴 수 있는 곳) + checker(z3, 명세→판정, 틀리지 않는 곳). `client/` = 원문을 들고 서버를 부르고 확인 단계와 원문 인용 리포트를 담당. 구조·API 는 `README.md`, `server/README.md`. 설계 문서(설계-01, LTL·왕복 검증 계획)는 claude.ai 프로젝트 "validator" 의 `claude/validator-design.md` 에 있고 저장소에는 없다.

## 두 작업자
- **Claude Code(이 환경)** — 코드·테스트·배포의 주체. 저장소에 push 하는 유일한 쪽.
- **Cowork 세션(claude.ai 프로젝트 "validator")** — 설계·문서·구조도·노트북·분석. 코드 변경이 필요하면 파일(zip/patch)과 적용 프롬프트를 사용자에게 주고, 사용자가 이 환경에 넘긴다. Cowork 는 이 저장소를 **프로젝트 지식의 GitHub 동기화(읽기 전용)** 로 본다 — push 는 못 하고, 동기화는 사용자가 프로젝트에서 "Sync" 를 눌러야 갱신된다.

## 불변 규칙
1. `server/checker.py` 의 판정 로직을 바꾸면 `server/examples/expected_findings.json` 회귀가 그대로 통과해야 한다(구현-00 결과: R3·R5 조건부 모순, R6 공허, R5 중복). 바꿔야 한다면 이유를 STATUS.md 에 적는다.
2. 외부 API 는 `POST /validate` 하나(`/audit` 별칭 유지). 응답 형식을 바꾸면 `server/README.md` 와 `client/` 를 같은 커밋에서 맞춘다.
3. formalizer 의 canned 번역은 입력 해시로만 조회된다. 예제 원문(`client/example_battery.py` 의 DOMAIN_TEXT·REQUIREMENTS, `server/examples/battery_input.json`)을 고치면 `server/formalizer/canned/battery.smt.json` 의 `input_sha` 를 다시 만든다(`python -m formalizer.canned add …`).
4. 커밋 전에 `cd server && python tests/test_api.py http://localhost:8000` PASS.
5. API 키·토큰은 커밋하지 않는다. `ANTHROPIC_API_KEY` 는 환경변수/Render 대시보드에서만.

## 세션을 마칠 때 (한 세트)
1. `STATUS.md` 맨 위에 항목을 추가한다 — 날짜, 바꾼 파일, 판정 결과 변화 유무, 배포 URL, 다음 할 일, 결정하지 못한 것. Cowork 는 이 파일을 제일 먼저 읽으므로 짧고 정확하게.
2. 테스트 PASS 확인 후 commit · push.
3. 사용자에게 "프로젝트 validator 에서 GitHub Sync 를 눌러 달라"고 마지막 줄에 알린다. 이것을 빠뜨리면 Cowork 가 낡은 코드를 본다.

동기화 대상에서 빼는 것: `validator_prototype.ipynb`, `docs/*.png`, `server/logs/`, `client/out/` — 프로젝트 지식 한도(2 MB)를 잡아먹고 Cowork 가 코드 판단에 쓰지 않는다. 새로 큰 파일(이미지·데이터·로그)을 추가하면 이 목록에도 적는다.

## 현재 상태 (2026-09-18 기준, 구현 01 첫 단계)
- 완료: 저장소 통합·개명(validator = client + server{formalizer, checker}), `/validate` 2모드, canned·anthropic provider, 확인 단계(y/n/e), 통합 테스트 8항목.
- 미완: LTL(`logic: ltl`, 설계-01 §3–§5), 왕복 검증(§8.1), rt-inconsistency(§5.4), Render 재배포(서비스명 validator).
