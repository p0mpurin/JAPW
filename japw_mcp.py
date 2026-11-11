"""Start the JAPW MCP server from any working directory: python path\\to\\JAPW\\japw_mcp.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from japw.mcp_server import main  # noqa: E402

main()
