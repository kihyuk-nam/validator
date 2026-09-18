"""
server/formalizer — 자연어 요구사항 → 형식 명세(JSON) 변환 모듈.  "틀릴 수 있는 곳".

    formalize(logic, domain, requirements, provider="canned", model=None) -> FormalizeResult(spec, provenance)

provider
    canned     입력(도메인 문장 + 요구사항 원문)을 정규화해 sha256 을 만들고 canned/*.json 에서 저장된 번역을 찾는다.
               원문이 한 글자라도 바뀌면 조회가 실패(FormalizeError)하므로 저장된 번역이 다른 원문에 붙는 일이 없다.
    anthropic  Claude API 호출.  ANTHROPIC_API_KEY 가 있을 때만 등록된다.  응답을 checker.validate_spec 으로 검증해
               실패하면 오류를 되돌려 주며 최대 3회 재시도한다.

두 provider 는 같은 시그니처를 구현하고, 결과는 항상 checker.validate_spec 을 통과한 뒤에 반환된다.
"""
from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class FormalizeError(ValueError):
    """형식화 실패 — HTTP 400 (canned 미존재·스키마 위반) 또는 503 (provider 없음) 으로 매핑."""

    def __init__(self, msg: str, status: int = 400, **extra):
        super().__init__(msg)
        self.status = status
        self.extra = extra


@dataclass
class FormalizeResult:
    spec: Dict[str, Any]
    provenance: Dict[str, Any] = field(default_factory=dict)


def normalize_input(logic: str, domain: str, requirements: List[Dict[str, str]]) -> str:
    """입력 정규화 — NFC, 공백 정리, 키 정렬.  이 문자열의 sha256 이 canned 조회 키."""
    def clean(s: str) -> str:
        return " ".join(unicodedata.normalize("NFC", s).split())
    return json.dumps({"logic": logic, "domain": clean(domain),
                       "requirements": [[r["id"], clean(r["text"])] for r in requirements]},
                      sort_keys=True, ensure_ascii=False)


def input_sha(logic: str, domain: str, requirements: List[Dict[str, str]]) -> str:
    return hashlib.sha256(normalize_input(logic, domain, requirements).encode("utf-8")).hexdigest()


def providers() -> List[str]:
    ps = ["canned"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        ps.append("anthropic")
    return ps


def formalize(logic: str, domain: str, requirements: List[Dict[str, str]], *,
              provider: str = "canned", model: Optional[str] = None) -> FormalizeResult:
    if not isinstance(requirements, list) or not requirements or \
       not all(isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("text"), str) for r in requirements):
        raise FormalizeError("requirements 는 [{id, text}] 배열이어야 함")
    if provider == "canned":
        from . import canned
        res = canned.formalize(logic, domain, requirements)
    elif provider == "anthropic":
        if "anthropic" not in providers():
            raise FormalizeError("provider unavailable: ANTHROPIC_API_KEY 가 서버에 없음", status=503)
        from . import anthropic
        res = anthropic.formalize(logic, domain, requirements, model=model)
    else:
        raise FormalizeError(f"unknown provider {provider!r} (available: {providers()})")
    # 어느 provider 든 스키마 검증을 통과한 것만 내보낸다
    import checker
    checker.validate_spec(res.spec)
    res.provenance.setdefault("provider", provider)
    res.provenance["input_sha"] = input_sha(logic, domain, requirements)
    return res
