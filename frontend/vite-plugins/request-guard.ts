import type { ViteDevServer } from 'vite';

/** The one boundary around the gallery's local edit mode. */

export type ServerAddress = {
  /** Vite's `server.host`: a name, `true` for all interfaces, or undefined. */
  host: string | boolean | undefined;
  port: number | undefined;
  https: boolean;
};

export type WriteGuard = {
  edit: boolean;
  remoteAddress: string | undefined;
  origin: string | undefined;
  host: string | undefined;
  approvedOrigins: readonly string[];
};

export type EditGuard = {
  edit: boolean;
  remoteAddress: string | undefined;
  referer: string | undefined;
  approvedOrigins: readonly string[];
};

export function isLoopback(address: string | undefined): boolean {
  if (address === undefined) return false;
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1';
}

function isLoopbackHost(host: string): boolean {
  return host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '[::1]';
}

/**
 * The origins the server itself was opened on. A server exposed on all
 * interfaces or on a named non-loopback host has no writable origin.
 */
export function approvedOrigins(address: ServerAddress): string[] {
  if (address.port === undefined) return [];
  if (address.host === true) return [];
  if (typeof address.host === 'string' && !isLoopbackHost(address.host)) return [];
  const scheme = address.https ? 'https' : 'http';
  return [
    `${scheme}://127.0.0.1:${address.port}`,
    `${scheme}://localhost:${address.port}`,
    `${scheme}://[::1]:${address.port}`,
  ];
}

/**
 * A write needs the explicit local edit mode, a loopback connection, an
 * `Origin` the server was opened on, and a matching `Host` header. Comparing
 * only the request `Host` is not enough because the caller controls it.
 */
export function canWriteCopy(guard: WriteGuard): boolean {
  if (!guard.edit || !isLoopback(guard.remoteAddress)) return false;
  if (guard.origin === undefined || guard.host === undefined) return false;
  if (!guard.approvedOrigins.includes(guard.origin)) return false;
  try {
    return new URL(guard.origin).host === guard.host;
  } catch {
    return false;
  }
}

/** The read-only indicator uses the page's browser-set Referer and the same origins. */
export function canEditCopy(guard: EditGuard): boolean {
  if (!guard.edit || !isLoopback(guard.remoteAddress)) return false;
  if (guard.referer === undefined) return false;
  try {
    return guard.approvedOrigins.includes(new URL(guard.referer).origin);
  } catch {
    return false;
  }
}

/** The address a running Vite server actually bound, for the approved origins. */
export function serverAddressOf(server: ViteDevServer): ServerAddress {
  const bound = server.httpServer?.address();
  const port = bound !== null && typeof bound === 'object' ? bound.port : server.config.server.port;
  return {
    host: server.config.server.host,
    port,
    https: server.config.server.https !== undefined,
  };
}
