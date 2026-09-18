# validator 인수인계 — 요구사항 모순 검사 API

자연어 요구사항을 **formalizer**(LLM, 자연어 → 형식 명세)가 번역하고 **checker**(z3, 명세 → 판정)가 모순·공허·중복을 찾아 주는 HTTP 서버다.
언어 상관없이 `POST` 한 번으로 쓸 수 있다. 서버·클라이언트 모두 Python 표준 라이브러리만 쓴다(서버의 z3-solver 제외).

## 1. 접속 정보

| | |
|---|---|
| **Base URL** | `https://validator-c6wn.onrender.com` |
| 상태 확인 | `GET /healthz` |
| 검사 | `POST /validate` (별칭 `POST /audit`) |
| 인증 | **없음** |
| 호스팅 | Render 무료 인스턴스 (Docker, `server/` 를 그대로 빌드) |
| 검증 시각 | 2026-09-18, `server/tests/test_api.py` PASS |

현재 `/healthz` 응답:

```json
{"ok": true,
 "checker": {"backend": "z3 5.1.0", "z3": true},
 "formalizer": {"providers": ["canned"], "canned": ["battery.smt"]}}
```

`checker.z3` 가 `false` 면 z3 없이 grid 폴백으로 돌고 있다는 뜻이다(개발용). 배포판은 항상 `true` 여야 한다.

## 2. 먼저 알아야 할 제약 두 가지

**① 절전 — 첫 호출이 ~1분 걸린다.**
무료 인스턴스는 15분 동안 요청이 없으면 잠든다. 깨어나는 데 40~60초가 걸리므로, 깨어 있을 때의 응답 시간(아래 §3 기준 0.3~0.4초)과 착각하면 타임아웃을 너무 짧게 잡게 된다.

- 클라이언트 타임아웃은 **최소 90초**로 잡을 것.
- 배치 작업 전에 `GET /healthz` 로 먼저 깨우면 그다음 호출부터는 빠르다.
- 저장소의 클라이언트들은 이미 이 점을 반영해 재시도·긴 타임아웃을 갖고 있다.

**② `canned` provider 만 켜져 있다 — 임의의 자연어는 아직 안 된다.**
서버에 `ANTHROPIC_API_KEY` 가 없으므로 formalizer 는 미리 저장된 번역(`canned`)만 조회한다. 조회 키는 `domain` + 요구사항 원문을 정규화한 sha256 이라, **원문이 한 글자라도 다르면** 다음과 같이 거절된다.

```json
HTTP 400 {"error": "no canned translation for this input", "input_sha": "6c89e260..."}
```

즉 **자연어 모드는 현재 배터리 예제(`server/examples/battery_input.json`) 하나에서만 동작한다.** 두 가지 선택지가 있다.

- **여러분의 요구사항을 넣으려면 → spec 모드(§3-B)를 쓴다.** trigger/effect 를 SMT-LIB 식으로 직접 주면 checker 는 제약 없이 동작한다. 실무에서 쓸 경로는 이쪽이다.
- 임의의 자연어를 자동 번역하려면 Render 대시보드 → 서비스 `validator` → Environment 에 `ANTHROPIC_API_KEY` 를 비밀값으로 추가하면 `provider: "anthropic"` 이 열린다. 단 공개 URL 에 키를 붙이는 것이므로 §5 를 먼저 읽을 것.

## 3. 호출 예 — 두 가지 입력 모드

`?smt2=0` 을 붙이면 응답에서 `result.smt2`(질의별 SMT-LIB2 원문)를 생략해 응답이 훨씬 작아진다. 재현·감사가 필요할 때만 빼라.

### A. 자연어 모드 — formalizer → checker

**curl**

```bash
URL=https://validator-c6wn.onrender.com
curl -s "$URL/healthz"                                        # 먼저 깨우기
curl -s -X POST "$URL/validate?smt2=0" \
     -H "content-type: application/json" \
     --data-binary @server/examples/battery_input.json
```

응답은 `{"status": "checked", "spec": {...}, "provenance": {...}, "result": {...}}` 형태다. `provenance` 에 어떤 provider·모델이 번역했는지와 `input_sha` 가 들어 있다.

`"formalize_only": true` 를 넣으면 검사 없이 `{"status": "awaiting_confirmation", "spec", "provenance"}` 만 돌아온다. **사람이 형식화 결과를 눈으로 확인한 뒤** 그 `spec` 을 그대로 B 모드로 다시 보내는 2단계 흐름을 권한다 — 형식화는 LLM 이 하는, 틀릴 수 있는 단계이기 때문이다.

**Python** (표준 라이브러리만)

canned 조회는 원문이 정확히 일치해야 하므로, 아래 예제는 `domain` 과 요구사항 원문을 예제 파일에서 그대로 읽는다. 이대로 실행하면 동작한다.

