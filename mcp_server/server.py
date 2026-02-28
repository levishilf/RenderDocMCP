"""
RenderDoc MCP Server
FastMCP 2.0 server providing access to RenderDoc capture data.
"""

from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from . import __version__
from .bridge.client import RenderDocBridge
from .config import settings

# Initialize FastMCP server
mcp = FastMCP(
    name="RenderDoc MCP Server",
)

# RenderDoc bridge client
bridge = RenderDocBridge(host=settings.renderdoc_host, port=settings.renderdoc_port)


@mcp.tool
def get_version() -> dict:
    """
    Get the current version of the RenderDoc MCP server.
    """
    return {"version": __version__}


@mcp.tool
def get_capture_status() -> dict:
    """
    Check if a capture is currently loaded in RenderDoc.
    Returns the capture status and API type if loaded.
    """
    return bridge.call("get_capture_status")


@mcp.tool
def get_draw_calls(
    include_children: bool = True,
    marker_filter: str | None = None,
    exclude_markers: list[str] | None = None,
    event_id_min: int | None = None,
    event_id_max: int | None = None,
    only_actions: bool = False,
    flags_filter: list[str] | None = None,
) -> dict:
    """
    Get the list of all draw calls and actions in the current capture.

    Args:
        include_children: Include child actions in the hierarchy (default: True)
        marker_filter: Only include actions under markers containing this string (partial match)
        exclude_markers: Exclude actions under markers containing these strings (list of partial matches)
        event_id_min: Only include actions with event_id >= this value
        event_id_max: Only include actions with event_id <= this value
        only_actions: If True, exclude marker actions (PushMarker/PopMarker/SetMarker)
        flags_filter: Only include actions with these flags (list of flag names, e.g. ["Drawcall", "Dispatch"])

    Returns a hierarchical tree of actions including markers, draw calls,
    dispatches, and other GPU events.
    """
    params: dict[str, object] = {"include_children": include_children}
    if marker_filter is not None:
        params["marker_filter"] = marker_filter
    if exclude_markers is not None:
        params["exclude_markers"] = exclude_markers
    if event_id_min is not None:
        params["event_id_min"] = event_id_min
    if event_id_max is not None:
        params["event_id_max"] = event_id_max
    if only_actions:
        params["only_actions"] = only_actions
    if flags_filter is not None:
        params["flags_filter"] = flags_filter
    return bridge.call("get_draw_calls", params)


@mcp.tool
def get_frame_summary() -> dict:
    """
    Get a summary of the current capture frame.

    Returns statistics about the frame including:
    - API type (D3D11, D3D12, Vulkan, etc.)
    - Total action count
    - Statistics: draw calls, dispatches, clears, copies, presents, markers
    - Top-level markers with event IDs and child counts
    - Resource counts: textures, buffers
    """
    return bridge.call("get_frame_summary")


@mcp.tool
def find_draws_by_shader(
    shader_name: str,
    stage: Literal["vertex", "hull", "domain", "geometry", "pixel", "compute"]
    | None = None,
) -> dict:
    """
    Find all draw calls using a shader with the given name (partial match).

    Args:
        shader_name: Partial name to search for in shader names or entry points
        stage: Optional shader stage to search (if not specified, searches all stages)

    Returns a list of matching draw calls with event IDs and match reasons.
    """
    params: dict[str, object] = {"shader_name": shader_name}
    if stage is not None:
        params["stage"] = stage
    return bridge.call("find_draws_by_shader", params)


@mcp.tool
def find_draws_by_texture(texture_name: str) -> dict:
    """
    Find all draw calls using a texture with the given name (partial match).

    Args:
        texture_name: Partial name to search for in texture resource names

    Returns a list of matching draw calls with event IDs and match reasons.
    Searches SRVs, UAVs, and render targets.
    """
    return bridge.call("find_draws_by_texture", {"texture_name": texture_name})


@mcp.tool
def find_draws_by_resource(resource_id: str) -> dict:
    """
    Find all draw calls using a specific resource ID (exact match).

    Args:
        resource_id: Resource ID to search for (e.g. "ResourceId::12345" or "12345")

    Returns a list of matching draw calls with event IDs and match reasons.
    Searches shaders, SRVs, UAVs, render targets, and depth targets.
    """
    return bridge.call("find_draws_by_resource", {"resource_id": resource_id})


@mcp.tool
def get_draw_call_details(event_id: int) -> dict:
    """
    Get detailed information about a specific draw call.

    Args:
        event_id: The event ID of the draw call to inspect

    Includes vertex/index counts, resource outputs, and other metadata.
    """
    return bridge.call("get_draw_call_details", {"event_id": event_id})


