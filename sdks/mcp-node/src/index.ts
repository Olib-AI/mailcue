import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { ConfigError, isLocked, loadConfig } from './config.js';
import { buildServer } from './server.js';

function logStderr(message: string): void {
  process.stderr.write(`${message}\n`);
}

async function main(): Promise<void> {
  let config;
  try {
    config = loadConfig();
  } catch (err) {
    if (err instanceof ConfigError) {
      logStderr(`mailcue-mcp: ${err.message}`);
      process.exit(1);
    }
    throw err;
  }

  const server = buildServer(config);
  const transport = new StdioServerTransport();
  await server.connect(transport);

  const scope = isLocked(config) ? `locked to ${config.mailbox}` : 'multi-mailbox';
  logStderr(`mailcue-mcp ready on stdio — ${config.baseUrl} (${scope})`);
}

main().catch((err) => {
  logStderr(`mailcue-mcp: fatal: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
