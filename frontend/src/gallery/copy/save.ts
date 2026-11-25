/** The editor talks to the dev endpoint; the endpoint keeps the response shape. */

import { isRecord } from './guard';

export type SaveResponse =
  | { ok: true; ko: string; en: string; koHash: string; enHash: string }
  | {
      ok: false;
      errors: { message: string }[];
      ko?: string;
      en?: string;
      koHash?: string;
      enHash?: string;
    };

export type SaveRequest = {
  namespace: string;
  key: string;
  ko: string;
  en: string;
  baseKo: string;
  baseEn: string;
  baseHashKo: string;
  baseHashEn: string;
};

function messageList(value: unknown): { message: string }[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const messages: { message: string }[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.message !== 'string') return null;
    messages.push({ message: item.message });
  }
  return messages;
}

export async function saveCopy(request: SaveRequest): Promise<SaveResponse> {
  let body: unknown;
  try {
    const response = await fetch('/__copy/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    body = await response.json();
  } catch {
    return { ok: false, errors: [{ message: '연결을 확인하지 못했어요. 다시 시도해 주세요.' }] };
  }
  if (isRecord(body)) {
    if (
      body.ok === true &&
      typeof body.ko === 'string' &&
      typeof body.en === 'string' &&
      typeof body.koHash === 'string' &&
      typeof body.enHash === 'string'
    ) {
      return { ok: true, ko: body.ko, en: body.en, koHash: body.koHash, enHash: body.enHash };
    }
    const errors = messageList(body.errors);
    if (errors !== null) {
      const values = {
        ko: typeof body.ko === 'string' ? body.ko : undefined,
        en: typeof body.en === 'string' ? body.en : undefined,
        koHash: typeof body.koHash === 'string' ? body.koHash : undefined,
        enHash: typeof body.enHash === 'string' ? body.enHash : undefined,
      };
      return { ok: false, errors, ...values };
    }
  }
  return { ok: false, errors: [{ message: '저장에 실패했어요. 다시 시도해 주세요.' }] };
}
