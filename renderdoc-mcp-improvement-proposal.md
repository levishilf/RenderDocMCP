# RenderDoc MCP 改进提案

## 背景

在 Unity 项目中分析 RenderDoc 捕获时，存在以下问题：

1. **UI 噪声问题**：从 Unity Editor 捕获时，会包含大量 `GUI.Repaint` 和 `UIR.DrawChain` 等 Editor UI 绘制，导致难以找到实际的游戏绘制（`Camera.Render` 下）
2. **响应大小问题**：`get_draw_calls(include_children=true)` 的结果超过 70KB，对 LLM 上下文造成压力
3. **搜索低效问题**：要找到使用特定着色器或纹理的 Draw Call，需要逐一检查所有 Draw Call

## 改进提案

### 1. 标记过滤（优先级：高）

仅获取特定标记下的内容，或排除特定标记的功能。

```python
get_draw_calls(
    include_children=True,
    marker_filter="Camera.Render",  # 仅获取此标记下的内容
    exclude_markers=["GUI.Repaint", "UIR.DrawChain", "UGUI.Rendering"]
)
```

**用例**：
- 从 Unity Editor 捕获中仅提取游戏绘制
- 仅调查特定渲染通道（Shadows、PostProcess 等）

**预期效果**：
- 将响应大小缩减至 10-20%
- 控制在 LLM 可直接解析的大小范围内

---

### 2. event_id 范围指定（优先级：高）

仅获取特定 event_id 范围的功能。

```python
get_draw_calls(
    event_id_min=7372,
    event_id_max=7600,
    include_children=True
)
```

**用例**：
- 当已知 `Camera.Render` 的 event_id 时，仅获取其周围内容
- 详细调查有问题的 Draw Call 周围

**预期效果**：
- 仅快速获取所需部分
- 支持逐步探索

---

### 3. 通过着色器/纹理/资源反向搜索（优先级：中）

搜索使用特定资源的 Draw Call 的功能。

```python
# 按着色器名称搜索（部分匹配）
find_draws_by_shader(shader_name="Toon")

# 按纹理名称搜索（部分匹配）
find_draws_by_texture(texture_name="CharacterSkin")

# 按资源 ID 搜索（精确匹配）
find_draws_by_resource(resource_id="ResourceId::12345")
```

**返回值示例**：
```json
{
  "matches": [
    {"event_id": 7538, "name": "DrawIndexed", "match_reason": "pixel_shader contains 'Toon'"},
    {"event_id": 7620, "name": "DrawIndexed", "match_reason": "pixel_shader contains 'Toon'"}
  ],
  "total_matches": 2
}
```

**用例**：
- 直接回答"哪些 Draw 使用了这个着色器？"这一最常见的问题
- 追踪特定纹理在哪些地方被使用
- 确定着色器 Bug 的影响范围

---

### 4. 获取帧摘要（优先级：中）

获取整帧概要信息的功能。

```python
get_frame_summary()
```

**返回值示例**：
```json
{
  "api": "D3D11",
  "total_events": 7763,
  "statistics": {
    "draw_calls": 64,
    "dispatches": 193,
    "clears": 5,
    "copies": 8
  },
  "top_level_markers": [
    {"name": "WaitForRenderJobs", "event_id": 118},
    {"name": "CustomRenderTextures.Update", "event_id": 6451},
    {"name": "Camera.Render", "event_id": 7372},
    {"name": "UIR.DrawChain", "event_id": 6484}
  ],
  "render_targets": [
    {"resource_id": "ResourceId::22573", "name": "MainRT", "resolution": "1920x1080"},
    {"resource_id": "ResourceId::22585", "name": "ShadowMap", "resolution": "2048x2048"}
  ],
  "unique_shaders": {
    "vertex": 12,
    "pixel": 15,
    "compute": 8
  }
}
```

**用例**：
- 作为探索起点把握全局
- 判断应详细查看哪个标记下的内容
- 了解性能概况

---

### 5. 仅获取 Draw Call 模式（优先级：中）

