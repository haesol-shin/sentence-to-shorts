import type { Language } from '@/shared/api/client';

/** The three settled speech levels in the script document head. */
export type Register = 'friendly' | 'neutral' | 'casual';

export type TargetDuration = 30 | 60 | 120;

/** The backend stages the script gate moves between (CONTRACTS 4.1). */
export type ScriptStage = 'draft' | 'concept_confirmed' | 'script_confirmed' | 'scenes_confirmed';

export type ScriptDraftState = 'pending' | 'ready' | 'failed';

/**
 * One spoken line. The screen writes the same value to `display_text` and
 * `speech_text`, so the caption and the voice never drift apart (contract:
 * Scene.lines owns the text; Script keeps only the source text).
 */
export interface ScriptLine {
  id: string;
  display_text: string;
  speech_text: string;
}

export interface ScriptScene {
  id: string;
  beat_id: string;
  beat_label: string;
  lines: ScriptLine[];
}

export interface ScriptDocument {
  id: string;
  revision: number;
  topic: string;
  stage: ScriptStage;
  script: {
    title: string | null;
    raw_text: string | null;
    source: 'user' | 'llm';
  };
  register: Register;
  target_duration_s: TargetDuration;
  scene_order: string[];
  scenes: Record<string, ScriptScene>;
  /** The language of the video, not of the interface. */
  language: Language;
}

/** One line before and after a tone change. */
export interface ToneLineReview {
  lineId: string;
  before: string;
  after: string;
}

export interface ToneSceneReview {
  sceneId: string;
  lines: ToneLineReview[];
}

/** The whole document in another speech level, waiting for a decision. */
export interface ToneProposal {
  from: Register;
  to: Register;
  scenes: ToneSceneReview[];
}

/** The rewritten lines of one scene, waiting for a decision in that scene. */
export interface RewriteProposal {
  sceneId: string;
  before: string[];
  after: string[];
}

export interface UndoEntry {
  document: ScriptDocument;
  changedSceneIds: string[];
  /** The line a run of typing changed, or `null` for any other change. */
  line: string | null;
}

export interface ScriptSnapshot {
  document: ScriptDocument;
  busy: boolean;
  error: string | null;
  targetSceneId: string | null;
  workingSceneId: string | null;
  rewrite: RewriteProposal | null;
  tone: ToneProposal | null;
  changedSceneIds: string[];
  highlightedSceneId: string | null;
  /** Bumped on every jump request so the same scene scrolls again. */
  focusToken: number;
  totalSeconds: number;
  canUndo: boolean;
  confirmed: boolean;
  /** The reason the next action stays shut, as a locale key. */
  nextBlockedReason: string | null;
}

/** The video a script screen belongs to; the screen opens a session per video. */
export interface ScriptTarget {
  id: string | null;
  topic: string | null;
  /** The user's original script, unchanged; absent for the synthetic mock. */
  script: string | null;
}
