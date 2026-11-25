/* global process */
/**
 * Starts Vite with the local copy edit mode. A wrapper keeps the env flag and
 * the open URL out of shell quoting, so `npm run dev` and `npm run copy` behave
 * the same on cmd.exe and a POSIX shell.
 */
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { signalExitCode } from './exit-code.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const vite = join(here, '..', 'node_modules', 'vite', 'bin', 'vite.js');
const child = spawn(process.execPath, [vite, ...process.argv.slice(2)], {
  stdio: 'inherit',
  env: { ...process.env, APP_COPY_EDIT: '1' },
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    child.kill(signal);
  });
}

child.on('exit', (code, signal) => {
  process.exit(signal === null ? (code ?? 1) : signalExitCode(signal));
});