```python
import json, urllib.request

URL = "https://validator-c6wn.onrender.com"

# 원문을 직접 타이핑하면 sha 가 달라져 400 이 난다 — 예제 파일을 그대로 읽는다
body = json.load(open("server/examples/battery_input.json", encoding="utf-8"))
body["formalize_only"] = True     # 1단계: 형식화만 받아 사람이 확인

req = urllib.request.Request(URL + "/validate", data=json.dumps(body).encode("utf-8"),
                             headers={"content-type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=180) as r:   # 절전 대비 긴 타임아웃
    first = json.load(r)

print(first["status"], first["provenance"]["provider"])
for r_ in first["spec"]["requirements"]:              # 사람이 확인할 대상
    print(f"  {r_['id']}: (=> {r_['trigger']} {r_['effect']})")

# 2단계: 확인한 spec 을 그대로 되보내 검사
req2 = urllib.request.Request(URL + "/validate?smt2=0",
                              data=json.dumps({"spec": first["spec"]}).encode("utf-8"),
                              headers={"content-type": "application/json"}, method="POST")
with urllib.request.urlopen(req2, timeout=180) as r:
    print(len(json.load(r)["result"]["findings"]), "findings")
```

저장소 루트에서 실행한 실제 출력:

```
awaiting_confirmation canned
  R1: (=> (> temp 45) (<= current 10))
  R2: (=> fast (>= current 30))
  R3: (=> (>= temp 50) fast)
  R4: (=> true (<= current 32))
  R5: (=> (>= temp 60) (<= current 20))
  R6: (=> (< temp (- 30)) fast)
4 findings
```

### B. spec 모드 — checker 만 (여러분의 요구사항에 쓸 경로)

**curl**

```bash
URL=https://validator-c6wn.onrender.com
curl -s -X POST "$URL/validate?smt2=0" \
     -H "content-type: application/json" \
     --data-binary @server/examples/battery_spec.json
```

최상위에 `variables` 와 `requirements` 가 있으면 spec 으로 인식한다. `{"spec": {...}}` 로 감싸도 같다.

**Python**

```python
import json, urllib.request

URL = "https://validator-c6wn.onrender.com"

spec = {
    "logic": "smt",
    "variables": {
        "temp":    {"sort": "Real", "range": [-20, 80], "unit": "°C"},
        "current": {"sort": "Real", "range": [0, 50],   "unit": "A"},
        "fast":    {"sort": "Bool"},
    },
    "requirements": [
        {"id": "R1", "trigger": "(> temp 45)",     "effect": "(<= current 10)"},
        {"id": "R2", "trigger": "fast",            "effect": "(>= current 30)"},
        {"id": "R3", "trigger": "(>= temp 50)",    "effect": "fast"},
        {"id": "R4", "trigger": "true",            "effect": "(<= current 32)"},
        {"id": "R5", "trigger": "(>= temp 60)",    "effect": "(<= current 20)"},
        {"id": "R6", "trigger": "(< temp (- 30))", "effect": "fast"},
    ],
}

req = urllib.request.Request(URL + "/validate?smt2=0", data=json.dumps({"spec": spec}).encode("utf-8"),
                             headers={"content-type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=180) as r:
    result = json.load(r)["result"]

print(result["global"]["status"])                       # sat
for f in result["findings"]:
    # redundant 는 implied_by(원인 요구사항)가, 나머지는 core(unsat core)가 본질이다
    print(f["kind"], f["req"], f.get("implied_by") or f.get("core"))
```

위 spec 의 실제 출력 — 전역 검사만으로는 문제가 안 보이지만(`sat`) 조건부로 4건이 나온다:

```
sat
conditional_conflict R3 ['R1', 'R2', 'R3']
conditional_conflict R5 ['R2', 'R3', 'R5']
vacuous R6 ['DOM', 'TRIG_R6']
redundant R5 ['R1']
```

읽는 법은 이렇다. `R3` 의 trigger 가 성립하는 상황(`temp ≥ 50`)에서는 R1·R2·R3 을 동시에 지킬 방법이 없다 — 이게 unsat core 다. `R6` 의 trigger(`temp < −30`)는 도메인(`temp ∈ [−20, 80]`)에서 절대 참이 될 수 없어 한 번도 발동하지 않는다(단위·부호 오타를 의심할 자리). `R5` 는 R1 이 이미 함의하므로 지워도 명세의 의미가 같다.

`core` 의 원소 중 `DOM`, `TRIG_<id>`, `NOT_<id>` 는 내부 라벨이다. 사용자에게 보여 줄 때는 **요구사항 ID 만 골라** 원문으로 되돌려 인용하라 — `client/example_battery.py` 의 `render_report()` 가 그 방식의 참고 구현이다.

## 4. 스키마·테스트·클라이언트

**입력/출력 스키마 전체는 [`server/README.md`](server/README.md) 를 보라.** 거기에 `variables.<name>.sort`/`range` 규칙, 허용 연산자 목록, `result` 의 모든 필드, `findings[].kind` 4종(`global_conflict`·`conditional_conflict`·`vacuous`·`redundant`)의 의미, 오류 코드(`400` 입력·스키마·canned 미존재 / `503` provider 없음 / `500` 내부)가 정리돼 있다. 이 문서는 그걸 중복하지 않는다.

