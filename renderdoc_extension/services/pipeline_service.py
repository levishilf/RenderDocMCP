"""
Pipeline state service for RenderDoc.
"""

import renderdoc as rd

from ..utils import Parsers, Serializers, Helpers


class PipelineService:
    """Pipeline state service"""

    def __init__(self, ctx, invoke_fn):
        self.ctx = ctx
        self._invoke = invoke_fn

    def get_shader_info(self, event_id, stage):
        """Get shader information for a specific stage"""
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"shader": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            pipe = controller.GetPipelineState()
            stage_enum = Parsers.parse_stage(stage)

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

            # Try to get original shader source from reflection data
            # (works for OpenGL/GLES captures where GLSL source is embedded)
            raw_source = self._extract_source_from_reflection(reflection)
            if raw_source:
                shader_info["source_code"] = raw_source["source_code"]
                shader_info["source_encoding"] = raw_source["encoding"]
                shader_info["source_method"] = raw_source["method"]
                if raw_source.get("debug_files"):
                    shader_info["debug_source_files"] = raw_source["debug_files"]

            # Get disassembly - try to find the most readable target
            try:
                targets = controller.GetDisassemblyTargets(True)
                shader_info["disassembly_targets"] = list(targets) if targets else []
                if targets:
                    # Pick the best readable target
                    best_target = self._pick_best_disassembly_target(targets)
                    shader_info["disassembly_target_used"] = best_target
                    disasm = controller.DisassembleShader(
                        pipe.GetGraphicsPipelineObject(), reflection, best_target
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

    @staticmethod
    def _extract_source_from_reflection(reflection):
        """Try to extract original shader source from ShaderReflection.

        For OpenGL/GLES captures, the raw GLSL source is typically embedded
        in the capture and accessible via reflection.rawBytes or
        reflection.debugInfo.files.

        Returns dict with source_code, encoding, method, debug_files or None.
        """
        if not reflection:
            return None

        result = {}

        # Method 1: Try reflection.rawBytes (contains original GLSL for GL/GLES)
        try:
            raw_bytes = reflection.rawBytes
            if raw_bytes and len(raw_bytes) > 0:
                encoding_str = ""
                try:
                    encoding_str = str(reflection.encoding)
                except Exception:
                    pass

                # For GLSL/GLSL-ES, rawBytes is the text source
                is_text = (
                    "glsl" in encoding_str.lower() or "hlsl" in encoding_str.lower()
                )

                if is_text:
                    # Decode as UTF-8 text
                    try:
                        source_text = bytes(raw_bytes).decode("utf-8", errors="replace")
                        # Strip null terminator if present
                        source_text = source_text.rstrip("\x00")
                        if source_text.strip():
                            result["source_code"] = source_text
                            result["encoding"] = encoding_str
                            result["method"] = "rawBytes"
                    except Exception:
                        pass
                else:
                    # For SPIR-V or other binary formats, note the encoding
                    # but don't try to decode as text
                    result["encoding"] = encoding_str
                    result["raw_bytes_size"] = len(raw_bytes)
        except Exception:
            pass

        # Method 2: Try reflection.debugInfo.files (debug source files)
        try:
            debug_info = reflection.debugInfo
            if debug_info and hasattr(debug_info, "files") and debug_info.files:
                debug_files = []
                for f in debug_info.files:
                    file_info = {}
                    try:
                        file_info["filename"] = (
                            f.filename if hasattr(f, "filename") else ""
                        )
                    except Exception:
                        file_info["filename"] = ""
                    try:
                        file_info["contents"] = (
                            f.contents if hasattr(f, "contents") else ""
                        )
                    except Exception:
                        file_info["contents"] = ""
                    if file_info.get("contents"):
                        debug_files.append(file_info)

                if debug_files:
                    result["debug_files"] = debug_files
                    # If we didn't get source from rawBytes, use first debug file
                    if "source_code" not in result:
                        result["source_code"] = debug_files[0]["contents"]
                        result["encoding"] = "debug_info"
                        result["method"] = "debugInfo.files[%s]" % debug_files[0].get(
                            "filename", "0"
                        )
        except Exception:
            pass

        if "source_code" in result:
            return result
        return None

    @staticmethod
    def _pick_best_disassembly_target(targets):
        """Pick the most human-readable disassembly target.

        Priority order:
        1. GLSL (cross-compiled from SPIR-V, most readable for mobile)
        2. HLSL (cross-compiled, readable for desktop)
        3. Anything that looks like high-level source
        4. SPIR-V (IL) as fallback
        5. First available target as last resort
        """
        targets_lower = [(t, t.lower()) for t in targets]

        # Prefer GLSL cross-compiled
        for t, tl in targets_lower:
            if "glsl" in tl and ("cross" in tl or "compil" in tl):
                return t

        # Then plain GLSL
        for t, tl in targets_lower:
            if "glsl" in tl:
                return t

        # Then HLSL cross-compiled
        for t, tl in targets_lower:
            if "hlsl" in tl and ("cross" in tl or "compil" in tl):
                return t

        # Then plain HLSL
        for t, tl in targets_lower:
            if "hlsl" in tl:
                return t

        # Skip raw IL targets, look for anything else
        for t, tl in targets_lower:
            if "il" not in tl and "bytecode" not in tl and "binary" not in tl:
                return t

        # Fallback: first target
        return targets[0]

    def get_shader_source(self, event_id, stage, target=None):
        """Get decompiled/disassembled shader source code.

        Tries all available disassembly targets to find readable shader code.
        For mobile (Vulkan/GLES) captures this typically cross-compiles
        SPIR-V back to GLSL.

        Args:
            event_id: The event ID to inspect
            stage: Shader stage string (vertex, pixel, etc.)
            target: Specific disassembly target name (optional).
                    If None, tries all targets and returns the best readable one.
        """
        if not self.ctx.IsCaptureLoaded():
            raise ValueError("No capture loaded")

        result = {"source": None, "error": None}

        def callback(controller):
            controller.SetFrameEvent(event_id, True)

            pipe = controller.GetPipelineState()
            stage_enum = Parsers.parse_stage(stage)

            shader = pipe.GetShader(stage_enum)
            if shader == rd.ResourceId.Null():
                result["error"] = "No %s shader bound" % stage
                return

            entry = pipe.GetShaderEntryPoint(stage_enum)
            reflection = pipe.GetShaderReflection(stage_enum)

            source_info = {
                "resource_id": str(shader),
                "entry_point": entry,
                "stage": stage,
            }

            # Method 1: Try to get original source from reflection data
            # (works for OpenGL/GLES captures where GLSL source is embedded)
            raw_source = self._extract_source_from_reflection(reflection)
            if raw_source and raw_source.get("source_code"):
                source_info["source_code"] = raw_source["source_code"]
                source_info["source_encoding"] = raw_source.get("encoding", "")
                source_info["source_method"] = raw_source.get("method", "")
                source_info["target"] = "embedded_source"
                if raw_source.get("debug_files"):
                    source_info["debug_source_files"] = raw_source["debug_files"]
                # Still try disassembly for additional info, but source is already found

            # Method 2: Try disassembly targets
            try:
                targets = controller.GetDisassemblyTargets(True)
                source_info["available_targets"] = list(targets) if targets else []

                if not targets:
                    if "source_code" not in source_info:
                        source_info["error"] = "No disassembly targets available"
                    result["source"] = source_info
                    return

                pipeline_obj = pipe.GetGraphicsPipelineObject()

                if target:
                    # User specified a target
                    matching = [t for t in targets if target.lower() in t.lower()]
                    if not matching:
                        if "source_code" not in source_info:
                            source_info["error"] = (
                                "Target '%s' not found. Available: %s"
                                % (target, ", ".join(targets))
                            )
                        result["source"] = source_info
                        return
                    chosen = matching[0]
                    try:
                        code = controller.DisassembleShader(
                            pipeline_obj, reflection, chosen
                        )
                        # Only overwrite if we got valid disassembly
                        if code and not code.startswith("[Error"):
                            source_info["target"] = chosen
                            source_info["source_code"] = code
                    except Exception as e:
                        if "source_code" not in source_info:
                            source_info["error"] = "Disassembly failed for '%s': %s" % (
                                chosen,
                                str(e),
                            )
                else:
                    # Try all targets, return results keyed by target name
                    all_sources = {}
                    best_target = self._pick_best_disassembly_target(targets)

                    for t in targets:
                        try:
                            code = controller.DisassembleShader(
                                pipeline_obj, reflection, t
                            )
                            all_sources[t] = code
                        except Exception as e:
                            all_sources[t] = "[Error: %s]" % str(e)

                    source_info["all_sources"] = all_sources

                    # Only overwrite source_code from disassembly if:
                    # 1. We don't already have embedded source, OR
                    # 2. The disassembly result is valid (not an error)
                    best_code = all_sources.get(best_target, "")
                    if best_code and not best_code.startswith("[Error"):
                        # Valid disassembly found — only overwrite if no embedded source
                        if "source_code" not in source_info:
                            source_info["target"] = best_target
                            source_info["source_code"] = best_code
                    else:
                        # Best target failed, but we may already have embedded source
                        if "source_code" not in source_info:
                            # No embedded source either, try to find any working target
                            for t, code in all_sources.items():
                                if code and not code.startswith("[Error"):
                                    source_info["target"] = t
                                    source_info["source_code"] = code
                                    break

            except Exception as e:
                import traceback

                source_info["error"] = "Disassembly error: %s\n%s" % (
                    str(e),
                    traceback.format_exc(),
                )

            result["source"] = source_info

        self._invoke(callback)

        if result["error"]:
            raise ValueError(result["error"])
        return result["source"]

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

            # Shader stages with detailed bindings
            stages = {}
            stage_list = Helpers.get_all_shader_stages()
            for stage in stage_list:
                shader = pipe.GetShader(stage)
                if shader != rd.ResourceId.Null():
                    stage_info = {
                        "resource_id": str(shader),
                        "entry_point": pipe.GetShaderEntryPoint(stage),
                    }

                    reflection = pipe.GetShaderReflection(stage)

                    stage_info["resources"] = self._get_stage_resources(
                        controller, pipe, stage, reflection
                    )
                    stage_info["uavs"] = self._get_stage_uavs(
                        controller, pipe, stage, reflection
                    )
                    stage_info["samplers"] = self._get_stage_samplers(
                        pipe, stage, reflection
                    )
                    stage_info["constant_buffers"] = self._get_stage_cbuffers(
                        controller, pipe, stage, reflection
                    )

                    stages[str(stage)] = stage_info

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

    def _get_stage_resources(self, controller, pipe, stage, reflection):
        """Get shader resource views (SRVs) for a stage"""
        resources = []
        try:
            srvs = pipe.GetReadOnlyResources(stage, False)

            name_map = {}
            if reflection:
                for res in reflection.readOnlyResources:
                    name_map[res.fixedBindNumber] = res.name

            for srv in srvs:
                if srv.descriptor.resource == rd.ResourceId.Null():
                    continue

                slot = srv.access.index
                res_info = {
                    "slot": slot,
                    "name": name_map.get(slot, ""),
                    "resource_id": str(srv.descriptor.resource),
                }

                res_info.update(
                    self._get_resource_details(controller, srv.descriptor.resource)
                )

                res_info["first_mip"] = srv.descriptor.firstMip
                res_info["num_mips"] = srv.descriptor.numMips
                res_info["first_slice"] = srv.descriptor.firstSlice
                res_info["num_slices"] = srv.descriptor.numSlices

                resources.append(res_info)
        except Exception as e:
            resources.append({"error": str(e)})

        return resources

    def _get_stage_uavs(self, controller, pipe, stage, reflection):
        """Get unordered access views (UAVs) for a stage"""
        uavs = []
        try:
            uav_list = pipe.GetReadWriteResources(stage, False)

            name_map = {}
            if reflection:
                for res in reflection.readWriteResources:
                    name_map[res.fixedBindNumber] = res.name

            for uav in uav_list:
                if uav.descriptor.resource == rd.ResourceId.Null():
                    continue

                slot = uav.access.index
                uav_info = {
                    "slot": slot,
                    "name": name_map.get(slot, ""),
                    "resource_id": str(uav.descriptor.resource),
                }

                uav_info.update(
                    self._get_resource_details(controller, uav.descriptor.resource)
                )

                uav_info["first_element"] = uav.descriptor.firstMip
                uav_info["num_elements"] = uav.descriptor.numMips

                uavs.append(uav_info)
        except Exception as e:
            uavs.append({"error": str(e)})

        return uavs

    def _get_stage_samplers(self, pipe, stage, reflection):
        """Get samplers for a stage"""
        samplers = []
        try:
            sampler_list = pipe.GetSamplers(stage, False)

            name_map = {}
            if reflection:
                for samp in reflection.samplers:
                    name_map[samp.fixedBindNumber] = samp.name

            for samp in sampler_list:
                slot = samp.access.index
                samp_info = {
                    "slot": slot,
                    "name": name_map.get(slot, ""),
                }

                desc = samp.descriptor
                try:
                    samp_info["address_u"] = str(desc.addressU)
                    samp_info["address_v"] = str(desc.addressV)
                    samp_info["address_w"] = str(desc.addressW)
                except AttributeError:
                    pass

                try:
                    samp_info["filter"] = str(desc.filter)
                except AttributeError:
                    pass

                try:
                    samp_info["max_anisotropy"] = desc.maxAnisotropy
                except AttributeError:
                    pass

                try:
                    samp_info["min_lod"] = desc.minLOD
                    samp_info["max_lod"] = desc.maxLOD
                    samp_info["mip_lod_bias"] = desc.mipLODBias
                except AttributeError:
                    pass

                try:
                    samp_info["border_color"] = [
                        desc.borderColor[0],
                        desc.borderColor[1],
                        desc.borderColor[2],
                        desc.borderColor[3],
                    ]
                except (AttributeError, TypeError):
                    pass

                try:
                    samp_info["compare_function"] = str(desc.compareFunction)
                except AttributeError:
                    pass

                samplers.append(samp_info)
        except Exception as e:
            samplers.append({"error": str(e)})

        return samplers

    def _get_stage_cbuffers(self, controller, pipe, stage, reflection):
        """Get constant buffers for a stage from shader reflection"""
        cbuffers = []
        try:
            if not reflection:
                return cbuffers

            for cb in reflection.constantBlocks:
                slot = cb.bindPoint if hasattr(cb, "bindPoint") else cb.fixedBindNumber
                cb_info = {
                    "slot": slot,
                    "name": cb.name,
                    "byte_size": cb.byteSize,
                    "variable_count": len(cb.variables) if cb.variables else 0,
                    "variables": [],
                }
                if cb.variables:
                    for var in cb.variables:
                        cb_info["variables"].append(
                            {
                                "name": var.name,
                                "byte_offset": var.byteOffset,
                                "type": str(var.type.name) if var.type else "",
                            }
                        )
                cbuffers.append(cb_info)

        except Exception as e:
            cbuffers.append({"error": str(e)})

        return cbuffers

    def _get_resource_details(self, controller, resource_id):
        """Get details about a resource (texture or buffer)"""
        details = {}

        try:
            resource_name = self.ctx.GetResourceName(resource_id)
            if resource_name:
                details["resource_name"] = resource_name
        except Exception:
            pass

        for tex in controller.GetTextures():
            if tex.resourceId == resource_id:
                details["type"] = "texture"
                details["width"] = tex.width
                details["height"] = tex.height
                details["depth"] = tex.depth
                details["array_size"] = tex.arraysize
                details["mip_levels"] = tex.mips
                details["format"] = str(tex.format.Name())
                details["dimension"] = str(tex.type)
                details["msaa_samples"] = tex.msSamp
                return details

        for buf in controller.GetBuffers():
            if buf.resourceId == resource_id:
                details["type"] = "buffer"
                details["length"] = buf.length
                return details

        return details

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
                    cb_info["variables"] = Serializers.serialize_variables(variables)
            except Exception as e:
                cb_info["error"] = str(e)

            cbuffers.append(cb_info)

        return cbuffers

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
