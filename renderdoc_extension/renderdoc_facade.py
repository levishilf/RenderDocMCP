"""
RenderDoc API Facade
Provides thread-safe access to RenderDoc's ReplayController and CaptureContext.
Uses BlockInvoke to marshal calls to the replay thread.
"""

import base64

# These modules are available in RenderDoc's embedded Python
import renderdoc as rd


class RenderDocFacade:
    """Facade for RenderDoc API access"""

    def __init__(self, ctx):
        """
        Initialize facade with CaptureContext.

        Args:
            ctx: The pyrenderdoc CaptureContext from register()
        """
        self.ctx = ctx

    def get_capture_status(self):
        """Check if a capture is loaded and get API info"""
        if not self.ctx.IsCaptureLoaded():
            return {"loaded": False}

        result = {"loaded": True, "api": None, "filename": None}

        try:
            result["filename"] = self.ctx.GetCaptureFilename()
        except Exception:
            pass

        # Get API type via replay
        def callback(controller):
            try:
                props = controller.GetAPIProperties()
                result["api"] = str(props.pipelineType)
            except Exception:
                pass

        self._invoke(callback)
        return result

    def get_draw_calls(self, include_children=True):
        """Get all draw calls/actions in the capture"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"actions": []}

        def callback(controller):
            root_actions = controller.GetRootActions()
            structured_file = controller.GetStructuredFile()
            result["actions"] = self._serialize_actions(
                root_actions, structured_file, include_children
            )

        self._invoke(callback)
        return result

    def get_draw_call_details(self, event_id):
        """Get detailed information about a specific draw call"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"details": None, "error": None}

        def callback(controller):
            # Move to the event
            controller.SetFrameEvent(event_id, True)

            action = self.ctx.GetAction(event_id)
            if not action:
                result["error"] = "No action at event %d" % event_id
                return

            structured_file = controller.GetStructuredFile()

            details = {
                "event_id": action.eventId,
                "action_id": action.actionId,
                "name": action.GetName(structured_file),
                "flags": self._serialize_flags(action.flags),
                "num_indices": action.numIndices,
                "num_instances": action.numInstances,
                "base_vertex": action.baseVertex,
                "vertex_offset": action.vertexOffset,
                "instance_offset": action.instanceOffset,
                "index_offset": action.indexOffset,
            }

            # Output resources
            outputs = []
            for i, output in enumerate(action.outputs):
                if output != rd.ResourceId.Null():
                    outputs.append({"index": i, "resource_id": str(output)})
            details["outputs"] = outputs

            if action.depthOut != rd.ResourceId.Null():
                details["depth_output"] = str(action.depthOut)

            result["details"] = details

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["details"]

    def get_shader_info(self, event_id, stage):
        """Get shader information for a specific stage"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"shader": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            pipe = controller.GetPipelineState()
            stage_enum = self._parse_stage(stage)

            shader = pipe.GetShader(stage_enum)
            if shader == rd.ResourceId.Null():
                result["error"] = "No %s shader bound" % stage
                return

            entry = pipe.GetShaderEntryPoint(stage_enum)
            reflection = pipe.GetShaderReflection(stage_enum)

            shader_info = {
                "resource_id": str(shader),
                "entry_point": entry,
                "stage": stage,
            }

            # Get disassembly
            try:
                targets = controller.GetDisassemblyTargets(True)
                if targets:
                    disasm = controller.DisassembleShader(
                        pipe.GetGraphicsPipelineObject(), reflection, targets[0]
                    )
                    shader_info["disassembly"] = disasm
            except Exception as e:
                shader_info["disassembly_error"] = str(e)

            # Get constant buffer info
            if reflection:
                shader_info["constant_buffers"] = self._get_cbuffer_info(
                    controller, pipe, reflection, stage_enum
                )
                shader_info["resources"] = self._get_resource_bindings(reflection)

            result["shader"] = shader_info

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["shader"]

    def get_buffer_contents(self, resource_id, offset=0, length=0):
        """Get buffer data"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            # Parse resource ID
            try:
                rid = self._parse_resource_id(resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            # Find buffer
            buf_desc = None
            for buf in controller.GetBuffers():
                if buf.resourceId == rid:
                    buf_desc = buf
                    break

            if not buf_desc:
                result["error"] = "Buffer not found: %s" % resource_id
                return

            # Get data
            actual_length = length if length > 0 else buf_desc.length
            data = controller.GetBufferData(rid, offset, actual_length)

            result["data"] = {
                "resource_id": resource_id,
                "length": len(data),
                "total_size": buf_desc.length,
                "offset": offset,
                "content_base64": base64.b64encode(data).decode("ascii"),
            }

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]

    def get_texture_info(self, resource_id):
        """Get texture metadata"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"texture": None, "error": None}

        def callback(controller):
            try:
                rid = self._parse_resource_id(resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            # Find texture
            tex_desc = None
            for tex in controller.GetTextures():
                if tex.resourceId == rid:
                    tex_desc = tex
                    break

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            result["texture"] = {
                "resource_id": resource_id,
                "width": tex_desc.width,
                "height": tex_desc.height,
                "depth": tex_desc.depth,
                "array_size": tex_desc.arraysize,
                "mip_levels": tex_desc.mips,
                "format": str(tex_desc.format.Name()),
                "dimension": str(tex_desc.type),
                "msaa_samples": tex_desc.msSamp,
                "byte_size": tex_desc.byteSize,
            }

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["texture"]

    def get_texture_data(self, resource_id, mip=0, slice=0, sample=0, depth_slice=None):
        """
        Get texture pixel data.

        Args:
            resource_id: Resource ID of the texture
            mip: Mip level to retrieve (default: 0)
            slice: Array slice or cube face (default: 0)
                   Note: For 3D textures, slice is ignored by RenderDoc API
            sample: MSAA sample index (default: 0)
            depth_slice: For 3D textures, extract a specific depth slice (default: None = full volume)
                         When specified, returns only the 2D slice at that depth index

        Returns:
            dict with texture metadata and base64-encoded pixel data
        """
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"data": None, "error": None}

        def callback(controller):
            try:
                rid = self._parse_resource_id(resource_id)
            except Exception:
                result["error"] = "Invalid resource ID: %s" % resource_id
                return

            # Find texture to get metadata
            tex_desc = None
            for tex in controller.GetTextures():
                if tex.resourceId == rid:
                    tex_desc = tex
                    break

            if not tex_desc:
                result["error"] = "Texture not found: %s" % resource_id
                return

            # Validate mip level
            if mip < 0 or mip >= tex_desc.mips:
                result["error"] = "Invalid mip level %d (texture has %d mips)" % (
                    mip,
                    tex_desc.mips,
                )
                return

            # Validate slice for array/cube textures
            max_slices = tex_desc.arraysize
            if tex_desc.cubemap:
                max_slices = tex_desc.arraysize * 6  # 6 faces per cube
            if slice < 0 or (max_slices > 1 and slice >= max_slices):
                result["error"] = "Invalid slice %d (texture has %d slices)" % (
                    slice,
                    max_slices,
                )
                return

            # Validate sample for MSAA
            if sample < 0 or (tex_desc.msSamp > 1 and sample >= tex_desc.msSamp):
                result["error"] = "Invalid sample %d (texture has %d samples)" % (
                    sample,
                    tex_desc.msSamp,
                )
                return

            # Calculate dimensions at this mip level
            mip_width = max(1, tex_desc.width >> mip)
            mip_height = max(1, tex_desc.height >> mip)
            mip_depth = max(1, tex_desc.depth >> mip)

            # Validate depth_slice for 3D textures
            is_3d = tex_desc.depth > 1
            if depth_slice is not None:
                if not is_3d:
                    result["error"] = "depth_slice can only be used with 3D textures"
                    return
                if depth_slice < 0 or depth_slice >= mip_depth:
                    result["error"] = "Invalid depth_slice %d (texture has %d depth at mip %d)" % (
                        depth_slice,
                        mip_depth,
                        mip,
                    )
                    return

            # Create subresource specification
            sub = rd.Subresource()
            sub.mip = mip
            sub.slice = slice
            sub.sample = sample

            # Get texture data
            try:
                data = controller.GetTextureData(rid, sub)
            except Exception as e:
                result["error"] = "Failed to get texture data: %s" % str(e)
                return

            # Extract depth slice for 3D textures if requested
            output_depth = mip_depth
            if is_3d and depth_slice is not None:
                # Calculate bytes per slice (width * height * bytes_per_pixel)
                total_size = len(data)
                bytes_per_slice = total_size // mip_depth

                # Extract the requested slice
                slice_start = depth_slice * bytes_per_slice
                slice_end = slice_start + bytes_per_slice
                data = data[slice_start:slice_end]
                output_depth = 1

            result["data"] = {
                "resource_id": resource_id,
                "width": mip_width,
                "height": mip_height,
                "depth": output_depth,
                "mip": mip,
                "slice": slice,
                "sample": sample,
                "depth_slice": depth_slice,
                "format": str(tex_desc.format.Name()),
                "dimension": str(tex_desc.type),
                "is_3d": is_3d,
                "total_depth": mip_depth if is_3d else 1,
                "data_length": len(data),
                "content_base64": base64.b64encode(data).decode("ascii"),
            }

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["data"]

    def get_pipeline_state(self, event_id):
        """Get full pipeline state at an event"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"pipeline": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            pipe = controller.GetPipelineState()
            api = controller.GetAPIProperties().pipelineType

            pipeline_info = {
                "event_id": event_id,
                "api": str(api),
            }

            # Shader stages
            stages = {}
            stage_list = [
                rd.ShaderStage.Vertex,
                rd.ShaderStage.Hull,
                rd.ShaderStage.Domain,
                rd.ShaderStage.Geometry,
                rd.ShaderStage.Pixel,
                rd.ShaderStage.Compute,
            ]
            for stage in stage_list:
                shader = pipe.GetShader(stage)
                if shader != rd.ResourceId.Null():
                    stages[str(stage)] = {
                        "resource_id": str(shader),
                        "entry_point": pipe.GetShaderEntryPoint(stage),
                    }
            pipeline_info["shaders"] = stages

            # Viewport and scissor
            try:
                vp_scissor = pipe.GetViewportScissor()
                if vp_scissor:
                    viewports = []
                    for v in vp_scissor.viewports:
                        viewports.append(
                            {
                                "x": v.x,
                                "y": v.y,
                                "width": v.width,
                                "height": v.height,
                                "min_depth": v.minDepth,
                                "max_depth": v.maxDepth,
                            }
                        )
                    pipeline_info["viewports"] = viewports
            except Exception:
                pass

            # Render targets
            try:
                om = pipe.GetOutputMerger()
                if om:
                    rts = []
                    for i, rt in enumerate(om.renderTargets):
                        if rt.resourceId != rd.ResourceId.Null():
                            rts.append({"index": i, "resource_id": str(rt.resourceId)})
                    pipeline_info["render_targets"] = rts

                    if om.depthTarget.resourceId != rd.ResourceId.Null():
                        pipeline_info["depth_target"] = str(om.depthTarget.resourceId)
            except Exception:
                pass

            # Input assembly
            try:
                ia = pipe.GetIAState()
                if ia:
                    pipeline_info["input_assembly"] = {"topology": str(ia.topology)}
            except Exception:
                pass

            result["pipeline"] = pipeline_info

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["pipeline"]

    # ==================== Helper Methods ====================

    def _invoke(self, callback):
        """Invoke callback on replay thread via BlockInvoke"""
        self.ctx.Replay().BlockInvoke(callback)

    def _serialize_actions(self, actions, structured_file, include_children):
        """Serialize action list to JSON-compatible format"""
        serialized = []
        for action in actions:
            item = {
                "event_id": action.eventId,
                "action_id": action.actionId,
                "name": action.GetName(structured_file),
                "flags": self._serialize_flags(action.flags),
                "num_indices": action.numIndices,
                "num_instances": action.numInstances,
            }
            if include_children and action.children:
                item["children"] = self._serialize_actions(
                    action.children, structured_file, include_children
                )
            serialized.append(item)
        return serialized

    def _serialize_flags(self, flags):
        """Convert ActionFlags to list of strings"""
        flag_names = []
        flag_map = [
            (rd.ActionFlags.Drawcall, "Drawcall"),
            (rd.ActionFlags.Dispatch, "Dispatch"),
            (rd.ActionFlags.Clear, "Clear"),
            (rd.ActionFlags.PushMarker, "PushMarker"),
            (rd.ActionFlags.PopMarker, "PopMarker"),
            (rd.ActionFlags.SetMarker, "SetMarker"),
            (rd.ActionFlags.Present, "Present"),
            (rd.ActionFlags.Copy, "Copy"),
            (rd.ActionFlags.Resolve, "Resolve"),
            (rd.ActionFlags.GenMips, "GenMips"),
            (rd.ActionFlags.PassBoundary, "PassBoundary"),
            (rd.ActionFlags.Indexed, "Indexed"),
            (rd.ActionFlags.Instanced, "Instanced"),
            (rd.ActionFlags.Auto, "Auto"),
            (rd.ActionFlags.Indirect, "Indirect"),
            (rd.ActionFlags.ClearColor, "ClearColor"),
            (rd.ActionFlags.ClearDepthStencil, "ClearDepthStencil"),
            (rd.ActionFlags.BeginPass, "BeginPass"),
            (rd.ActionFlags.EndPass, "EndPass"),
        ]
        for flag, name in flag_map:
            if flags & flag:
                flag_names.append(name)
        return flag_names

    def _parse_stage(self, stage_str):
        """Convert stage string to ShaderStage enum"""
        stage_map = {
            "vertex": rd.ShaderStage.Vertex,
            "hull": rd.ShaderStage.Hull,
            "domain": rd.ShaderStage.Domain,
            "geometry": rd.ShaderStage.Geometry,
            "pixel": rd.ShaderStage.Pixel,
            "compute": rd.ShaderStage.Compute,
        }
        stage_lower = stage_str.lower()
        if stage_lower not in stage_map:
            raise ValueError("Unknown shader stage: %s" % stage_str)
        return stage_map[stage_lower]

    def _parse_resource_id(self, resource_id_str):
        """Parse resource ID string to ResourceId object"""
        # Handle formats like "ResourceId::123" or just "123"
        rid = rd.ResourceId()
        if "::" in resource_id_str:
            id_part = resource_id_str.split("::")[-1]
        else:
            id_part = resource_id_str
        rid.id = int(id_part)
        return rid

    def _get_cbuffer_info(self, controller, pipe, reflection, stage):
        """Get constant buffer information and values"""
        cbuffers = []

        for i, cb in enumerate(reflection.constantBlocks):
            cb_info = {
                "name": cb.name,
                "slot": i,
                "size": cb.byteSize,
                "variables": [],
            }

            try:
                bind = pipe.GetConstantBuffer(stage, i, 0)
                if bind.resourceId != rd.ResourceId.Null():
                    variables = controller.GetCBufferVariableContents(
                        pipe.GetGraphicsPipelineObject(),
                        reflection.resourceId,
                        stage,
                        reflection.entryPoint,
                        i,
                        bind.resourceId,
                        bind.byteOffset,
                        bind.byteSize,
                    )
                    cb_info["variables"] = self._serialize_variables(variables)
            except Exception as e:
                cb_info["error"] = str(e)

            cbuffers.append(cb_info)

        return cbuffers

    def _serialize_variables(self, variables):
        """Serialize shader variables to JSON format"""
        result = []
        for var in variables:
            var_info = {
                "name": var.name,
                "type": str(var.type),
                "rows": var.rows,
                "columns": var.columns,
            }

            # Get value based on type
            try:
                if var.type == rd.VarType.Float:
                    count = var.rows * var.columns
                    var_info["value"] = list(var.value.f32v[:count])
                elif var.type == rd.VarType.Int:
                    count = var.rows * var.columns
                    var_info["value"] = list(var.value.s32v[:count])
                elif var.type == rd.VarType.UInt:
                    count = var.rows * var.columns
                    var_info["value"] = list(var.value.u32v[:count])
            except Exception:
                pass

            # Nested members
            if var.members:
                var_info["members"] = self._serialize_variables(var.members)

            result.append(var_info)

        return result

    def _get_resource_bindings(self, reflection):
        """Get shader resource bindings"""
        resources = []

        try:
            for res in reflection.readOnlyResources:
                resources.append(
                    {
                        "name": res.name,
                        "type": str(res.resType),
                        "binding": res.fixedBindNumber,
                        "access": "ReadOnly",
                    }
                )
        except Exception:
            pass

        try:
            for res in reflection.readWriteResources:
                resources.append(
                    {
                        "name": res.name,
                        "type": str(res.resType),
                        "binding": res.fixedBindNumber,
                        "access": "ReadWrite",
                    }
                )
        except Exception:
            pass

        return resources
