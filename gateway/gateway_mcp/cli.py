import argparse
import json
import os

from gateway_mcp.mcp_runtime import run_server
from gateway_mcp.services.migrations import check_current, migrate_up
from gateway_mcp.smoke import main as smoke_main


def main() -> None:
    parser = argparse.ArgumentParser(description="GatewayMCP")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("GATEWAY_TRANSPORT", "stdio"),
    )
    subparsers = parser.add_subparsers(dest="command")
    migrate_parser = subparsers.add_parser(
        "migrate", help="Manage GatewayMCP database migrations"
    )
    migrate_parser.add_argument("action", choices=["up", "status"])
    smoke_parser = subparsers.add_parser(
        "smoke", help="Smoke-check a deployed GatewayMCP instance"
    )
    smoke_parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    smoke_parser.add_argument("--token", default="")
    smoke_parser.add_argument("--timeout", type=int, default=20)
    smoke_parser.add_argument(
        "--protocol-mode", choices=["legacy", "modern", "both"], default="legacy"
    )
    notification_parser = subparsers.add_parser(
        "notifications-worker", help="Deliver employee Web Push notifications"
    )
    notification_parser.add_argument("--once", action="store_true")
    notification_parser.add_argument("--poll-seconds", type=float, default=None)
    notification_parser.add_argument("--batch-size", type=int, default=None)
    connection_parser = subparsers.add_parser("factory-connection", help="Provision an encrypted Factory GitLab connection locally")
    connection_parser.add_argument("--id", required=True)
    connection_parser.add_argument("--api-url", required=True)
    connection_parser.add_argument("--username", default="oauth2")
    args = parser.parse_args()
    if args.command == "factory-connection":
        from getpass import getpass
        from gateway_mcp.services.factory_readiness import provision_connection

        provision_connection(args.id, args.api_url, args.username, getpass("GitLab token: "))
        print(json.dumps({"ok": True, "configured": True}))
        return
    if args.command == "migrate":
        result = migrate_up() if args.action == "up" else check_current()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "smoke":
        raise SystemExit(
            smoke_main(
                [
                    "--base-url",
                    args.base_url,
                    "--token",
                    args.token,
                    "--timeout",
                    str(args.timeout),
                    "--protocol-mode",
                    args.protocol_mode,
                ]
            )
        )
    if args.command == "notifications-worker":
        from gateway_mcp.services.notification_worker import run_forever, run_once

        if args.once:
            result = run_once(batch_size=args.batch_size or 25)
            print(json.dumps(result, ensure_ascii=False))
            return
        run_forever(
            poll_seconds=args.poll_seconds,
            batch_size=args.batch_size,
        )
        return
    from gateway_mcp.server import mcp

    run_server(mcp, transport=args.transport)
