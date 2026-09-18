"""
server/checker.py — 형식화된 요구사항 명세(JSON)를 받아 z3 로 감사 4종을 수행하는 검사기(checker). "틀리지 않는 곳".

입력 스키마 (logic = "smt"):
    {
      "logic": "smt",
      "variables": {
        "temp":    {"sort": "Real", "range": [-20, 80], "unit": "°C"},
        "current": {"sort": "Real", "range": [0, 50],  "unit": "A"},
        "fast":    {"sort": "Bool"}
      },
      "requirements": [
        {"id": "R1", "trigger": "(> temp 45)", "effect": "(<= current 10)"},
        ...
      ]
    }
  각 요구사항 Rᵢ 는 SMT-LIB 식  (=> trigger effect)  로 해석한다.
  무조건 요구사항은 trigger = "true".

감사 4종 (VERIMED 방식, 프로젝트 문서 §1·§2 참조):
    ① 전역 일관성   sat( DOM ∧ ⋀R )
    ② 공허성        sat( DOM ∧ trigᵢ )              — UNSAT 이면 절대 발동하지 않는 요구사항
    ③ trigger 실현성 sat( DOM ∧ ⋀R ∧ trigᵢ )        — UNSAT 이면 그 상황에서 조건부 충돌, unsat core 가 원인 집합
    ④ 중복성        sat( DOM ∧ ⋀R∖Rᵢ ∧ ¬Rᵢ )        — UNSAT 이면 Rᵢ 는 나머지가 이미 함의

백엔드: z3 가 설치돼 있으면 z3 (assert_and_track + unsat_core),
        없으면 유한 격자(grid) 브루트포스 + 삭제 기반 최소 충돌 부분집합(MUS).
        두 백엔드는 같은 인터페이스(check → status, model, core)를 가진다.

외부 의존성 없음 (z3-solver 는 선택).  Python 3.9+.
"""
from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Tuple

try:  # z3 는 선택 의존성
    import z3  # type: ignore

    HAVE_Z3 = True
except Exception:  # pragma: no cover
    z3 = None
    HAVE_Z3 = False


# ---------------------------------------------------------------------------
# 0. 오류 타입
# ---------------------------------------------------------------------------
class SpecError(ValueError):
    """입력 명세(JSON)가 스키마·문법에 맞지 않을 때 — HTTP 400 으로 매핑."""


# ---------------------------------------------------------------------------
# 1. SMT-LIB s-식 파서 / 평가기 (grid 백엔드용, 그리고 스키마 검증용)
# ---------------------------------------------------------------------------
def tokenize(s: str) -> List[str]:
    return s.replace("(", " ( ").replace(")", " ) ").split()


def parse_sexpr(s: str) -> Any:
    """SMT-LIB 식 문자열 → 중첩 리스트/원자. 예: "(=> (> temp 45) (<= current 10))"."""
    toks = tokenize(s)
    if not toks:
        raise SpecError("빈 식")
    pos = 0

    def read() -> Any:
        nonlocal pos
        if pos >= len(toks):
            raise SpecError(f"괄호가 닫히지 않음: {s!r}")
        t = toks[pos]
        pos += 1
        if t == "(":
            lst = []
            while pos < len(toks) and toks[pos] != ")":
                lst.append(read())
            if pos >= len(toks):
                raise SpecError(f"괄호가 닫히지 않음: {s!r}")
            pos += 1  # ')'
            return lst
        if t == ")":
            raise SpecError(f"짝이 없는 ')': {s!r}")
        return t

    ast = read()
    if pos != len(toks):
        raise SpecError(f"식 뒤에 남는 토큰: {s!r}")
    return ast


def _num(tok: str) -> Optional[Fraction]:
    try:
        return Fraction(tok)
    except (ValueError, ZeroDivisionError):
        return None


_BOOL_OPS = {"and", "or", "not", "=>", "xor"}
_CMP_OPS = {"=", "distinct", "<", "<=", ">", ">="}
_ARITH_OPS = {"+", "-", "*", "/"}
_ALL_OPS = _BOOL_OPS | _CMP_OPS | _ARITH_OPS | {"ite", "true", "false"}


def free_symbols(ast: Any) -> set:
    if isinstance(ast, list):
        out: set = set()
        if not ast:
            return out
        head, rest = ast[0], ast[1:]
        if not isinstance(head, str) or head not in _ALL_OPS:
            raise SpecError(f"알 수 없는 연산자: {head!r}")
        for a in rest:
            out |= free_symbols(a)
        return out
    if ast in ("true", "false") or _num(ast) is not None:
        return set()
    return {ast}