@mcp.tool
def get_action_timings(
    event_ids: list[int] | None = None,
    marker_filter: str | None = None,
    exclude_markers: list[str] | None = None,
) -> dict:
    """
    Get GPU timing information for actions (draw calls, dispatches, etc.).

    Args:
        event_ids: Optional list of specific event IDs to get timings for.
                   If not specified, returns timings for all actions.
        marker_filter: Only include actions under markers containing this string (partial match).
        exclude_markers: Exclude actions under markers containing these strings.

    Returns timing data including:
    - available: Whether GPU timing counters are supported
    - unit: Time unit (typically "seconds")
    - timings: List of {event_id, name, duration_seconds, duration_ms}
    - total_duration_ms: Sum of all durations
    - count: Number of timing entries

    Note: GPU timing counters may not be available on all hardware/drivers.
    """
    params: dict[str, object] = {}
    if event_ids is not None:
        params["event_ids"] = event_ids
    if marker_filter is not None:
        params["marker_filter"] = marker_filter
    if exclude_markers is not None:
        params["exclude_markers"] = exclude_markers
    return bridge.call("get_action_timings", params)


@mcp.tool
def get_shader_info(
    event_id: int,
    stage: Literal["vertex", "hull", "domain", "geometry", "pixel", "compute"],
) -> dict:
    """
    Get shader information for a specific stage at a given event.

    Args:
        event_id: The event ID to inspect the shader at
        stage: The shader stage (vertex, hull, domain, geometry, pixel, compute)

    Returns shader disassembly (using the best available readable target),
    constant buffer values, resource bindings, and the list of available
    disassembly targets.
    """
    return bridge.call("get_shader_info", {"event_id": event_id, "stage": stage})


@mcp.tool
def get_shader_source(
    event_id: int,
    stage: Literal["vertex", "hull", "domain", "geometry", "pixel", "compute"],
    output_dir: str | None = None,
    target: str | None = None,
) -> dict:
    """
    Get shader source code by saving it to a local file and returning the file path.

    The shader source is saved to disk so AI clients can read it on demand without
    the source being truncated in the tool response. This is faster because only
    file metadata is returned, not the full shader text.

    For mobile captures (Vulkan/OpenGL ES), shaders are typically cross-compiled
    from SPIR-V back to readable GLSL.

    IMPORTANT for AI clients (VSCode / Rider / Claude):
    After calling this tool, display a clickable file link in the chat response
    so users can navigate directly to the shader file. Use the file_path from
    the result to construct a markdown link, for example:
      - VSCode:  [shader.glsl](file_path)
      - Rider:   [shader.glsl](file_path)
    where file_path uses forward slashes (e.g. C:/path/to/shader.glsl).

    Args:
        event_id: The event ID to inspect the shader at
        stage: The shader stage (vertex, hull, domain, geometry, pixel, compute)
        output_dir: Directory to save the file.
                    Recommended: use a "renderdoc/<capture_name>" folder under the
                    AI client's project root.
                    Defaults to "renderdoc/<capture_name>/" in the current working
                    directory, where <capture_name> is derived from the currently
                    loaded RenderDoc capture filename.
        target: Optional specific disassembly target name (e.g. "GLSL", "SPIR-V").
                If not specified, automatically picks the most readable target.

    Returns:
        - file_path: Absolute path to the saved shader file (read it when needed)
        - file_link: Markdown-formatted clickable link for display in chat
        - file_size: Size in bytes
        - line_count: Number of lines in the shader
        - stage: Shader stage
        - target: Which disassembly target was used
        - available_targets: All disassembly targets the shader supports
        - entry_point: Shader entry point name
        - resource_id: Shader resource ID
    """
    params: dict[str, object] = {"event_id": event_id, "stage": stage}
    if target is not None:
        params["target"] = target
    result = bridge.call("get_shader_source", params)

    source_code = result.get("source_code", "")
    if not source_code:
        return {
            "error": "No shader source code available",
            "details": result.get("error", "Unknown error"),
            "available_targets": result.get("available_targets", []),
        }

    # Determine file extension based on target/encoding
    used_target = result.get("target", "unknown").lower()
    if "glsl" in used_target or "embedded" in used_target:
        ext = ".glsl"
    elif "hlsl" in used_target:
        ext = ".hlsl"
    elif "spir" in used_target:
        ext = ".spvasm"
    else:
        ext = ".txt"

    # Build filename
    entry_point = result.get("entry_point", "")
    if entry_point:
        filename = "shader_eid%d_%s_%s%s" % (event_id, stage, entry_point, ext)
    else:
        filename = "shader_eid%d_%s%s" % (event_id, stage, ext)

    # Sanitize filename
    filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)

    # Determine output directory
    if output_dir:
        save_dir = Path(output_dir)
    else:
        # Default: renderdoc/<capture_name>/ under current working directory
        save_dir = Path.cwd() / "renderdoc"
        try:
            status = bridge.call("get_capture_status")
            capture_filename = status.get("filename", "")
            if capture_filename:
                capture_name = Path(capture_filename).stem
                capture_name = "".join(
                    c if c.isalnum() or c in "._- " else "_" for c in capture_name
                ).strip()
                if capture_name:
                    save_dir = save_dir / capture_name
        except Exception:
            pass

    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / filename

    # Write file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(source_code)

    resolved_path = str(file_path.resolve())
    # Build a clickable file link for AI chat display (use forward slashes for URI)
    file_uri = resolved_path.replace("\\", "/")
    file_link = "[%s](%s)" % (filename, file_uri)

    return {
        "file_path": resolved_path,
        "file_link": file_link,
        "file_size": file_path.stat().st_size,
        "line_count": source_code.count("\n") + 1,
        "stage": stage,
        "target": result.get("target", "unknown"),
        "available_targets": result.get("available_targets", []),
        "entry_point": entry_point,
        "resource_id": result.get("resource_id", ""),
    }


