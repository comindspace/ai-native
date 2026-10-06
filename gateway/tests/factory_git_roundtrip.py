"""Real Git clone/commit/push through Starlette and the constrained Gateway proxy.

Run separately from dependency-stub unit tests: uv run python tests/factory_git_roundtrip.py
Only temporary repositories and synthetic identities are used.
"""

import base64
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway_mcp.factory_git_client import git_environment
from gateway_mcp.routes import factory_git as route
from gateway_mcp.services import factory_git as service
from gateway_mcp.services import storage_work
from gateway_mcp.services.policy import GatewayActor

WORK = "work-11111111-1111-1111-1111-111111111111"
ACTOR = GatewayActor(subject="test-worker", scopes=("factory:git", "factory:claim"))


def git(*args, env=None, success=True):
    result = subprocess.run(
        ["git", *map(str, args)], env=env, capture_output=True, timeout=30, check=False
    )
    if success and result.returncode:
        raise AssertionError(result.stderr.decode(errors="replace"))
    return result


def main():
    with tempfile.TemporaryDirectory(prefix="factory-git-integration-") as directory:
        root = Path(directory)
        repo, seed, clone = root / "repo.git", root / "seed", root / "worker"
        git("init", "--bare", "--initial-branch=main", repo)
        git("--git-dir", repo, "config", "http.receivepack", "true")
        git("init", "--initial-branch=main", seed)
        git("-C", seed, "config", "user.name", "Integration Test")
        git("-C", seed, "config", "user.email", "test@example.invalid")
        (seed / "README.md").write_text("seed\n", encoding="utf-8")
        git("-C", seed, "add", "README.md")
        git("-C", seed, "commit", "-m", "seed")
        git("-C", seed, "push", repo, "main")
        base_head = git("--git-dir", repo, "rev-parse", "main").stdout
        requests = []

        def upstream(request):
            assert request.url.host == "git.example"
            assert (
                request.headers["authorization"]
                == "Basic "
                + base64.b64encode(b"oauth2:synthetic-upstream-token").decode()
            )
            assert "git-protocol" not in request.headers
            requests.append((request.method, request.url.path))
            body = request.read()
            env = {
                **os.environ,
                "GIT_PROJECT_ROOT": str(root),
                "GIT_HTTP_EXPORT_ALL": "1",
                "REQUEST_METHOD": request.method,
                "PATH_INFO": request.url.path,
                "QUERY_STRING": request.url.query.decode(),
                "CONTENT_TYPE": request.headers.get("content-type", ""),
                "CONTENT_LENGTH": str(len(body)),
                "REMOTE_USER": "test-worker",
                "SERVER_PROTOCOL": "HTTP/1.1",
            }
            result = subprocess.run(
                ["git", "http-backend"],
                check=False,
                input=body,
                env=env,
                capture_output=True,
                timeout=30,
            )
            if result.returncode:
                raise AssertionError("Local Git HTTP backend failed")
            separator = b"\r\n\r\n" if b"\r\n\r\n" in result.stdout else b"\n\n"
            header, content = result.stdout.split(separator, 1)
            headers = dict(line.decode().split(": ", 1) for line in header.splitlines())
            status = int(headers.pop("Status", "200 OK").split()[0])
            return httpx.Response(status, headers=headers, content=content)

        original_client = httpx.AsyncClient

        def client(*args, **kwargs):
            return original_client(
                *args, **kwargs, transport=httpx.MockTransport(upstream)
            )

        class Mcp:
            def custom_route(self, path, methods, **kwargs):
                def register(func):
                    self.route = Route(path, func, methods=methods)
                    return func

                return register

        mcp = Mcp()
        route.register_factory_git_routes(mcp)
        app = Starlette(routes=[mcp.route])
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="error", access_log=False)
        )
        thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        candidate = {
            "work_id": WORK,
            "project_id": "test",
            "project_path": "repo",
            "status": "running",
            "execution_mode": "factory",
            "scope_decision": "within_scope",
            "claimed_by": ACTOR.subject,
            "lease_expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
            "contract": {"metadata": {"gitlab_backend": "https://git.example"}},
        }
        stored = {
            "revision": 1,
            "config": {
                "gitlab_connection_id": "gitlab:test",
                "project_path": "repo",
                "gitlab_web_url": "https://git.example/repo",
                "gitlab_clone_url": "https://git.example/repo.git",
                "default_base_branch": "main",
                "mr_target_branch": "main",
            },
            "readiness": {
                "ready": True,
                "connection_version": 1,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        settings = {
            "username": "oauth2",
            "token": "synthetic-upstream-token",
            "version": 1,
            "base_url": "https://git.example",
            "repositories": ["repo"],
        }
        with (
            patch.object(
                route,
                "request_actor",
                side_effect=lambda r: (
                    ACTOR
                    if r.headers.get("authorization")
                    == "Bearer synthetic-gateway-token"
                    else None
                ),
            ),
            patch.object(route.httpx, "AsyncClient", side_effect=client),
            patch.object(route, "audit_event"),
            patch.object(service, "enabled", return_value=True),
            patch.object(service, "get_work", return_value=candidate),
            patch.object(service, "_require_project_access"),
            patch.object(service.storage_factory, "get_project", return_value=stored),
            patch.object(service.storage_factory, "list_probes", return_value=[]),
            patch.object(
                storage_work,
                "latest_factory_preflight",
                return_value={
                    "actor_subject": ACTOR.subject,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "lease_expires_at": candidate["lease_expires_at"],
                        "ready": True,
                        "project_revision": stored["revision"],
                        "connection_version": 1,
                        "checked_at": stored["readiness"]["checked_at"],
                    },
                },
            ),
            patch.object(service, "connection_settings", return_value=settings),
        ):
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                assert server.started
                url = f"http://127.0.0.1:{port}/factory/git/{WORK}/repo.git"
                env = git_environment(url, "synthetic-gateway-token")
                git("clone", "--depth=1", "--branch", "main", url, clone, env=env)
                git("-C", clone, "config", "user.name", "Integration Test")
                git("-C", clone, "config", "user.email", "test@example.invalid")
                (clone / "feature.txt").write_text("verified\n", encoding="utf-8")
                git("-C", clone, "add", "feature.txt")
                git("-C", clone, "commit", "-m", "worker change")
                git("-C", clone, "push", url, "HEAD:refs/heads/codex/" + WORK, env=env)
                assert (
                    git(
                        "--git-dir", repo, "show", "codex/" + WORK + ":feature.txt"
                    ).stdout.strip()
                    == b"verified"
                )
                count = sum(
                    method == "POST" and path.endswith("receive-pack")
                    for method, path in requests
                )
                denied = git(
                    "-C",
                    clone,
                    "push",
                    url,
                    "HEAD:refs/heads/main",
                    env=env,
                    success=False,
                )
                assert denied.returncode != 0
                assert count == sum(
                    method == "POST" and path.endswith("receive-pack")
                    for method, path in requests
                )
                assert git("--git-dir", repo, "rev-parse", "main").stdout == base_head
                local_config = (clone / ".git" / "config").read_text()
                assert "synthetic-upstream-token" not in local_config
                assert "synthetic-gateway-token" not in local_config
                candidate["status"] = "completed"
                assert (
                    git("-C", clone, "fetch", url, env=env, success=False).returncode
                    != 0
                )
                print(
                    "PASS: real Git clone, commit and work-branch push; main rejected before upstream; completed lease rejected; no stored tokens"
                )
            finally:
                server.should_exit = True
                thread.join(timeout=15)
                sock.close()
                assert not thread.is_alive()


if __name__ == "__main__":
    main()