def compile_expr(ast: Any, sorts: Dict[str, str]) -> Callable[[Dict[str, Any]], Any]:
    """AST → env(dict) 를 받아 값을 돌려주는 클로저.  grid 백엔드에서 수만 점을 평가하므로 미리 컴파일."""
    if not isinstance(ast, list):
        if ast == "true":
            return lambda env: True
        if ast == "false":
            return lambda env: False
        n = _num(ast)
        if n is not None:
            return lambda env, n=n: n
        if ast not in sorts:
            raise SpecError(f"선언되지 않은 변수: {ast!r}")
        return lambda env, v=ast: env[v]

    head, args = ast[0], [compile_expr(a, sorts) for a in ast[1:]]
    if head == "and":
        return lambda env: all(f(env) for f in args)
    if head == "or":
        return lambda env: any(f(env) for f in args)
    if head == "not":
        (f,) = args
        return lambda env: not f(env)
    if head == "=>":  # 우결합: (=> a b c) = a → (b → c)
        def imp(env):
            vals = [f(env) for f in args]
            acc = vals[-1]
            for v in reversed(vals[:-1]):
                acc = (not v) or acc
            return acc
        return imp
    if head == "xor":
        return lambda env: sum(bool(f(env)) for f in args) % 2 == 1
    if head == "ite":
        c, t, e = args
        return lambda env: t(env) if c(env) else e(env)
    if head in _CMP_OPS:
        import operator as op
        cmp = {"=": op.eq, "<": op.lt, "<=": op.le, ">": op.gt, ">=": op.ge}
        if head == "distinct":
            return lambda env: len({f(env) for f in args}) == len(args)
        fn = cmp[head]
        return lambda env: all(fn(a(env), b(env)) for a, b in zip(args[:-1], args[1:]))
    if head == "+":
        return lambda env: sum(f(env) for f in args)
    if head == "-":
        if len(args) == 1:
            (f,) = args
            return lambda env: -f(env)
        return lambda env: args[0](env) - sum(f(env) for f in args[1:])
    if head == "*":
        def mul(env):
            acc = Fraction(1)
            for f in args:
                acc *= f(env)
            return acc
        return mul
    if head == "/":
        return lambda env: args[0](env) / args[1](env)
    raise SpecError(f"알 수 없는 연산자: {head!r}")


# ---------------------------------------------------------------------------
# 2. 명세(스키마) 검증 + 정규화
# ---------------------------------------------------------------------------
@dataclass
class Var:
    name: str
    sort: str                       # Bool | Int | Real
    lo: Optional[Fraction] = None
    hi: Optional[Fraction] = None
    unit: str = ""


@dataclass
class Req:
    id: str
    trigger: str
    effect: str
    trigger_ast: Any = None
    effect_ast: Any = None

    @property
    def unconditional(self) -> bool:
        return self.trigger_ast == "true"

    @property
    def formula(self) -> str:
        return self.effect if self.unconditional else f"(=> {self.trigger} {self.effect})"


@dataclass
class Spec:
    variables: Dict[str, Var]
    requirements: List[Req]

    @property
    def sorts(self) -> Dict[str, str]:
        return {v.name: v.sort for v in self.variables.values()}

    def domain_formula(self) -> str:
        parts = []
        for v in self.variables.values():
            if v.sort == "Bool":
                continue
            parts.append(f"(<= {_lit(v.lo)} {v.name})")
            parts.append(f"(<= {v.name} {_lit(v.hi)})")
        return "(and " + " ".join(parts) + ")" if parts else "true"


def _lit(x: Fraction) -> str:
    """Fraction → SMT-LIB 리터럴.  음수는 (- 20) 형태."""
    if x.denominator == 1:
        s = str(abs(x.numerator))
    else:
        s = f"(/ {abs(x.numerator)} {x.denominator})"
    return f"(- {s})" if x < 0 else s


