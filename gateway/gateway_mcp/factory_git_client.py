"""Worker-side Git wrapper. Only Gateway credentials enter the Git process."""

import argparse
import os
import subprocess
from urllib.parse import urlsplit

from gateway_mcp.services.factory_git import WORK_ID


def git_environment(url: str, token: str) -> dict[str, str]:
    if not token or any(ord(char) < 33 for char in token):
        raise ValueError("GATEWAY_MCP_TOKEN is required")
    allowed = {
        "path",
        "systemroot",
        "windir",
        "temp",
        "tmp",
        "home",
        "userprofile",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "ssl_cert_file",
        "ssl_cert_dir",
    }
    env = {key: value for key, value in os.environ.items() if key.casefold() in allowed}
    settings = {
        "credential.helper": "",
        "http.followRedirects": "false",
        f"http.{url}/.extraHeader": "Authorization: Bearer " + token,
        "protocol.version": "0",
        "protocol.file.allow": "never",
        "core.hooksPath": os.devnull,
    }
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_COUNT=str(len(settings)),
        GCM_INTERACTIVE="Never",
    )
    for index, (key, value) in enumerate(settings.items()):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("action", choices=["clone", "fetch", "push"])
    args = parser.parse_args()
    parsed = urlsplit(args.gateway)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not WORK_ID.fullmatch(args.work_id)
    ):
        parser.error("Use a credential-free HTTPS Gateway origin and a valid work_id")
    if args.base_branch.startswith("-"):
        parser.error("Invalid base branch")
    url = args.gateway.rstrip("/") + f"/factory/git/{args.work_id}/repo.git"
    try:
        env = git_environment(url, os.getenv("GATEWAY_MCP_TOKEN", ""))
    except ValueError:
        parser.error("GATEWAY_MCP_TOKEN is required in the worker environment")
    if args.action == "clone":
        command = [
            "git",
            "clone",
            "--depth=1",
            "--single-branch",
            "--no-tags",
            "--branch",
            args.base_branch,
            "--",
            url,
            args.directory,
        ]
    elif args.action == "fetch":
        command = [
            "git",
            "-C",
            args.directory,
            "fetch",
            "--no-tags",
            "--",
            url,
            args.base_branch,
        ]
    else:
        command = [
            "git",
            "-C",
            args.directory,
            "push",
            "--porcelain",
            "--",
            url,
            f"HEAD:refs/heads/codex/{args.work_id}",
        ]
    raise SystemExit(subprocess.run(command, env=env, check=False).returncode)


if __name__ == "__main__":
    main()
