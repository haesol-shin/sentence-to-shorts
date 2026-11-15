import { useEffect, useState } from 'react';

import { getJson, type RuntimeStatus } from '@/shared/api/client';

export interface BrandResult {
  brand: RuntimeStatus['brand'] | null;
  failed: boolean;
}

export function useBrand(): BrandResult {
  const [brand, setBrand] = useState<RuntimeStatus['brand'] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    getJson<RuntimeStatus>('/runtime', controller.signal)
      .then((runtime) => setBrand(runtime.brand))
      .catch(() => {
        if (!controller.signal.aborted) {
          setFailed(true);
        }
      });

    return () => controller.abort();
  }, []);

  return { brand, failed };
}
