import type { components } from '@/shared/api/generated/openapi';

export type Settings = components['schemas']['Settings'];
export type Plan = components['schemas']['ChangePlan'];
export type StyleManifest = components['schemas']['StyleManifest'];
export type PinnedRef = components['schemas']['PinnedRef'];
export type Origin = components['schemas']['Origin'];
export type LockKey = components['schemas']['LockKey'];
export type Character = components['schemas']['CharacterSpec'];
export type Slot = keyof Character['slots'];
export type SetOp = components['schemas']['SetOp'];

/**
 * The four values a story card owns. They live beside the card, so switching
 * cards carries that card's values and leaves the other cards' values alone.
 */
export interface CardTune {
  layout: PinnedRef;
  role: Settings['format']['character_role'];
  register: Settings['format']['register'];
  humor: Settings['format']['humor'];
}

export interface Attachment {
  id: string;
  kind: 'text' | 'reference' | 'bgm' | 'link';
  name: string;
  file?: File;
  text?: string;
  url?: string;
  durationMs?: number;
  state: 'ready' | 'receiving' | 'failed';
}

export interface ConceptCatalog {
  styles: { ref: PinnedRef; manifest: StyleManifest }[];
  layouts: { ref: PinnedRef; dialogBox: boolean }[];
  /** Pinned font manifests for the caption selector. */
  fonts?: PinnedRef[];
}

export interface ConceptDocument {
  id: string;
  projectId: string;
  revision: number;
  topic: string;
  confirmed: boolean;
  settings: Settings;
  attachments: Attachment[];
}

export interface ConceptResult {
  plan: Plan | null;
  notes: string[];
  unsupported: string[];
  /** The newest revision the server holds once the job has ended. */
  revision?: number;
  /** The materials the server holds once the job has ended. */
  attachments?: Attachment[];
}

export interface ConceptJob {
  id: string;
  kind: 'style' | 'reference' | 'bgm_upload' | 'chat';
  state: 'queued' | 'running' | 'succeeded' | 'failed';
  result?: ConceptResult;
}

export interface ConceptSnapshot {
  document: ConceptDocument;
  catalog: ConceptCatalog | null;
  loading: boolean;
  busy: boolean;
  error: string | null;
  pending: Plan | null;
  notes: string[];
  unsupported: string[];
  job: ConceptJob | null;
  draft: string;
  canUndo: boolean;
  /** Values remembered for the cards that are not selected. */
  cardTunes: Record<string, CardTune>;
  /** The values the first concept reply names, frozen before the user edits. */
  opening: Settings;
  /** Settings paths the draft filled, for the one-time changed highlight. */
  draftChanged: string[];
}