def validate_spec(doc: Dict[str, Any]) -> Spec:
    if not isinstance(doc, dict):
        raise SpecError("최상위는 JSON 객체여야 함")
    if doc.get("logic", "smt") != "smt":
        raise SpecError(f"지원하지 않는 logic: {doc.get('logic')!r} (현재 'smt' 만 지원, 'ltl' 은 단계 C)")
    variables = doc.get("variables")
    reqs = doc.get("requirements")
    if not isinstance(variables, dict) or not variables:
        raise SpecError("'variables' 는 비어 있지 않은 객체여야 함")
    if not isinstance(reqs, list) or not reqs:
        raise SpecError("'requirements' 는 비어 있지 않은 배열이어야 함")

    vars_: Dict[str, Var] = {}
    for name, d in variables.items():
        if not isinstance(d, dict) or d.get("sort") not in ("Bool", "Int", "Real"):
            raise SpecError(f"변수 {name!r}: sort 는 Bool | Int | Real 이어야 함")
        v = Var(name=name, sort=d["sort"], unit=str(d.get("unit", "")))
        if v.sort != "Bool":
            rng = d.get("range")
            if not (isinstance(rng, list) and len(rng) == 2):
                raise SpecError(f"변수 {name!r}: 수치형 변수는 range [lo, hi] 가 필요함 (grid 백엔드의 유한성 보장)")
            v.lo, v.hi = Fraction(str(rng[0])), Fraction(str(rng[1]))
            if v.lo > v.hi:
                raise SpecError(f"변수 {name!r}: range 하한이 상한보다 큼")
        vars_[name] = v

    out: List[Req] = []
    seen = set()
    for i, r in enumerate(reqs):
        if not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in ("id", "trigger", "effect")):
            raise SpecError(f"requirements[{i}]: id / trigger / effect 문자열이 필요함")
        if r["id"] in seen or r["id"] == "DOM":
            raise SpecError(f"요구사항 id 중복 또는 예약어: {r['id']!r}")
        seen.add(r["id"])
        req = Req(id=r["id"], trigger=r["trigger"].strip(), effect=r["effect"].strip())
        for fld in ("trigger", "effect"):
            ast = parse_sexpr(getattr(req, fld))
            unknown = free_symbols(ast) - set(vars_)
            if unknown:
                raise SpecError(f"{req.id}.{fld}: 선언되지 않은 기호 {sorted(unknown)}")
            setattr(req, fld + "_ast", ast)
        out.append(req)
    return Spec(variables=vars_, requirements=out)


