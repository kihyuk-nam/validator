"""
client/example_battery.py — 예제 클라이언트: 전기차 배터리 충전 제어기 요구사항의 모순 찾기.

흐름:  자연어 요구사항 ──POST /validate (formalize_only)──▶ 명세 JSON ──(확인)──▶ POST /validate {spec} ──▶ 판정 JSON ──▶ 리포트

    python example_battery.py                                   # provider canned, 확인 프롬프트 y/n/e
    python example_battery.py --yes --out out/                  # 확인 자동 통과 (회귀·CI 용)
    python example_battery.py --provider anthropic              # 서버에 ANTHROPIC_API_KEY 가 있을 때
    python example_battery.py --one-shot                        # 1회 호출로 형식화+검사 (확인 단계 없음)
    python example_battery.py --spec specs/battery_spec.json    # 형식화 건너뛰고 검사만
    python example_battery.py --local                           # 서버 없이 ../server 의 formalizer·checker 직접 호출
    python example_battery.py --validator https://validator-xxxx.onrender.com

형식화(LLM, 틀릴 수 있는 곳)는 서버의 formalizer 가, 판정(z3, 틀리지 않는 곳)은 서버의 checker 가 한다.
클라이언트는 원문을 들고 있다가 결과의 요구사항 ID 를 원문으로 되돌려 리포트를 만든다.  표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List

DEFAULT_URL = os.environ.get("VALIDATOR_URL", "https://validator.onrender.com")

# ---------------------------------------------------------------------------
# 1. 자연어 요구사항 (입력)
# ---------------------------------------------------------------------------
DOMAIN_TEXT = (
    "배터리 온도 센서 측정 범위는 −20 °C ~ 80 °C, 충전 전류 지령 범위는 0 A ~ 50 A 이다. "
    "충전 모드는 급속(fast) 또는 일반이다."
)

REQUIREMENTS: List[Dict[str, str]] = [
    {"id": "R1", "text": "배터리 온도가 45 °C를 초과하면 충전 전류를 10 A 이하로 제한해야 한다."},
    {"id": "R2", "text": "급속 충전 모드에서는 충전 전류를 30 A 이상으로 유지해야 한다."},
    {"id": "R3", "text": "배터리 온도가 50 °C 이상이면 잔여 충전 시간을 줄이기 위해 급속 충전 모드로 전환해야 한다."},
    {"id": "R4", "text": "충전 전류는 어떤 경우에도 32 A를 넘어서는 안 된다."},
    {"id": "R5", "text": "배터리 온도가 60 °C 이상이면 충전 전류를 20 A 이하로 제한해야 한다."},
    {"id": "R6", "text": "배터리 온도가 −30 °C 미만이면 배터리 예열을 위해 급속 충전 모드로 전환해야 한다."},
]


# ---------------------------------------------------------------------------
# 2. 서버 호출
# ---------------------------------------------------------------------------
def post_validate(url: str, body: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(url.rstrip("/") + "/validate", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        sys.exit(f"validator 오류 HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        sys.exit(f"validator({url})에 연결할 수 없음: {e.reason}\n  → 먼저  python ../server/server.py  로 서버를 띄우거나 --local 을 쓰세요.")


def local_validate(body: Dict[str, Any]) -> Dict[str, Any]:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
    import server as srv  # type: ignore
    code, obj = srv.handle_validate(body, keep_smt2=True)
    if code != 200:
        sys.exit(f"validator 오류 {code}: {json.dumps(obj, ensure_ascii=False)}")
    return obj


# ---------------------------------------------------------------------------
# 3. 확인 단계 — 형식화 결과를 원문과 나란히 보여 주고 y/n/e
# ---------------------------------------------------------------------------
def show_formalization(reqs, spec, provenance):
    text_of = {r["id"]: r["text"] for r in reqs}
    print(f"\n[형식화] provider={provenance.get('provider')} model={provenance.get('model', '-')}")
    print("변수:", ", ".join(f"{k}:{v['sort']}{v.get('range', '')}" for k, v in spec["variables"].items()))
    for r in spec["requirements"]:
        print(f"  {r['id']}  {text_of.get(r['id'], '')}\n        ⇒ (=> {r['trigger']} {r['effect']})")


def confirm(spec, out_dir) -> Dict[str, Any]:
    while True:
        ans = input("\n이 형식화로 검사할까요?  y(진행) / n(중단) / e(spec 저장 후 편집해서 --spec 으로 재투입): ").strip().lower()
        if ans == "y":
            return spec
        if ans == "n":
            sys.exit("중단")
        if ans == "e":
            os.makedirs(out_dir or ".", exist_ok=True)
            p = os.path.join(out_dir or ".", "spec_to_edit.json")
            json.dump(spec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            sys.exit(f"{p} 에 저장. 편집 후:  python example_battery.py --spec {p}")


# ---------------------------------------------------------------------------
# 4. 리포트 — core 의 요구사항 ID 를 원문으로 되돌려 인용
# ---------------------------------------------------------------------------
def _fmt_witness(w, spec):
    parts = []
    for k, v in w.items():
        unit = spec["variables"].get(k, {}).get("unit", "")
        parts.append(f"{k}={v}{unit}" if not isinstance(v, bool) else f"{k}={'참' if v else '거짓'}")
    return ", ".join(parts)


def render_report(reqs, spec, result) -> str:
    text_of = {r["id"]: r["text"] for r in reqs}
    form_of = {r["id"]: r for r in spec["requirements"]}
    L = ["# 요구사항 모순 감사 리포트 — 전기차 배터리 충전 제어기", "",
         f"checker 백엔드: `{result['backend']}` · 요구사항 {result['n_requirements']}개 · {result['elapsed_ms']} ms", "",
         "## 1. 입력과 형식화", "", f"도메인: {DOMAIN_TEXT}", "",
         "| ID | 자연어 | trigger | effect |", "|---|---|---|---|"]
    for r in reqs:
        f = form_of[r["id"]]
        L.append(f"| {r['id']} | {r['text']} | `{f['trigger']}` | `{f['effect']}` |")
    L += ["", "## 2. 판정 요약", ""]
    g = result["global"]
    if g["status"] == "sat":
        L.append(f"- **전역 일관성: 만족 가능(SAT).** 예: {_fmt_witness(g['witness'], spec)}. "
                 "→ 모든 요구사항을 동시에 만족하는 상태가 존재하므로 전역 검사만으로는 문제가 보이지 않는다.")
    else:
        L.append(f"- **전역 모순(UNSAT).** 원인 집합: {', '.join(g['core'])}")
    kinds = {"conditional_conflict": "조건부 모순", "vacuous": "공허한 요구사항", "redundant": "중복 요구사항", "global_conflict": "전역 모순"}
    counts: Dict[str, int] = {}
    for f in result["findings"]:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    L += ["- 발견: " + (", ".join(f"{kinds[k]} {n}건" for k, n in counts.items()) or "없음"), "", "## 3. 발견 사항 (원문 인용)", ""]
    for n, f in enumerate(result["findings"], 1):
        if f["kind"] == "conditional_conflict":
            L += [f"### {n}. 조건부 모순 — {f['req']} 의 상황 `{f['trigger']}` 에서", "",
                  "이 상황이 실제로 벌어지면 다음 요구사항들을 동시에 지킬 방법이 없다 (unsat core):", ""]
            L += [f"- **{rid}** — {text_of[rid]}  (`{form_of[rid]['trigger']}` → `{form_of[rid]['effect']}`)" for rid in f["core"]]
        elif f["kind"] == "vacuous":
            L += [f"### {n}. 공허한 요구사항 — {f['req']}", "", f"- **{f['req']}** — {text_of[f['req']]}",
                  f"- trigger `{form_of[f['req']]['trigger']}` 는 도메인 범위 안에서 절대 참이 될 수 없다 → 한 번도 발동하지 않는다. 오타(단위·부호)이거나 도메인 기술이 틀렸을 가능성."]
        elif f["kind"] == "redundant":
            L += [f"### {n}. 중복 요구사항 — {f['req']}", "", f"- **{f['req']}** — {text_of[f['req']]}", "- 다음 요구사항(과 도메인)이 이미 함의한다:"]
            L += [f"  - **{rid}** — {text_of[rid]}" for rid in f["implied_by"]]
            L.append("- 삭제해도 명세의 의미는 같다. 다만 사람이 읽기 위한 강조라면 남겨도 된다.")
        elif f["kind"] == "global_conflict":
            L += [f"### {n}. 전역 모순", ""] + [f"- **{rid}** — {text_of[rid]}" for rid in f["core"] if rid in text_of]
        L.append("")
    L += ["## 4. 요구사항별 상태", "", "| ID | trigger 상태 | 실현 예 (witness) | 중복 |", "|---|---|---|---|"]
    status_ko = {"realizable": "실현 가능", "conflict": "충돌", "vacuous": "공허", "unconditional": "무조건"}
    for r in result["requirements"]:
        w = _fmt_witness(r["witness"], spec) if r.get("witness") else "—"
        red = f"예 (← {', '.join(r['implied_by'])})" if r.get("redundant") else "아니오"
        L.append(f"| {r['id']} | {status_ko.get(r.get('trigger_status', ''), '')} | {w} | {red} |")
    if result.get("smt2"):
        L += ["", f"질의별 SMT-LIB2 파일 {len(result['smt2'])}개는 --out 디렉터리의 smt2/ 에 저장된다 (`z3 파일.smt2` 로 재현)."]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validator", default=DEFAULT_URL, help="validator 서버 주소 (환경변수 VALIDATOR_URL)")
    ap.add_argument("--provider", choices=["canned", "anthropic"], default="canned")
    ap.add_argument("--model", help="--provider anthropic 일 때 모델명")
    ap.add_argument("--spec", help="이미 형식화된 명세 JSON — 형식화 건너뛰고 검사만")
    ap.add_argument("--one-shot", action="store_true", help="형식화+검사를 한 번의 호출로 (확인 단계 없음)")
    ap.add_argument("--yes", action="store_true", help="확인 프롬프트 자동 통과")
    ap.add_argument("--local", action="store_true", help="HTTP 대신 ../server 를 직접 import")
    ap.add_argument("--out", help="리포트·명세·판정·smt2 저장 디렉터리")
    a = ap.parse_args()
    call = local_validate if a.local else (lambda body: post_validate(a.validator, body))

    if a.spec:                                              # 검사만
        spec = json.load(open(a.spec, encoding="utf-8"))
        res = call({"spec": spec})
        provenance = {"provider": "file", "model": a.spec}
    else:
        nl = {"logic": "smt", "domain": DOMAIN_TEXT, "requirements": REQUIREMENTS, "provider": a.provider}
        if a.model:
            nl["model"] = a.model
        if a.one_shot:                                      # 1회 호출
            res = call(nl)
            spec, provenance = res["spec"], res["provenance"]
        else:                                               # 2회 호출: 형식화 → 확인 → 검사
            first = call({**nl, "formalize_only": True})
            spec, provenance = first["spec"], first["provenance"]
            show_formalization(REQUIREMENTS, spec, provenance)
            if not a.yes:
                spec = confirm(spec, a.out)
            res = call({"spec": spec})
    result = res["result"]

    report = render_report(REQUIREMENTS, spec, result)
    print(report)
    if a.out:
        os.makedirs(os.path.join(a.out, "smt2"), exist_ok=True)
        open(os.path.join(a.out, "report.md"), "w", encoding="utf-8").write(report)
        json.dump(spec, open(os.path.join(a.out, "spec.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        json.dump({k: v for k, v in result.items() if k != "smt2"} | {"provenance": provenance},
                  open(os.path.join(a.out, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        for name, txt in result.get("smt2", {}).items():
            open(os.path.join(a.out, "smt2", f"{name}.smt2"), "w", encoding="utf-8").write(txt)
        print(f"[saved] {a.out}/report.md, spec.json, result.json, smt2/*.smt2 ({len(result.get('smt2', {}))}개)", file=sys.stderr)


if __name__ == "__main__":
    main()
