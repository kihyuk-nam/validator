"""
formalizer/anthropic.py — Claude API provider.  표준 라이브러리로 호출 (SDK 불필요).
구현-00 client/example_battery.py 의 formalize_anthropic 을 서버로 옮긴 것.  검증은 checker.validate_spec 으로 서버에서 한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import Dict, List, Optional

from . import FormalizeError, FormalizeResult

PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "smt.txt")
DEFAULT_MODEL = "claude-sonnet-4-5"


def _system_prompt() -> str:
    return open(PROMPT_PATH, encoding="utf-8").read()


def formalize(logic: str, domain: str, requirements: List[Dict[str, str]], *, model: Optional[str] = None,
              retries: int = 3) -> FormalizeResult:
    import checker  # 서버 sys.path 에 server/ 가 있음
    if logic != "smt":
        raise FormalizeError(f"logic {logic!r} 는 아직 지원하지 않음 (smt 만)")
    key = os.environ["ANTHROPIC_API_KEY"]
    model = model or DEFAULT_MODEL
    system = _system_prompt()
    user = "Domain:\n" + domain + "\n\nRequirements:\n" + "\n".join(f"{r['id']}. {r['text']}" for r in requirements)
    messages = [{"role": "user", "content": user}]
    last_err = ""
    for attempt in range(1, retries + 1):
        body = json.dumps({"model": model, "max_tokens": 2048, "system": system, "messages": messages}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST",
                                     headers={"content-type": "application/json", "x-api-key": key,
                                              "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = json.load(resp)
        text = "".join(b.get("text", "") for b in out.get("content", [])).strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        try:
            spec = json.loads(text)
            ids_in = [r["id"] for r in requirements]
            ids_out = [r.get("id") for r in spec.get("requirements", [])]
            if ids_in != ids_out:
                raise ValueError(f"requirement ids mismatch: expected {ids_in}, got {ids_out}")
            checker.validate_spec(spec)          # 스키마·문법 검증 — 실패 메시지를 그대로 되돌려 준다
            return FormalizeResult(spec=spec, provenance={
                "provider": "anthropic", "model": model, "attempts": attempt,
                "prompt_sha": hashlib.sha256(system.encode()).hexdigest()[:16]})
        except Exception as e:
            last_err = str(e)
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"Your output was rejected: {last_err}. Return ONLY the corrected JSON."}]
    raise FormalizeError(f"형식화 {retries}회 실패: {last_err}")