# ---------------------------------------------------------------------------
# 3. SMT-LIB2 텍스트 생성 (재현용 .smt2 — `z3 file.smt2` 로 그대로 실행 가능)
# ---------------------------------------------------------------------------
def to_smt2(spec: Spec, assertions: List[Tuple[str, str]], comment: str = "") -> str:
    lines = []
    if comment:
        lines += [f"; {c}" for c in comment.splitlines()]
    lines += ["(set-option :produce-unsat-cores true)", "(set-option :produce-models true)"]
    for v in spec.variables.values():
        lines.append(f"(declare-const {v.name} {v.sort})")
    for name, f in assertions:
        lines.append(f"(assert (! {f} :named {name}))")
    lines += ["(check-sat)", "(get-unsat-core)", "(get-model)"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 4. 백엔드
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    status: str                              # "sat" | "unsat"
    model: Optional[Dict[str, Any]] = None   # sat 일 때 증인(witness)
    core: List[str] = field(default_factory=list)  # unsat 일 때 원인 집합 (assertion 이름)


class Backend:
    name = "abstract"

    def check(self, spec: Spec, assertions: List[Tuple[str, str]]) -> CheckResult:
        raise NotImplementedError


def _jsonable(x: Any) -> Any:
    if isinstance(x, Fraction):
        return int(x) if x.denominator == 1 else float(x)
    return x


class Z3Backend(Backend):
    """z3: 식은 z3 의 SMT-LIB 파서로 읽고, assert_and_track 으로 이름을 달아 unsat core 를 얻는다."""

    def __init__(self):
        self.name = f"z3 {z3.get_version_string()}"

    def check(self, spec: Spec, assertions: List[Tuple[str, str]]) -> CheckResult:
        decls = {}
        for v in spec.variables.values():
            decls[v.name] = {"Bool": z3.Bool, "Int": z3.Int, "Real": z3.Real}[v.sort](v.name)
        s = z3.Solver()
        s.set(unsat_core=True)
        for name, f in assertions:
            expr = z3.parse_smt2_string(f"(assert {f})", decls=decls)[0]
            s.assert_and_track(expr, z3.Bool(name))
        r = s.check()
        if r == z3.sat:
            m = s.model()
            model = {}
            for v in spec.variables.values():
                val = m.eval(decls[v.name], model_completion=True)
                if v.sort == "Bool":
                    model[v.name] = z3.is_true(val)
                elif v.sort == "Int":
                    model[v.name] = val.as_long()
                else:
                    fr = val.as_fraction()
                    model[v.name] = _jsonable(Fraction(fr.numerator, fr.denominator))
            return CheckResult("sat", model=model)
        if r == z3.unsat:
            return CheckResult("unsat", core=sorted(str(c) for c in s.unsat_core()))
        raise RuntimeError(f"z3 returned {r}")


class GridBackend(Backend):
    """
    z3 폴백: 각 수치 변수의 range 를 step 간격으로 잘라 만든 유한 격자 위에서 모든 점을 시험한다.
    - 격자 위에 만족점이 있으면 sat (증인은 실제 만족점이므로 건전).
    - 격자 위에 없으면 unsat 으로 보고하지만, 격자 사이(예: 45.3)에만 해가 있는 경우를 놓칠 수 있다
      → 이 백엔드의 unsat 은 '격자 해상도 한에서' 라는 단서가 붙는다. 실제 운용은 z3 권장.
    - unsat core: 삭제 기반 MUS — 하나씩 빼 보며 여전히 unsat 이면 버린다.
    """

    def __init__(self, step: Fraction = Fraction(1, 2), max_points: int = 2_000_000):
        self.step = step
        self.max_points = max_points
        self.name = f"grid(step={step})"

    def _axes(self, spec: Spec) -> List[Tuple[str, List[Any]]]:
        axes = []
        total = 1
        for v in spec.variables.values():
            if v.sort == "Bool":
                vals: List[Any] = [False, True]
            else:
                step = Fraction(1) if v.sort == "Int" else self.step
                n = int(math.floor((v.hi - v.lo) / step))
                vals = [v.lo + k * step for k in range(n + 1)]
                if vals[-1] != v.hi:
                    vals.append(v.hi)
            axes.append((v.name, vals))
            total *= len(vals)
        if total > self.max_points:
            raise SpecError(f"grid 백엔드: 격자점 {total:,} 개가 한도({self.max_points:,})를 넘음 — z3 를 설치하거나 range/step 을 줄이세요")
        return axes

    # 같은 식(DOM, R1, …)이 감사 질의마다 반복되므로, 식 → 만족 격자점 집합을 한 번만 계산해 캐시한다.
    def _points(self, spec: Spec):
        key = id(spec)
        if getattr(self, "_pts_key", None) != key:
            axes = self._axes(spec)
            names = [a[0] for a in axes]
            self._pts_key = key
            self._names = names
            self._grid = list(itertools.product(*[a[1] for a in axes]))
            self._sets: Dict[str, frozenset] = {}
        return self._names, self._grid

    def _satset(self, spec: Spec, formula: str) -> frozenset:
        names, grid = self._points(spec)
        if formula not in self._sets:
            f = compile_expr(parse_sexpr(formula), spec.sorts)
            self._sets[formula] = frozenset(i for i, combo in enumerate(grid) if f(dict(zip(names, combo))))
        return self._sets[formula]

    def check(self, spec: Spec, assertions: List[Tuple[str, str]]) -> CheckResult:
        names, grid = self._points(spec)
        sets = {name: self._satset(spec, f) for name, f in assertions}

        def common(keys) -> frozenset:
            acc = None
            for k in keys:
                acc = sets[k] if acc is None else acc & sets[k]
                if not acc:
                    break
            return acc if acc is not None else frozenset(range(len(grid)))

        hit = common(sets)
        if hit:
            combo = grid[min(hit)]
            return CheckResult("sat", model={k: _jsonable(v) for k, v in zip(names, combo)})
        # 삭제 기반 MUS.  DOM 은 격자 자체가 이미 인코딩하고 있으므로(격자 밖 점은 시험 불가) 항상 core 에 남긴다.
        core = list(sets)
        for name in list(core):
            if name == "DOM":
                continue
            trial = [k for k in core if k != name]
            if trial and not common(trial):
                core.remove(name)
        return CheckResult("unsat", core=sorted(core))


def default_backend() -> Backend:
    return Z3Backend() if HAVE_Z3 else GridBackend()


# ---------------------------------------------------------------------------
# 5. 감사 4종
# ---------------------------------------------------------------------------
def check(doc: Dict[str, Any], backend: Optional[Backend] = None, keep_smt2: bool = True) -> Dict[str, Any]:
    """명세 JSON → 판정 JSON.  server.py 의 POST /validate (spec 모드) 가 이 함수를 그대로 호출한다."""
    t0 = time.perf_counter()
    spec = validate_spec(doc)
    be = backend or default_backend()
    smt2: Dict[str, str] = {}
    findings: List[Dict[str, Any]] = []
    per_req: Dict[str, Dict[str, Any]] = {r.id: {"id": r.id} for r in spec.requirements}

    DOM = ("DOM", spec.domain_formula())
    R_all = [(r.id, r.formula) for r in spec.requirements]

    def run(key: str, assertions: List[Tuple[str, str]], comment: str) -> CheckResult:
        if keep_smt2:
            smt2[key] = to_smt2(spec, assertions, comment)
        return be.check(spec, assertions)

    # ① 전역 일관성
    g = run("global", [DOM] + R_all, "① global consistency: DOM ∧ ⋀R")
    glob = {"status": g.status, "witness": g.model, "core": g.core}
    if g.status == "unsat":
        findings.append({"kind": "global_conflict", "core": g.core,
                         "message": "모든 요구사항을 동시에 만족하는 상태가 없음"})

    # ② 공허성 · ③ trigger 실현성
    for r in spec.requirements:
        info = per_req[r.id]
        if r.unconditional:
            info["trigger_status"] = "unconditional"
            continue
        trig = (f"TRIG_{r.id}", r.trigger)
        v = run(f"vacuity_{r.id}", [DOM, trig], f"② vacuity of {r.id}: DOM ∧ trigger")
        if v.status == "unsat":
            info["trigger_status"] = "vacuous"
            info["core"] = v.core
            findings.append({"kind": "vacuous", "req": r.id, "core": v.core,
                             "message": f"{r.id} 의 trigger {r.trigger} 는 도메인 안에서 절대 참이 될 수 없음 — 발동하지 않는 요구사항"})
            continue
        c = run(f"trigger_{r.id}", [DOM] + R_all + [trig], f"③ trigger realizability of {r.id}: DOM ∧ ⋀R ∧ trigger")
        if c.status == "sat":
            info["trigger_status"] = "realizable"
            info["witness"] = c.model
        else:
            reqs_in_core = [x for x in c.core if x in per_req]
            info["trigger_status"] = "conflict"
            info["core"] = c.core
            findings.append({"kind": "conditional_conflict", "req": r.id, "trigger": r.trigger,
                             "core": reqs_in_core, "raw_core": c.core,
                             "message": f"{r.id} 의 trigger 상황({r.trigger})에서 {', '.join(reqs_in_core)} 을(를) 동시에 만족할 수 없음"})

    # ④ 중복성
    for r in spec.requirements:
        info = per_req[r.id]
        if info.get("trigger_status") == "vacuous":
            info["redundant"] = False
            continue
        others = [(x.id, x.formula) for x in spec.requirements if x.id != r.id]
        neg = (f"NOT_{r.id}", f"(not {r.formula})")
        d = run(f"redundancy_{r.id}", [DOM] + others + [neg], f"④ redundancy of {r.id}: DOM ∧ ⋀R∖{r.id} ∧ ¬{r.id}")
        implied_by = [x for x in d.core if x in per_req]
        if d.status == "unsat" and implied_by:
            info["redundant"] = True
            info["implied_by"] = implied_by
            findings.append({"kind": "redundant", "req": r.id, "implied_by": implied_by, "core": d.core,
                             "message": f"{r.id} 는 {', '.join(implied_by)} (과 도메인)이 이미 함의 — 삭제해도 명세가 달라지지 않음"})
        else:
            info["redundant"] = False
            if d.status == "sat":
                info["distinguishing_witness"] = d.model   # 이 점에서 Rᵢ 만 깨진다 → Rᵢ 가 실제로 무언가를 추가함

    return {
        "logic": "smt",
        "backend": be.name,
        "n_requirements": len(spec.requirements),
        "global": glob,
        "requirements": list(per_req.values()),
        "findings": findings,
        "smt2": smt2,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


audit = check  # 구현-00 호환 별칭


if __name__ == "__main__":  # 간단 자가 시험:  python checker.py spec.json
    import json
    import sys

    doc = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(check(doc, keep_smt2=False), ensure_ascii=False, indent=2))
