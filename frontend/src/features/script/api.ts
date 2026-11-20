import type { Language } from '@/shared/api/client';

import { createSyntheticDocument } from './fixture';
import {
  buildRewriteProposal,
  cloneDocument,
  firstTooLongLine,
  hasDuplicateOrder,
  hasEmptyLine,
  isConfirmed,
} from './model';
import type { ScriptDocument, ScriptTarget } from './types';

/** The rewrite takes long enough that the stop control can be pressed. */
const REWRITE_DELAY_MS = 2500;

export type ScriptApiErrorCode =
  | 'cancelled'
  | 'duplicate_order'
  | 'script_invalid'
  | 'script_missing'
  | 'script_not_confirmed'
  | 'revision_conflict';

export class ScriptApiError extends Error {
  constructor(
    readonly code: ScriptApiErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'ScriptApiError';
  }
}

export type ScriptRequestMethod = 'open' | 'rewrite' | 'cancel' | 'confirm' | 'previews';

export interface ScriptRequest {
  method: ScriptRequestMethod;
  sceneId?: string;
}

export interface ScriptApi {
  open(language: Language, target?: ScriptTarget): Promise<ScriptDocument>;
  rewrite(
    document: ScriptDocument,
    sceneId: string,
    options?: { signal?: AbortSignal; attempt?: number },
  ): Promise<string[]>;
  confirm(document: ScriptDocument): Promise<ScriptDocument>;
  /** The edit step asks for scene previews only after this gate opens. */
  requestPreviews(document: ScriptDocument): Promise<void>;
}

export interface MockScriptApiOptions {
  rewriteDelayMs?: number;
}

/**
 * The screen's API boundary, like the concept screen's: a mock that records
 * what a real transport would send. A production implementation replaces this
 * object; the screen never speaks a second transport.
 */
export class MockScriptApi implements ScriptApi {
  readonly requests: ScriptRequest[] = [];

  private readonly rewriteDelayMs: number;

  constructor(options: MockScriptApiOptions = {}) {
    this.rewriteDelayMs = Math.max(0, options.rewriteDelayMs ?? REWRITE_DELAY_MS);
  }

  count(method: ScriptRequestMethod): number {
    return this.requests.filter((request) => request.method === method).length;
  }

  open(
    language: Language,
    target: ScriptTarget = { id: null, topic: null, script: null },
  ): Promise<ScriptDocument> {
    this.record('open');
    return Promise.resolve(createSyntheticDocument(language, target));
  }

  rewrite(
    document: ScriptDocument,
    sceneId: string,
    options: { signal?: AbortSignal; attempt?: number } = {},
  ): Promise<string[]> {
    this.record('rewrite', sceneId);
    const proposal = buildRewriteProposal(document, sceneId, options.attempt ?? 0);
    if (proposal === null) {
      return Promise.reject(new ScriptApiError('revision_conflict', 'Unknown scene'));
    }
    return this.wait(options.signal).then(() => proposal.after);
  }

  confirm(document: ScriptDocument): Promise<ScriptDocument> {
    this.record('confirm');
    if (document.scene_order.length === 0) {
      return Promise.reject(new ScriptApiError('script_missing', 'The script has no scenes'));
    }
    if (hasDuplicateOrder(document)) {
      return Promise.reject(
        new ScriptApiError('duplicate_order', 'The scene order repeats a scene'),
      );
    }
    if (hasEmptyLine(document)) {
      return Promise.reject(new ScriptApiError('script_invalid', 'A line has no text'));
    }
    const tooLong = firstTooLongLine(document);
    if (tooLong !== null) {
      return Promise.reject(
        new ScriptApiError('script_invalid', 'A line is longer than the contract limit'),
      );
    }
    if (isConfirmed(document)) {
      return Promise.resolve(cloneDocument(document));
    }
    const next = cloneDocument(document);
    next.stage = 'script_confirmed';
    next.revision += 1;
    return Promise.resolve(next);
  }

  requestPreviews(document: ScriptDocument): Promise<void> {
    if (!isConfirmed(document)) {
      return Promise.reject(
        new ScriptApiError('script_not_confirmed', 'Confirm the script before previews'),
      );
    }
    this.record('previews');
    return Promise.resolve();
  }

  private wait(signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted === true) {
        this.record('cancel');
        reject(new ScriptApiError('cancelled', 'The rewrite stopped'));
        return;
      }
      const timer = setTimeout(() => {
        finish();
        resolve();
      }, this.rewriteDelayMs);
      const onAbort = () => {
        finish();
        this.record('cancel');
        reject(new ScriptApiError('cancelled', 'The rewrite stopped'));
      };
      const finish = () => {
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
      };
      signal?.addEventListener('abort', onAbort, { once: true });
    });
  }

  private record(method: ScriptRequestMethod, sceneId?: string): void {
    this.requests.push(sceneId === undefined ? { method } : { method, sceneId });
  }
}

export function createMockScriptApi(options: MockScriptApiOptions = {}): MockScriptApi {
  return new MockScriptApi(options);
}
