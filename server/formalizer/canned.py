"""
formalizer/canned.py — 저장된 번역(canned) provider.

canned/*.json 형식:
    {"input_sha": "<sha256>", "logic": "smt", "provenance": {...}, "spec": {...}, "notes": {...}}
서버 시작 시 디렉터리를 모두 읽어 input_sha → 파일 표를 만든다.  파일 이름은 사람용이고 조회 키가 아니다.
같은 입력을 다시 저장하려면 tools 없이 `python -m formalizer.canned add <name> <input.json> <spec.json>` 으로 만든다.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List

from . import FormalizeError, FormalizeResult, input_sha

CANNED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "canned")
_TABLE: Dict[str, Dict[str, Any]] = {}


def _load() -> Dict[str, Dict[str, Any]]:
    if not _TABLE:
        for p in sorted(glob.glob(os.path.join(CANNED_DIR, "*.json"))):
            d = json.load(open(p, encoding="utf-8"))
            d["_file"] = os.path.basename(p)
            _TABLE[d["input_sha"]] = d
    return _TABLE


def available() -> List[str]:
    return [d["_file"].rsplit(".json", 1)[0] for d in _load().values()]


def formalize(logic: str, domain: str, requirements: List[Dict[str, str]]) -> FormalizeResult:
    sha = input_sha(logic, domain, requirements)
    d = _load().get(sha)
    if d is None:
        raise FormalizeError("no canned translation for this input", input_sha=sha, available=available(),
                             hint="원문이 저장본과 한 글자라도 다르면 조회에 실패한다. provider=anthropic 을 쓰거나 canned 파일을 추가할 것")
    prov = dict(d.get("provenance", {}))
    prov["canned_file"] = d["_file"]
    return FormalizeResult(spec=d["spec"], provenance=prov)


if __name__ == "__main__":  # python -m formalizer.canned add <name> <input.json> <spec.json>
    import sys
    if len(sys.argv) == 5 and sys.argv[1] == "add":
        name, inp, spec = sys.argv[2:]
        i = json.load(open(inp, encoding="utf-8"))
        out = {"input_sha": input_sha(i["logic"], i["domain"], i["requirements"]), "logic": i["logic"],
               "provenance": {"provider": "canned", "model": "manual"}, "spec": json.load(open(spec, encoding="utf-8"))}
        path = os.path.join(CANNED_DIR, name + ".json")
        json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("wrote", path, out["input_sha"])
    else:
        print(__doc__)
