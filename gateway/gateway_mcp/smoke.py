import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

LEGACY_PROTOCOL_VERSION = "2025-06-18"
MODERN_PROTOCOL_VERSION = "2026-07-28"


@dataclass
class SmokeResult:
    name: str
    ok: bool
    detail: str


def run_smoke(
    base_url: str,
    *,
    token: str = "",
    timeout: int = 20,
    protocol_mode: str = "legacy",
) -> list[SmokeResult]:
    base = base_url.rstrip("/")
    results = [
        _check_json("healthz", f"{base}/healthz", timeout=timeout, required_keys=["ok", "service"]),
        _check_json(
            "oauth_authorization_server",
            f"{base}/.well-known/oauth-authorization-server",
            timeout=timeout,
            required_keys=["issuer", "authorization_endpoint", "token_endpoint", "registration_endpoint"],
        ),
        _check_json(
            "oauth_protected_resource",
            f"{base}/.well-known/oauth-protected-resource/mcp",
            timeout=timeout,
            required_keys=["resource", "authorization_servers", "scopes_supported"],
        ),
        _check_client_registration(base, timeout=timeout),
    ]
    if token and protocol_mode in {"legacy", "both"}:
        results.extend(_check_mcp_legacy(base, token=token, timeout=timeout))
    if token and protocol_mode in {"modern", "both"}:
        results.extend(_check_mcp_modern(base, token=token, timeout=timeout))
    return results


def print_results(results: list[SmokeResult]) -> None:
    for result in results:
        status = "ok" if result.ok else "fail"
        print(f"{status}\t{result.name}\t{result.detail}")


def exit_code(results: list[SmokeResult]) -> int:
    return 0 if all(result.ok for result in results) else 1


def _check_json(name: str, url: str, *, timeout: int, required_keys: list[str]) -> SmokeResult:
    try:
        status, _, body = _request("GET", url, timeout=timeout)
        data = json.loads(body)
        missing = [key for key in required_keys if key not in data]
        if status != 200:
            return SmokeResult(name, False, f"HTTP {status}")
        if missing:
            return SmokeResult(name, False, f"missing keys: {', '.join(missing)}")
        return SmokeResult(name, True, _short_json(data))
    except Exception as exc:
        return SmokeResult(name, False, str(exc))


def _check_client_registration(base: str, *, timeout: int) -> SmokeResult:
    try:
        payload = {
            "client_name": "GatewayMCP smoke",
            "redirect_uris": ["http://127.0.0.1:5555/callback"],
        }
        status, _, body = _request(
            "POST",
            f"{base}/oauth/register",
            json_payload=payload,
            timeout=timeout,
        )
        data = json.loads(body)
        if status != 201:
            return SmokeResult("oauth_register", False, f"HTTP {status}: {_short_text(body)}")
        if data.get("token_endpoint_auth_method") != "none" or not str(data.get("client_id", "")).startswith("gateway-client."):
            return SmokeResult("oauth_register", False, "unexpected client registration response")
        return SmokeResult("oauth_register", True, "public PKCE client registered")
    except Exception as exc:
        return SmokeResult("oauth_register", False, str(exc))