@mcp.tool
def get_buffer_contents(
    resource_id: str,
    offset: int = 0,
    length: int = 0,
) -> dict:
    """
    Read the contents of a buffer resource.

    Args:
        resource_id: The resource ID of the buffer to read
        offset: Byte offset to start reading from (default: 0)
        length: Number of bytes to read, 0 for entire buffer (default: 0)

    Returns buffer data as base64-encoded bytes along with metadata.
    """
    return bridge.call(
        "get_buffer_contents",
        {"resource_id": resource_id, "offset": offset, "length": length},
    )


@mcp.tool
def get_texture_info(resource_id: str) -> dict:
    """
    Get metadata about a texture resource.

    Args:
        resource_id: The resource ID of the texture

    Includes dimensions, format, mip levels, and other properties.
    """
    return bridge.call("get_texture_info", {"resource_id": resource_id})


@mcp.tool
def get_texture_data(
    resource_id: str,
    mip: int = 0,
    slice: int = 0,
    sample: int = 0,
    depth_slice: int | None = None,
) -> dict:
    """
    Read the pixel data of a texture resource.

    Args:
        resource_id: The resource ID of the texture to read
        mip: Mip level to retrieve (default: 0)
        slice: Array slice or cube face index (default: 0)
               For cube maps: 0=X+, 1=X-, 2=Y+, 3=Y-, 4=Z+, 5=Z-
        sample: MSAA sample index (default: 0)
        depth_slice: For 3D textures only, extract a specific depth slice (default: None = full volume)
                     When specified, returns only the 2D slice at that depth index

    Returns texture pixel data as base64-encoded bytes along with metadata
    including dimensions at the requested mip level and format information.
    """
    params = {"resource_id": resource_id, "mip": mip, "slice": slice, "sample": sample}
    if depth_slice is not None:
        params["depth_slice"] = depth_slice
    return bridge.call("get_texture_data", params)


@mcp.tool
def get_pipeline_state(event_id: int) -> dict:
    """
    Get the full graphics pipeline state at a specific event.

    Args:
        event_id: The event ID to get pipeline state at

    Returns detailed pipeline state including:
    - Bound shaders with entry points for each stage
    - Shader resources (SRVs): textures and buffers with dimensions, format, slot, name
    - UAVs (RWTextures/RWBuffers): resource details with dimensions and format
    - Samplers: addressing modes, filter settings, LOD parameters
    - Constant buffers: slot, size, variable count
    - Render targets and depth target
    - Viewports and input assembly state
    """
    return bridge.call("get_pipeline_state", {"event_id": event_id})


@mcp.tool
def list_captures(directory: str) -> dict:
    """
    List all RenderDoc capture files (.rdc) in the specified directory.

    Args:
        directory: The directory path to search for capture files

    Returns a list of capture files with their metadata including:
    - filename: The capture file name
    - path: Full path to the file
    - size_bytes: File size in bytes
    - modified_time: Last modified timestamp (ISO format)
    """
    return bridge.call("list_captures", {"directory": directory})


@mcp.tool
def open_capture(capture_path: str) -> dict:
    """
    Open a RenderDoc capture file (.rdc).

    Args:
        capture_path: Full path to the capture file to open

    Returns success status and information about the opened capture.
    Note: This will close any currently open capture.
    """
    return bridge.call("open_capture", {"capture_path": capture_path})


def main():
    """Run the MCP server"""
    import sys

    print(f"当前 renderdoc-mcp 版本为 {__version__}", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
