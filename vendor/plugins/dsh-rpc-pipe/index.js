/**
 * dsh-rpc-pipe — expose the harness SDK JSON-RPC server over a local named pipe.
 *
 * The packaged `@deepseek-ai/dsh-sdk-jsonrpc-server` plugin wires its transport to
 * `process.stdin` / `process.stdout` (its Config schema only exposes
 * `maxTokensAsSuccess`), so a long-lived harness process can serve exactly one
 * out-of-process client. This plugin reuses the exported `HarnessSdkJsonRpcServer`
 * class and `JsonRpcLineTransport` class, but creates one server instance per pipe
 * connection, so several local clients (ComfyUI nodes, a chat panel, other tools)
 * share the same agent runtime without sharing a single stdio channel.
 *
 * Hard rules baked into this implementation:
 *  - never call the packaged plugin's `disposeAndExit` (it calls `process.exit(0)`
 *    and would take the host process down);
 *  - `shutdown` closes only the issuing connection;
 *  - connection teardown disposes that connection's server and nothing else.
 *
 * Both npm packages are loaded from the harness installation by absolute file URL:
 * the plugin lives outside the harness package tree, so bare specifier resolution
 * would not reach them.
 *
 * @module dsh-rpc-pipe
 */

import net from "node:net";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

/** Cordis plugin name. */
export const name = "rpc-pipe";

/** Services the harness SDK server needs; both exist in base-backed profiles. */
export const inject = ["agents", "workingDirectory"];

const DEFAULT_HARNESS_ROOT = "D:\\ai\\harness\\resources\\app\\dsh";
const DEFAULT_PIPE_PATH = "\\\\.\\pipe\\dsh-comfy";

/**
 * Import the two harness packages from an installation root.
 * @param {string} root - directory that contains `node_modules/@deepseek-ai/...`.
 * @returns {Promise<{HarnessSdkJsonRpcServer: any, JsonRpcLineTransport: any}>}
 */
async function loadHarnessModules(root) {
  const pkg = (name, entry) => pathToFileURL(join(root, "node_modules", "@deepseek-ai", name, "lib", entry)).href;
  const [serverMod, protoMod] = await Promise.all([
    import(pkg("dsh-sdk-jsonrpc-server", "index.js")),
    import(pkg("dsh-sdk-protocol", "index.js")),
  ]);
  return {
    HarnessSdkJsonRpcServer: serverMod.HarnessSdkJsonRpcServer,
    JsonRpcLineTransport: protoMod.JsonRpcLineTransport,
  };
}

/**
 * Serve the SDK JSON-RPC protocol on a named pipe.
 * @param {any} ctx - host plugin context.
 * @param {any} config - `{ pipePath, harnessRoot, maxTokensAsSuccess }`.
 */
export async function apply(ctx, config) {
  const cfg = config ?? {};
  const pipePath = typeof cfg.pipePath === "string" && cfg.pipePath.length > 0 ? cfg.pipePath : DEFAULT_PIPE_PATH;
  const harnessRoot =
    typeof cfg.harnessRoot === "string" && cfg.harnessRoot.length > 0 ? cfg.harnessRoot : DEFAULT_HARNESS_ROOT;
  const maxTokensAsSuccess = cfg.maxTokensAsSuccess !== false;
  const log = (message) => ctx.logger?.info?.(`rpc-pipe: ${message}`);

  const { HarnessSdkJsonRpcServer, JsonRpcLineTransport } = await loadHarnessModules(harnessRoot);

  /** @type {Set<any>} */
  const connections = new Set();

  /**
   * Bind one accepted socket to its own SDK server instance.
   * @param {import("node:net").Socket} sock - accepted duplex socket.
   */
  const attach = (sock) => {
    sock.setNoDelay?.(true);
    const transport = new JsonRpcLineTransport(sock, sock);
    const server = new HarnessSdkJsonRpcServer(ctx, transport, { maxTokensAsSuccess });
    const record = { sock, transport, server, closed: false };
    connections.add(record);

    const disposeRecord = () => {
      if (record.closed) return;
      record.closed = true;
      connections.delete(record);
      Promise.resolve()
        .then(() => server.shutdown())
        .catch(() => {});
    };

    transport.onRequest(async (method, params) => {
      if (method === "initialize") await ctx.get("loader")?.await();
      const result = await server.handleRequest(method, params);
      if (method === "shutdown") {
        log(`shutdown requested on ${pipePath}; closing this connection only`);
        setImmediate(() => {
          try {
            Promise.resolve(transport.flush()).catch(() => {});
          } catch {}
          try {
            sock.end();
          } catch {}
          disposeRecord();
        });
      }
      return result;
    });

    sock.on("close", () => {
      try {
        transport.close();
      } catch {}
      disposeRecord();
    });
    sock.on("error", (error) => {
      ctx.logger?.warn?.(`rpc-pipe: connection error: ${error?.message ?? String(error)}`);
      try {
        transport.close();
      } catch {}
      disposeRecord();
    });

    transport.start();
    log(`client connected (${connections.size} open)`);
  };

  const server = net.createServer({ allowHalfOpen: true }, attach);

  ctx.effect(() => {
    server.listen(pipePath, () => log(`listening on ${pipePath}`));
    server.on("error", (error) => ctx.logger?.warn?.(`rpc-pipe: server error: ${error?.message ?? String(error)}`));
    return async () => {
      for (const record of [...connections]) {
        try {
          record.sock.destroy();
        } catch {}
        await Promise.resolve()
          .then(() => record.server.shutdown())
          .catch(() => {});
        connections.delete(record);
      }
      await new Promise((resolve) => server.close(() => resolve()));
      log("stopped");
    };
  }, "rpc-pipe.serve");
}
