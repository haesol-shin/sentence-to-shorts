import { useEffect, useState } from 'react';

import {
  clearSession,
  pairSession,
  refreshSession,
  type Language,
} from '@/shared/api/client';

export type SessionState = 'pending' | 'ready' | 'missing';

export interface SessionResult {
  state: SessionState;
  /** The language the pairing answer asked for, before the user picks one. */
  uiLanguage: Language | null;
}

const PAIR_CODE = /^[A-Za-z0-9_-]{16,64}$/u;

/** Reads `#pair=<code>` and ignores a fragment that is not a code. */
export function pairCodeFromHash(hash: string): string | null {
  const code = new URLSearchParams(hash.replace(/^#/u, '')).get('pair');
  return code !== null && PAIR_CODE.test(code) ? code : null;
}

function stripPairFragment(): void {
  const { pathname, search } = window.location;
  window.history.replaceState(null, '', `${pathname}${search}`);
}

let inflight: Promise<SessionResult> | null = null;

async function bootstrap(): Promise<SessionResult> {
  const code = pairCodeFromHash(window.location.hash);
  if (code !== null) {
    try {
      const paired = await pairSession(code);
      // The fragment never reaches the server log or a Referer (CONTRACTS 13.2).
      stripPairFragment();
      return { state: 'ready', uiLanguage: paired.ui_language };
    } catch {
      return { state: 'missing', uiLanguage: null };
    }
  }
  try {
    await refreshSession();
    return { state: 'ready', uiLanguage: null };
  } catch {
    return { state: 'missing', uiLanguage: null };
  }
}

/**
 * Pairs once per tab. React runs effects twice in development, so both mounts
 * share one promise and the one-time code is spent only once.
 */
export function ensureSession(): Promise<SessionResult> {
  inflight ??= bootstrap();
  return inflight;
}

export function resetSession(): void {
  inflight = null;
  clearSession();
}

export function useSession(): SessionResult {
  const [result, setResult] = useState<SessionResult>({ state: 'pending', uiLanguage: null });

  useEffect(() => {
    let active = true;
    void ensureSession().then((next) => {
      if (active) {
        setResult(next);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  return result;
}
