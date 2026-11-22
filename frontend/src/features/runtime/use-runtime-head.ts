import { useCallback, useEffect, useState } from 'react';

import { getJson, saveLlmCredential, type RuntimeStatus } from '@/shared/api/client';

type LlmAuthState = RuntimeStatus['llm_auth']['state'];

export interface LlmKey {
  /** The release profile asks the user for their own key; dev and fixture never do. */
  release: boolean;
  /** The server holds no usable key: `missing` or `expired`. */
  needed: boolean;
  /** Stores the key, reads `/runtime` again and answers the state that read shows. */
  save: (apiKey: string) => Promise<LlmAuthState>;
}

export interface RuntimeHead {
  brand: RuntimeStatus['brand'] | null;
  llmKey: LlmKey;
}

interface Reading {
  brand: RuntimeStatus['brand'];
  release: boolean;
  state: LlmAuthState;
}

function readingOf(runtime: RuntimeStatus): Reading {
  return { brand: runtime.brand, release: runtime.profile === 'release', state: runtime.llm_auth.state };
}

/**
 * Reads the display name, the profile and the LLM key state from one
 * `GET /runtime`, once the session is up. A read that never answered shows
 * nothing and no key entry: the refusal then shows as the ordinary error.
 */
export function useRuntimeHead(ready: boolean): RuntimeHead {
  const [reading, setReading] = useState<Reading | null>(null);

  useEffect(() => {
    if (!ready) return undefined;
    const controller = new AbortController();
    getJson<RuntimeStatus>('/runtime', controller.signal)
      .then((runtime) => {
        if (!controller.signal.aborted) setReading(readingOf(runtime));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [ready]);

  const save = useCallback(async (apiKey: string): Promise<LlmAuthState> => {
    await saveLlmCredential(apiKey);
    const next = readingOf(await getJson<RuntimeStatus>('/runtime'));
    setReading(next);
    return next.state;
  }, []);

  return {
    brand: reading?.brand ?? null,
    llmKey: {
      release: reading?.release ?? false,
      needed: reading !== null && (reading.state === 'missing' || reading.state === 'expired'),
      save,
    },
  };
}
