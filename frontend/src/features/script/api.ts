import type { Language } from '@/shared/api/client';
import { confirmedMockScripts } from '@/shared/api/mock/story';

import { createSyntheticDocument } from './fixture';
import {
  buildRewriteProposal,
  cloneDocument,
  firstTooLongLine,
  hasDuplicateOrder,
  hasEmptyLine,
  isConfirmed,
  maxEntityNumber,
} from './model';
import type { RewriteResult, ScriptDocument, ScriptTarget } from './types';

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
    options?: { signal?: AbortSignal; instruction?: string },
  ): Promise<RewriteResult>;
  confirm(document: ScriptDocument): Promise<ScriptDocument>;
  /** Adopt settings the conversation changed elsewhere, keeping the unsaved lines. */
  sync?(document: ScriptDocument): Promise<ScriptDocument>;
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
    options: { signal?: AbortSignal; instruction?: string } = {},
  ): Promise<RewriteResult> {
    this.record('rewrite', sceneId);
    const proposal = buildRewriteProposal(document, sceneId);
    if (proposal === null) {
      return Promise.reject(new ScriptApiError('revision_conflict', 'Unknown scene'));
    }
    const instruction = options.instruction?.trim() ?? '';
    return this.wait(options.signal).then(() => {
      if (instruction === '') return { lines: proposal.after, unsupported: [] };
      if (/짧|short/u.test(instruction)) {
        return {
          lines: document.scenes[sceneId].lines.map((line) => {
            const words = line.display_text.split(/\s+/u);
            const text = words.slice(0, Math.ceil(words.length / 2)).join(' ');
            return { ...line, display_text: text, speech_text: text };
          }),
          unsupported: [],
        };
      }
      return {
        lines: null,
        unsupported: [document.language === 'ko'
          ? (/순서|order/u.test(instruction)
            ? '장면 순서는 전체 대본에 속해요. 장면 카드를 끌어 순서를 바꿔 주세요.'
            : '장면 대화에서는 문장만 고칠 수 있어요. 대사나 장면 설정을 화면에서 직접 고쳐 주세요.')
          : (/순서|order/u.test(instruction)
            ? 'Scene order belongs to the whole script. Drag the scene cards to reorder them.'
            : 'Scene chat only edits lines. Make other changes in the scene settings instead.')],
      };
    });
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
    // The mock video read lays this over its story, so the edit step opens on
    // the confirmed order and lines. A session id is `<video id>#<attempt>`, and
    // a seeded scene's number is its place in the story.
    confirmedMockScripts.set(
      document.id.split('#')[0] ?? document.id,
      document.scene_order.map((sceneId) => ({
        story: maxEntityNumber([sceneId], 's') - 1,
        lines: document.scenes[sceneId]?.lines.map((line) => line.display_text) ?? [],
      })),
    );
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
