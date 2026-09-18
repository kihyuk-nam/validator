"""
server/tests/test_api.py — validator 통합 테스트 (표준 라이브러리만).

    python tests/test_api.py http://localhost:8000
    python tests/test_api.py https://validator-xxxx.onrender.com

검사 항목
  0. /healthz (절전 중이면 재시도) — checker 백엔드 z3 여부, formalizer providers
  1. spec 모드: examples/battery_spec.json → findings 가 examples/expected_findings.json 과 일치
  2. 자연어 모드(canned): examples/battery_input.json → 같은 findings, provenance.provider == canned
  3. 자연어 모드 2단계: formalize_only → spec 을 그대로 되보내 → 같은 findings
  4. 원문을 한 글자 바꾸면 canned 조회 실패 → 400 + input_sha
  5. 잘못된 spec → 400 ;  R1+R4 만 → findings 없음
  6. /audit 별칭이 /validate 와 같은 결과
exit 0 = 통과.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(HERE, "..", "examples")


def call(url, path, data=None):
    req = urllib.request.Request(url.rstrip("/") + path, data=data, headers={"content-type": "application/json"},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.load(r)


def key(f):
    return (f["kind"], f.get("req"), tuple(sorted(f.get("implied_by") or f.get("core") or [])))


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    fails = 0
    spec = json.load(open(os.path.join(EX, "battery_spec.json"), encoding="utf-8"))
    nl = json.load(open(os.path.join(EX, "battery_input.json"), encoding="utf-8"))
    expected = {key(f) for f in json.load(open(os.path.join(EX, "expected_findings.json"), encoding="utf-8"))}

    def check_findings(tag, result):
        nonlocal fails
        got = {(f["kind"], f.get("req"), tuple(sorted(f.get("implied_by") if f["kind"] == "redundant" else f.get("core", []))))
               for f in result["findings"]}
        if result["global"]["status"] != "sat":
            print(f"  FAIL [{tag}] 전역 일관성은 sat 이어야 함"); fails += 1
        for e in sorted(expected):
            if e in got:
                print(f"  ok   [{tag}] {e[0]:20s} {e[1]}  {list(e[2])}")
            else:
                print(f"  FAIL [{tag}] 기대 결과 없음: {e}"); fails += 1
        for g in got - expected:
            print(f"  FAIL [{tag}] 예상 밖 결과: {g}"); fails += 1

    # 0. healthz
    for i in range(6):
        try:
            st, h = call(url, "/healthz"); break
        except Exception as e:
            print(f"  healthz 대기 중 ({i+1}/6): {e}"); time.sleep(10)
    else:
        sys.exit("FAIL: 서버에 연결할 수 없음")
    print(f"[healthz] {h}")
    if not h.get("checker", {}).get("z3"):
        print("  WARN: z3 없이 grid 백엔드로 동작 중 — 배포판이면 requirements.txt 확인")

    # 1. spec 모드
    st, res = call(url, "/validate?smt2=0", json.dumps({"spec": spec}).encode())
    print(f"[spec 모드] HTTP {st} status={res['status']} backend={res['result']['backend']} elapsed={res['result']['elapsed_ms']} ms")
    check_findings("spec", res["result"])

    # 2. 자연어 모드 (canned, 1회)
    st, res2 = call(url, "/validate?smt2=0", json.dumps(nl).encode())
    print(f"[NL 모드] HTTP {st} status={res2['status']} provider={res2['provenance'].get('provider')} sha={res2['provenance'].get('input_sha', '')[:12]}")
    if res2["provenance"].get("provider") != "canned":
        print("  FAIL: provider 가 canned 가 아님"); fails += 1
    check_findings("nl", res2["result"])

    # 3. 2단계
    st, first = call(url, "/validate", json.dumps({**nl, "formalize_only": True}).encode())
    if first["status"] != "awaiting_confirmation" or "result" in first:
        print("  FAIL: formalize_only 응답 형식"); fails += 1
    st, second = call(url, "/validate?smt2=0", json.dumps({"spec": first["spec"]}).encode())
    print(f"[2단계] 1차 {first['status']} → 2차 {second['status']}")
    check_findings("2단계", second["result"])

    # 4. 원문 변경 → canned 실패
    mutated = json.loads(json.dumps(nl)); mutated["requirements"][0]["text"] += " (수정)"
    try:
        call(url, "/validate", json.dumps(mutated).encode()); print("  FAIL: 원문 변경에 400 이 아님"); fails += 1
    except urllib.error.HTTPError as e:
        body = json.loads(e.read()); print(f"[canned miss] HTTP {e.code} {body.get('error')} sha={body.get('input_sha', '')[:12]}")
        if e.code != 400 or "input_sha" not in body:
            fails += 1

    # 5. 잘못된 spec / 모순 없는 spec
    try:
        call(url, "/validate", json.dumps({"spec": {"variables": {}, "requirements": []}}).encode()); print("  FAIL: 잘못된 spec 에 400 이 아님"); fails += 1
    except urllib.error.HTTPError as e:
        body = json.loads(e.read()); print(f"[400 check] HTTP {e.code} {body.get('detail')}")
        if e.code != 400: fails += 1
    ok_spec = json.loads(json.dumps(spec)); ok_spec["requirements"] = [r for r in ok_spec["requirements"] if r["id"] in ("R1", "R4")]
    st, res5 = call(url, "/validate?smt2=0", json.dumps({"spec": ok_spec}).encode())
    print(f"[clean spec] findings={res5['result']['findings']}")
    if res5["result"]["findings"]:
        print("  FAIL: R1+R4 만으로는 findings 가 없어야 함"); fails += 1

    # 6. /audit 별칭
    st, res6 = call(url, "/audit?smt2=0", json.dumps({"spec": spec}).encode())
    if {key(f) for f in res6["result"]["findings"]} != {key(f) for f in res["result"]["findings"]}:
        print("  FAIL: /audit 별칭 결과 불일치"); fails += 1
    else:
        print("[/audit alias] ok")

    print("\nPASS" if fails == 0 else f"\nFAIL ({fails})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
