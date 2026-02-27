# RenderDoc MCP Server

作为 RenderDoc UI 扩展运行的 MCP 服务器。AI 助手可以访问 RenderDoc 的捕获数据，辅助图形调试。

## 架构

```
Claude/AI Client (stdio)
        │
        ▼
MCP Server Process (Python + FastMCP 2.0)
        │ File-based IPC (%TEMP%/renderdoc_mcp/)
        ▼
RenderDoc Process (Extension)
```

由于 RenderDoc 内置的 Python 没有 socket 模块，因此使用基于文件的 IPC 进行通信。

## 设置

### 1. 安装 RenderDoc 扩展

```bash
python scripts/install_extension.py
```

扩展会安装到 `%APPDATA%\qrenderdoc\extensions\renderdoc_mcp_bridge`。

### 2. 在 RenderDoc 中启用扩展

1. 启动 RenderDoc
2. Tools > Manage Extensions
3. 启用 "RenderDoc MCP Bridge"

### 3. 安装 MCP 服务器

```bash
uv tool install
uv tool update-shell  # 添加到 PATH
```

重启 Shell 后即可使用 `renderdoc-mcp` 命令。

> **Note**: 使用 `uv tool install --editable .` 可以使源码修改立即生效（开发时很方便）。
> 作为稳定版安装时请使用 `uv tool install .`。

#### 更新MCP
以CodeBuddy为例
- 在配置界面-MCP-自定义MCP-renderdoc中：关闭该mcp
- 运行`uv tool install --editable .`
- 在配置界面-MCP-自定义MCP-renderdoc中：开启该mcp

### 4. MCP 客户端配置

#### Claude Desktop

添加到 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "renderdoc": {
      "command": "renderdoc-mcp"
    }
  }
}
```

#### Claude Code

添加到 `.mcp.json`：

```json
{
  "mcpServers": {
    "renderdoc": {
      "command": "renderdoc-mcp"
    }
  }
}
```

## 使用方法

1. 启动 RenderDoc，打开捕获文件 (.rdc)
2. 通过 MCP 客户端（Claude 等）访问 RenderDoc 的数据

## MCP 工具列表

| 工具 | 说明 |
|--------|------|
| `get_capture_status` | 检查捕获的加载状态 |
| `get_draw_calls` | 以层级结构获取 Draw Call 列表 |
| `get_draw_call_details` | 获取特定 Draw Call 的详细信息 |
| `get_shader_info` | 获取着色器源码和常量缓冲区的值 |
| `get_buffer_contents` | 获取缓冲区内容 (Base64) |
| `get_texture_info` | 获取纹理元数据 |
| `get_texture_data` | 获取纹理像素数据 (Base64) |
| `get_pipeline_state` | 获取管线状态 |

## 使用示例

### 获取 Draw Call 列表

```
get_draw_calls(include_children=true)
```

### 获取着色器信息

```
get_shader_info(event_id=123, stage="pixel")
```

### 获取管线状态

```
get_pipeline_state(event_id=123)
```

### 获取纹理数据

```
# 获取 2D 纹理的 mip 0
get_texture_data(resource_id="ResourceId::123")

# 获取特定 mip 级别
get_texture_data(resource_id="ResourceId::123", mip=2)

# 获取立方体贴图的特定面 (0=X+, 1=X-, 2=Y+, 3=Y-, 4=Z+, 5=Z-)
get_texture_data(resource_id="ResourceId::456", slice=3)

# 获取 3D 纹理的特定深度切片
get_texture_data(resource_id="ResourceId::789", depth_slice=5)
```

### 部分获取缓冲区数据

```
# 获取整个缓冲区
get_buffer_contents(resource_id="ResourceId::123")

# 从偏移 256 处获取 512 字节
get_buffer_contents(resource_id="ResourceId::123", offset=256, length=512)
```

## 要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- RenderDoc 1.20+

> **Note**: 仅在 Windows + DirectX 11 环境下进行了测试验证。
> 在 Linux/macOS + Vulkan/OpenGL 环境下也可能可以运行，但尚未验证。

## 许可证

MIT