def _check_mcp_legacy(base: str, *, token: str, timeout: int) -> list[SmokeResult]:
    mcp_url = f"{base}/mcp"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    results: list[SmokeResult] = []
    session_id = ""
    try:
        status, response_headers, body = _request(
            "POST",
            mcp_url,
            json_payload={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LEGACY_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "gateway-smoke", "version": "0.1.0"},
                },
            },
            headers=headers,
            timeout=timeout,
        )
        data = _decode_mcp_body(body)
        session_id = response_headers.get("mcp-session-id", "")
        if status not in {200, 202} or data.get("error"):
            return [SmokeResult("mcp_initialize", False, f"HTTP {status}: {_short_text(body)}")]
        results.append(SmokeResult("mcp_initialize", True, f"session={session_id or 'stateless'}"))
    except Exception as exc:
        return [SmokeResult("mcp_initialize", False, str(exc))]

    call_headers = dict(headers)
    if session_id:
        call_headers["mcp-session-id"] = session_id
    try:
        _request(
            "POST",
            mcp_url,
            json_payload={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=call_headers,
            timeout=timeout,
        )
    except Exception:
        pass

    results.append(
        _check_mcp_call(
            "mcp_tools_list",
            mcp_url,
            headers=call_headers,
            payload={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            timeout=timeout,
            expected_tool="gateway_search_tools",
        )
    )
    results.append(
        _check_mcp_call(
            "gateway_search_tools",
            mcp_url,
            headers=call_headers,
            payload={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "gateway_search_tools", "arguments": {"query": "yonote"}},
            },
            timeout=timeout,
            expected_text="yonote.documents.search",
        )
    )
    return results


def _check_mcp_modern(base: str, *, token: str, timeout: int) -> list[SmokeResult]:
    mcp_url = f"{base}/mcp"
    request_meta = {
        "io.modelcontextprotocol/protocolVersion": MODERN_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "gateway-smoke", "version": "0.2.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    common_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
    }
    discover = _check_mcp_call(
        "mcp_server_discover_modern",
        mcp_url,
        headers={**common_headers, "Mcp-Method": "server/discover"},
        payload={
            "jsonrpc": "2.0",
            "id": "discover-1",
            "method": "server/discover",
            "params": {"_meta": request_meta},
        },
        timeout=timeout,
        expected_protocol=MODERN_PROTOCOL_VERSION,
    )
    if not discover.ok:
        return [discover]

    tools = _check_mcp_call(
        "mcp_tools_list_modern",
        mcp_url,
        headers={**common_headers, "Mcp-Method": "tools/list"},
        payload={
            "jsonrpc": "2.0",
            "id": "tools-1",
            "method": "tools/list",
            "params": {"_meta": request_meta},
        },
        timeout=timeout,
        expected_tool="gateway_search_tools",
    )
    return [discover, tools]


def _check_mcp_call(
    name: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    expected_tool: str = "",
    expected_text: str = "",
    expected_protocol: str = "",
) -> SmokeResult:
    try:
        status, _, body = _request("POST", url, json_payload=payload, headers=headers, timeout=timeout)
        data = _decode_mcp_body(body)
        if status not in {200, 202} or data.get("error"):
            return SmokeResult(name, False, f"HTTP {status}: {_short_text(body)}")
        if expected_protocol:
            versions = data.get("result", {}).get("supportedVersions", [])
            if expected_protocol not in versions:
                return SmokeResult(name, False, f"{expected_protocol} not advertised")
            return SmokeResult(name, True, f"supports {expected_protocol}")
        if expected_tool:
            tools = data.get("result", {}).get("tools", [])
            if expected_tool not in {tool.get("name") for tool in tools if isinstance(tool, dict)}:
                return SmokeResult(name, False, f"{expected_tool} not listed")
            return SmokeResult(name, True, f"{len(tools)} tools")
        if expected_text and expected_text not in body:
            return SmokeResult(name, False, f"{expected_text} not found")
        return SmokeResult(name, True, "response ok")
    except Exception as exc:
        return SmokeResult(name, False, str(exc))


def _request(
    method: str,
    url: str,
    *,
    json_payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int,
) -> tuple[int, dict[str, str], str]:
    data = None
    request_headers = dict(headers or {})
    if json_payload is not None:
        data = json.dumps(json_payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, dict(response.headers.items()), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, dict(exc.headers.items()), body


def _decode_mcp_body(body: str) -> dict[str, Any]:
    stripped = body.strip()
    if not stripped:
        return {}
    if stripped.startswith("event:") or "\ndata:" in stripped:
        for line in stripped.splitlines():
            if line.startswith("data:"):
                return json.loads(line.removeprefix("data:").strip())
        return {}
    return json.loads(stripped)


def _short_json(data: dict[str, Any]) -> str:
    compact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return _short_text(compact)


def _short_text(value: str, *, limit: int = 180) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check a deployed GatewayMCP instance")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--protocol-mode", choices=["legacy", "modern", "both"], default="legacy")
    args = parser.parse_args(argv)
    results = run_smoke(
        args.base_url,
        token=args.token,
        timeout=args.timeout,
        protocol_mode=args.protocol_mode,
    )
    print_results(results)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
