import os
from mcp.server.fastmcp import FastMCP
from mcp_server.tools.postgres import search_tasks, get_task_by_id, create_task, update_task_status
from mcp_server.tools.jira import sync_task_to_jira
from mcp_server.tools.calendar import check_owner_availability
from mcp_server.tools.report import generate_report

port = int(os.getenv("MCP_SERVER_PORT", "8001"))
mcp = FastMCP("task-planner", host="0.0.0.0", port=port)

mcp.tool()(search_tasks)
mcp.tool()(get_task_by_id)
mcp.tool()(create_task)
mcp.tool()(update_task_status)
mcp.tool()(sync_task_to_jira)
mcp.tool()(check_owner_availability)
mcp.tool()(generate_report)

if __name__ == "__main__":
    mcp.run(transport="sse")