排除标记（PushMarker/PopMarker），仅获取实际绘制调用的功能。

```python
get_draw_calls(
    only_actions=True,  # 排除标记
    flags_filter=["Drawcall", "Dispatch"]  # 仅包含具有特定标志的项
)
```

**用例**：
- 仅需要 Draw Call 的总数和列表时
- 仅需要调查 Compute Shader（Dispatch）时

---

### 6. 批量获取管线状态（优先级：低）

一次性获取多个 event_id 的管线状态的功能。

```python
get_multiple_pipeline_states(event_ids=[7538, 7558, 7450, 7458])
```

**返回值示例**：
```json
{
  "states": {
    "7538": { /* pipeline state */ },
    "7558": { /* pipeline state */ },
    "7450": { /* pipeline state */ },
    "7458": { /* pipeline state */ }
  }
}
```

**用例**：
- 对比分析多个 Draw Call
- 差异调查（对比正常的 Draw 和异常的 Draw）

---

## 优先级总结

| 优先级 | 功能 | 实现难度 | 效果 |
|--------|------|-----------|------|
| **高** | 标记过滤 | 中 | 去除 UI 噪声后大幅改善 |
| **高** | event_id 范围指定 | 低 | 部分获取提升速度 |
| **中** | 着色器/纹理反向搜索 | 高 | 直接支持最常见的用例 |
| **中** | 帧摘要 | 中 | 作为探索起点很有用 |
| **中** | 仅获取 Draw Call | 低 | 简单的过滤 |
| **低** | 批量获取 | 低 | 提高效率但非必须 |

## Unity 特有的过滤预设（可选）

有 Unity 专用预设会很方便：

```python
get_draw_calls(
    preset="unity_game_rendering"
)
```

**预设内容**：
- `marker_filter`: "Camera.Render"
- `exclude_markers`: ["GUI.Repaint", "UIR.DrawChain", "GUITexture.Draw", "UGUI.Rendering.RenderOverlays", "PlayerEndOfFrame", "EditorLoop"]

---

## 实现参考：当前工作流程的问题

### 当前流程

```
1. get_draw_calls(include_children=true)
   → 返回 76KB 的 JSON（保存到文件）

2. 用外部工具（Python 等）解析文件
   → 确定 Camera.Render 的 event_id（例：7372）

3. 手动指定 event_id 范围进行详细调查
   → get_pipeline_state(7538), get_shader_info(7538, "pixel"), ...
```

### 改进后的理想流程

```
1. get_frame_summary()
   → 得知 Camera.Render 在 event_id: 7372

2. get_draw_calls(marker_filter="Camera.Render", exclude_markers=[...])
   → 仅获取所需的 Draw Call（几 KB）

3. find_draws_by_shader(shader_name="MyShader")
   → 直接返回匹配的 event_id

4. get_pipeline_state(event_id) 查看详细信息
```

---

## 补充：应跳过的 Unity 标记列表

从 Unity Editor 捕获时应排除的标记：

| 标记名 | 说明 |
|-----------|------|
| `GUI.Repaint` | IMGUI 绘制 |
| `UIR.DrawChain` | UI Toolkit 绘制 |
| `GUITexture.Draw` | GUI 纹理绘制 |
| `UGUI.Rendering.RenderOverlays` | uGUI 覆盖层 |
| `PlayerEndOfFrame` | 帧结束处理 |
| `EditorLoop` | 编辑器循环处理 |

相反，重要的标记：

| 标记名 | 说明 |
|-----------|------|
| `Camera.Render` | 主摄像机绘制的起点 |
| `Drawing` | 绘制阶段 |
| `Render.OpaqueGeometry` | 不透明物体绘制 |
| `Render.TransparentGeometry` | 半透明物体绘制 |
| `RenderForward.RenderLoopJob` | 前向渲染的 Draw Call 组 |
| `Camera.RenderSkybox` | 天空盒绘制 |
| `Camera.ImageEffects` | 后处理 |
| `Shadows.RenderShadowMap` | 阴影贴图生成 |
