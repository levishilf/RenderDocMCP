"""RenderDoc MCP Server"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("renderdoc-mcp")
except PackageNotFoundError:
    __version__ = "dev"
