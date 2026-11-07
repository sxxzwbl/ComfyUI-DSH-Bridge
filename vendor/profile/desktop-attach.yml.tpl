# >>> ComfyUI-DSH-Bridge (attach mode)
#
# Publish the desktop harness on a named pipe so ComfyUI can reuse the runtime
# that is already signed in, instead of spawning a second harness of its own.
# That keeps one credential store, one session log and one model catalog.
#
# `scripts/install.py --attach` writes this block into
# <DSH_HOME>/profiles/desktop/cordis.patch.yml and rewrites it in place on every
# run, so hand edits inside the markers are lost; put custom rows outside them.
#
# harnessRoot must be the directory that contains node_modules/@deepseek-ai —
# for a packed install that is <harness>/resources/app.asar/dsh, not
# <harness>/resources/app/dsh.
- insert:
    - id: rpc-pipe
      name: '{{PLUGIN_URL}}'
      inject: [agents, workingDirectory]
      config:
        pipePath: '{{PIPE_PATH}}'
        harnessRoot: '{{HARNESS_ROOT}}'
        maxTokensAsSuccess: true
# <<< ComfyUI-DSH-Bridge
