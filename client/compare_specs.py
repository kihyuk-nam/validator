"""
compare_specs.py — 두 형식화 결과(명세 JSON)를 validator API(checker)만으로 비교한다.  단계 B(형식화 신뢰성)의 최소 형태.

    python compare_specs.py specs/battery_spec.json specs/claude_spec.json
    python compare_specs.py A.json B.json --validator https://validator-c6wn.onrender.com

① 요구사항별 문자열 비교(구문)
② 요구사항별 SMT 동치(의미): 서버의 전역 일관성 검사를 이용 —
     명세 {L: Aᵢ, NOT_R: ¬Bᵢ} 의 global 이 unsat 이면 DOM ∧ Aᵢ ∧ ¬Bᵢ 가 불가능, 즉 Aᵢ ⇒ Bᵢ.
     반대 방향도 같이 보아 둘 다 성립하면 동치.  sat 이면 global.witness 가 반례.  (DOM 은 A 의 variables 기준)
③ 두 명세 각각 감사해 findings 비교
표준 라이브러리만 사용.
"""
import argparse, json, os, sys, urllib.request


def audit(url, spec):
    """spec 모드로 POST /validate → result (판정 JSON)"""
    req = urllib.request.Request(url.rstrip("/") + "/validate?smt2=0", data=json.dumps({"spec": spec}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["result"]


def formula(r):
    return r["effect"] if r["trigger"].strip() == "true" else f"(=> {r['trigger']} {r['effect']})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--validator", default=os.environ.get("VALIDATOR_URL", "https://validator-c6wn.onrender.com"))
    a = ap.parse_args()
    A, B = (json.load(open(p, encoding="utf-8")) for p in (a.a, a.b))
    ra = {r["id"]: r for r in A["requirements"]}
    print(f"validator: {a.validator}\n")
    print(f"{'ID':4} {'구문':6} {'A⇒B':5} {'B⇒A':5} 판정")
    print("-" * 60)
    for rb in B["requirements"]:
        r_a = ra.get(rb["id"])
        if r_a is None:
            print(f"{rb['id']:4} A 에 없음"); continue
        same = (r_a["trigger"].strip(), r_a["effect"].strip()) == (rb["trigger"].strip(), rb["effect"].strip())
        def implies(lhs, rhs):
            """DOM ∧ lhs ∧ ¬rhs 가 UNSAT 이면 lhs ⇒ rhs.  (unsat, witness)"""
            spec = {"logic": "smt", "variables": A["variables"],
                    "requirements": [{"id": "L", "trigger": "true", "effect": lhs},
                                     {"id": "NOT_R", "trigger": "true", "effect": f"(not {rhs})"}]}
            g = audit(a.validator, spec)["global"]
            return g["status"] == "unsat", g.get("witness")
        ab, wit_ab = implies(formula(r_a), formula(rb))   # A ⇒ B
        ba, wit_ba = implies(formula(rb), formula(r_a))   # B ⇒ A
        verdict = "동치" if ab and ba else ("A 가 더 강함" if ab else ("B 가 더 강함" if ba else "불일치"))
        print(f"{rb['id']:4} {'같음' if same else '다름':6} {'✓' if ab else '✗':5} {'✓' if ba else '✗':5} {verdict}")
        if not same:
            print(f"       A: {formula(r_a)}\n       B: {formula(rb)}")
        if not ab and wit_ab:
            print(f"       반례 A∧¬B: {wit_ab}")
        if not ba and wit_ba:
            print(f"       반례 B∧¬A: {wit_ba}")

    print("\n③ 감사 결과 비교")
    fa, fb = audit(a.validator, A)["findings"], audit(a.validator, B)["findings"]
    key = lambda f: (f["kind"], f.get("req"), tuple(f.get("implied_by") or f.get("core") or []))
    sa, sb = {key(f) for f in fa}, {key(f) for f in fb}
    for k in sorted(sa | sb):
        print(f"  {'양쪽' if k in sa and k in sb else ('A만' if k in sa else 'B만'):4} {k[0]:20s} {k[1]}  {list(k[2])}")


if __name__ == "__main__":
    main()
