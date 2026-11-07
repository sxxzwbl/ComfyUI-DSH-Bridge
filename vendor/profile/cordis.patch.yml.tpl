# ComfyUI-DSH-Bridge profile: base + sdk app + the named-pipe JSON-RPC entry point.
#
# This file is a template. `scripts/install.py` fills in {{PIPE_PATH}} and
# {{HARNESS_ROOT}} and writes the result to <DSH_HOME>/profiles/comfy/cordis.patch.yml.
# Edit the generated copy for local changes; keep this one generic.
- insert:
    - id: rpc-pipe
      name: dsh-rpc-pipe
      inject: [agents, workingDirectory]
      config:
        pipePath: '{{PIPE_PATH}}'
        harnessRoot: '{{HARNESS_ROOT}}'
        maxTokensAsSuccess: true

# Prompt-engine persona for this profile. The node's prompt output goes straight
# into CLIP, so anything that is not the artefact is contamination.
- id: system-prompt
  config:
    personaPrefix: |
      你是运行在 ComfyUI 里的提示词推理引擎。只输出用户要求的内容，不解释过程、不加前言。
      需要图像或视频模型专用结构时，先调用 skill 工具加载对应技能，再严格按那个 skill 的结构输出。

# Lean tool set: a prompt engine needs vision, file reads and skills — not
# shells, subagents or schedulers. Dropping their schemas also cuts input tokens.
# NOTE: ids must match the row ids as inserted by the bundles. dsh-base owns the
# `tool-*` ids; dsh-sdk-app re-inserts three rows under different ids
# (`present`, `workspace-dependencies`, `tool-schedule`), so disabling
# `tool-present` / `tool-workspace-dependencies` silently does nothing.
- id: tool-bash
  disabled: true
- id: tool-pwsh
  disabled: true
- id: tool-plugin-manager
  disabled: true
- id: tool-schedule
  disabled: true
- id: tool-goal
  disabled: true
- id: tool-subagent
  disabled: true
- id: tool-subagent-control
  disabled: true
- id: tool-workflow
  disabled: true
- id: tool-jobs
  disabled: true
- id: tool-todo
  disabled: true

# sdk-app rows (different ids — see note above).
- id: present
  name: '@deepseek-ai/dsh-tool-present'
  disabled: true
- id: workspace-dependencies
  name: '@deepseek-ai/dsh-tool-workspace-dependencies'
  disabled: true