**통합 테스트** — 서버가 정상인지 확인하는 가장 빠른 방법이다. 배포 주소든 사내 주소든 URL 만 바꿔 주면 된다.

```bash
python server/tests/test_api.py https://validator-c6wn.onrender.com
```

spec 모드·자연어 모드·2단계 흐름·canned 미존재 400·잘못된 spec 400·`/audit` 별칭을 검사하고 마지막에 `PASS` 를 출력한다(exit 0). 절전 중이면 `/healthz` 를 10초 간격으로 6회 재시도하므로 첫 실행은 1분 가까이 걸릴 수 있다 — 기다리면 된다.

**참고 클라이언트** — 그대로 써도 되고 읽고 베껴도 된다. 둘 다 기본 URL 이 위 배포 주소이고, `--validator URL` 또는 환경변수 `VALIDATOR_URL` 로 바꿀 수 있다.

```bash
cd client
python example_battery.py --yes --out out/          # 형식화 → 확인 → 검사 → Markdown 리포트
python compare_specs.py specs/battery_spec.json specs/claude_spec.json
```

`example_battery.py` 는 `out/report.md`(사람이 읽는 리포트), `spec.json`, `result.json`, `smt2/*.smt2`(z3 로 재현 가능한 질의)를 남긴다. `compare_specs.py` 는 형식화가 다르게 나왔을 때 두 명세가 **의미상 동치인지** checker 로 판정한다 — 구문이 달라도 동치일 수 있어서(`fast` vs `(= fast true)`) 유용하다.

## 5. 무료 플랜의 한계 — 실제 명세는 여기 올리지 말 것

이 인스턴스는 **URL 이 공개돼 있고 인증이 전혀 없다.** 주소를 아는 누구든 호출할 수 있고, 여러분이 보낸 요구사항 본문은 Render 의 인프라를 지나간다.

**따라서 대외비·고객 요구사항을 이 주소로 보내지 말 것.** 이 인스턴스는 기능 확인과 통합 개발용이다.

실제 명세는 같은 이미지를 사내에서 띄워 쓰라. 코드는 완전히 동일하다.

```bash
cd server
docker build -t validator .
docker run -d -p 8000:7860 --name validator validator
python tests/test_api.py http://localhost:8000     # PASS 확인
```

사내 URL 로 바꾸는 건 `--validator http://<사내주소>:8000` 또는 `VALIDATOR_URL` 환경변수 하나다.

간단한 인증이 필요하면 `server/server.py` 의 `do_POST` 맨 앞에 `Authorization: Bearer <토큰>` 검사 몇 줄을 넣고 토큰을 환경변수로 주면 된다. 현재는 들어 있지 않다.

## 6. 설계상 알아 둘 점

이 도구의 핵심은 **틀릴 수 있는 곳과 틀리지 않는 곳을 분리**한 것이다.

- **formalizer** (LLM): 자연어 → 형식 명세. 틀릴 수 있다. 그래서 `formalize_only` 로 결과를 사람에게 보여 주고 확인받는 단계가 따로 있다.
- **checker** (z3): 명세 → 판정. 여기서 나온 모순은 수학적으로 확실하다. `smt2` 필드의 SMT-LIB2 원문을 `z3 파일.smt2` 로 직접 돌려 재현·감사할 수 있다.

그래서 **검사 결과를 신뢰하기 전에 형식화가 원문의 뜻을 맞게 옮겼는지 확인해야 한다.** 판정을 의심할 게 아니라 번역을 의심하는 게 맞다. spec 모드를 쓰면 이 불확실성 자체가 없어진다.

전역 일관성(`global.status`)이 `sat` 이어도 안심하면 안 된다는 점도 중요하다. 위 예제가 정확히 그 경우다 — 모든 요구사항을 동시에 만족하는 상태가 존재하지만(`temp=0, current=0, fast=false`), 특정 trigger 상황에 들어가면 지킬 수 없는 조합이 두 건 있다. 전역 검사만 돌리는 도구가 놓치는 부분이다.

## 7. 저장소

`https://github.com/kihyuk-nam/validator` (private)

```
server/    server.py(HTTP) · formalizer/(형식화) · checker.py(z3 판정) · Dockerfile · tests/ · examples/
client/    example_battery.py · compare_specs.py · specs/
render.yaml            Render Blueprint (name validator, rootDir server, plan free)
validator_prototype.ipynb   전체 흐름을 순서대로 실행해 보는 노트북
README.md              구조 개요
server/README.md       API 스키마 (입력·출력 전체)
```

`server/checker.py` 의 판정 로직은 결과가 바뀌면 안 되는 부분이다. 고칠 일이 있으면 `server/tests/test_api.py` 가 계속 PASS 인지 먼저 확인하라.
