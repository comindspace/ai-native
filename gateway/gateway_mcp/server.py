from gateway_mcp.mcp_runtime import create_server
from gateway_mcp.routes.admin_access import register_admin_access_routes
from gateway_mcp.routes.admin_audit import register_admin_audit_routes
from gateway_mcp.routes.admin_factory_connections import (
    register_admin_factory_connection_routes,
)
from gateway_mcp.routes.admin_integrations import register_admin_integration_routes
from gateway_mcp.routes.admin_metrics import register_admin_metrics_routes
from gateway_mcp.routes.admin_showcase import register_admin_showcase_routes
from gateway_mcp.routes.admin_telemetry import register_admin_telemetry_routes
from gateway_mcp.routes.admin_user_roles import register_admin_user_role_routes
from gateway_mcp.routes.auth import register_auth_routes
from gateway_mcp.routes.credentials import register_credentials_routes
from gateway_mcp.routes.factory_git import register_factory_git_routes
from gateway_mcp.routes.file_transfers import register_file_transfer_routes
from gateway_mcp.routes.health import register_health_routes
from gateway_mcp.routes.llm_proxy import register_llm_proxy_routes
from gateway_mcp.routes.notifications import register_notification_routes
from gateway_mcp.routes.telemetry import register_telemetry_routes
from gateway_mcp.services.auth import mcp_auth_settings, token_verifier
from gateway_mcp.tools.access import register_access_tools
from gateway_mcp.tools.access_requests import register_access_request_tools
from gateway_mcp.tools.approvals import register_approval_tools
from gateway_mcp.tools.company import register_company_tools
from gateway_mcp.tools.discovery import register_discovery_tools
from gateway_mcp.tools.factory import register_factory_tools
from gateway_mcp.tools.files import register_file_tools
from gateway_mcp.tools.knowledge import register_knowledge_tools
from gateway_mcp.tools.memory import register_memory_tools
from gateway_mcp.tools.notifications import register_notification_tools
from gateway_mcp.tools.privacy import register_privacy_tools
from gateway_mcp.tools.process import register_process_tools
from gateway_mcp.tools.router import register_router_tools
from gateway_mcp.tools.telemetry import register_telemetry_tools
from gateway_mcp.tools.work import register_work_tools


def create_mcp():
    server = create_server(
        name="gateway",
        token_verifier=token_verifier(),
        auth=mcp_auth_settings(),
    )
    register_health_routes(server)
    register_telemetry_routes(server)
    register_auth_routes(server)
    register_credentials_routes(server)
    register_file_transfer_routes(server)
    register_factory_git_routes(server)
    register_llm_proxy_routes(server)
    register_notification_routes(server)
    register_admin_audit_routes(server)
    register_admin_access_routes(server)
    register_admin_user_role_routes(server)
    register_admin_showcase_routes(server)
    register_admin_integration_routes(server)
    register_admin_metrics_routes(server)
    register_admin_factory_connection_routes(server)
    register_admin_telemetry_routes(server)
    register_company_tools(server)
    register_memory_tools(server)
    register_notification_tools(server)
    register_knowledge_tools(server)
    register_process_tools(server)
    register_privacy_tools(server)
    register_factory_tools(server)
    register_file_tools(server)
    register_work_tools(server)
    register_telemetry_tools(server)
    register_discovery_tools(server)
    register_access_tools(server)
    register_access_request_tools(server)
    register_approval_tools(server)
    register_router_tools(server)
    return server


mcp = create_mcp()
