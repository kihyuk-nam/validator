"""
server/server.py — validator 의 HTTP API.  formalizer(LLM 형식화) + checker(z3 검사) 두 모듈을 묶는다.

    python server.py                # http://0.0.0.0:8000   (PORT 환경변수 우선)
    python server.py --port 9000

엔드포인트
    GET  /healthz     → {"ok", "checker": {"backend", "z3"}, "formalizer": {"providers", "canned"}}
    POST /validate    ← 두 가지 입력 형태
        (a) 자연어:  {"logic": "smt", "domain": "...", "requirements": [{"id","text"}], "provider": "canned"|"anthropic",
                      "model"?: "...", "formalize_only"?: false}
            → formalizer 로 spec 을 만들고, formalize_only 가 아니면 이어서 checker 로 검사
            → {"status": "checked", "spec", "provenance", "result"}   또는   {"status": "awaiting_confirmation", "spec", "provenance"}
        (b) 명세:    {"spec": {...}}  또는 spec 자체 ({"variables", "requirements"} 가 최상위)
            → checker 만  → {"status": "checked", "result"}
        ?smt2=0  이면 result.smt2 생략
    POST /audit       → /validate 와 같은 핸들러 (구현-00 호환 별칭)
    GET  /            → 이 도움말

오류: 400 {"error", "detail"} (입력·스키마·canned 미존재) · 503 (provider 없음) · 500 (내부)
표준 라이브러리만 사용.  LLM 키는 서버 환경변수 ANTHROPIC_API_KEY (없으면 canned provider 만).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checker  # noqa: E402
import formalizer  # noqa: E402
from formalizer import canned as canned_provider  # noqa: E402

HELP = __doc__


def handle_validate(doc, keep_smt2: bool):
    """요청 본문 → (status_code, 응답 dict).  HTTP 를 모르는 순수 함수라 테스트에서 직접 부를 수 있다."""
    if not isinstance(doc, dict):
        return 400, {"error": "spec error", "detail": "최상위는 JSON 객체여야 함"}
    # (b) 명세 모드
    spec = doc.get("spec") if "spec" in doc else (doc if "requirements" in doc and "variables" in doc else None)
    if spec is not None:
        try:
            result = checker.check(spec, keep_smt2=keep_smt2)
        except checker.SpecError as e:
            return 400, {"error": "spec error", "detail": str(e)}
        return 200, {"status": "checked", "result": result}
    # (a) 자연어 모드
    try:
        fr = formalizer.formalize(doc.get("logic", "smt"), doc.get("domain", ""), doc.get("requirements"),
                                  provider=doc.get("provider", "canned"), model=doc.get("model"))
    except formalizer.FormalizeError as e:
        return e.status, {"error": str(e), **e.extra}
    except checker.SpecError as e:
        return 400, {"error": "spec error", "detail": str(e)}
    if doc.get("formalize_only"):
        return 200, {"status": "awaiting_confirmation", "spec": fr.spec, "provenance": fr.provenance}
    result = checker.check(fr.spec, keep_smt2=keep_smt2)
    return 200, {"status": "checked", "spec": fr.spec, "provenance": fr.provenance, "result": result}


class Handler(BaseHTTPRequestHandler):
    server_version = "validator/0.2"

    def _send(self, code: int, obj, ctype="application/json"):
        body = (json.dumps(obj, ensure_ascii=False, indent=1) if ctype.startswith("application/json") else obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/healthz":
            be = checker.default_backend()
            return self._send(200, {"ok": True,
                                    "checker": {"backend": be.name, "z3": checker.HAVE_Z3},
                                    "formalizer": {"providers": formalizer.providers(), "canned": canned_provider.available()},
                                    # 구현-00 호환 필드
                                    "backend": be.name, "z3": checker.HAVE_Z3})
        if path == "/":
            return self._send(200, HELP, ctype="text/plain")
        return self._send(404, {"error": f"no such path: {path}"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/validate", "/audit"):
            return self._send(404, {"error": f"no such path: {u.path}"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            doc = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            return self._send(400, {"error": f"invalid JSON body: {e}"})
        keep = parse_qs(u.query).get("smt2", ["1"])[0] not in ("0", "false")
        try:
            code, obj = handle_validate(doc, keep)
        except Exception as e:  # 솔버·내부 오류
            traceback.print_exc()
            return self._send(500, {"error": "internal error", "detail": repr(e)})
        return self._send(code, obj)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"validator listening on http://{a.host}:{a.port}  checker={checker.default_backend().name}  "
          f"formalizer providers={formalizer.providers()} canned={canned_provider.available()}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
