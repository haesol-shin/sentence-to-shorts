import {
  MAX_TEXT_ATTACHMENTS,
  linkPolicy,
  readTextFile,
  validateReferenceUrl,
  type Deployment,
} from './attachments';
import {
  CONCEPT_LOCK_KEYS,
  DEFAULT_CHARACTER,
  DEFAULT_FONT_REF,
  LAYOUT_REFS,
  PIXEL_REF,
  applySettingsOps,
  changeCard,
  chatProposal,
  cloneSettings,
  getSettingsValue,
  normalizeDuration,
  planImpact,
  planTouchesLockedFields,
  recommendedSceneCount,
  referenceProposal,
  validateConcept,
} from './model';
import type {
  Attachment,
  ConceptCatalog,
  ConceptDocument,
  ConceptJob,
  ConceptResult,
  PinnedRef,
  Plan,
  Settings,
  SetOp,
  StyleManifest,
} from './types';

export type { Deployment } from './attachments';

interface FixtureFile {
  response: {
    body: unknown;
  };
}

const fixtureModules = import.meta.glob(
  '../../../../fixtures/api/{createVideo,confirmConcept,getCatalogItem}.json',
  { eager: true },
) as Record<string, { default: FixtureFile }>;

function fixtureBody(name: string): unknown {
  const entry = Object.entries(fixtureModules).find(([path]) => path.endsWith(`/fixtures/api/${name}.json`));
  if (entry === undefined) {
    throw new Error(`Missing fixture: ${name}`);
  }
  return entry[1].default.response.body;
}

function isSettingsBody(value: unknown): value is { settings: Settings } {
  return value !== null && typeof value === 'object' && 'settings' in value;
}

const createVideoBody = fixtureBody('createVideo');
const confirmConceptBody = fixtureBody('confirmConcept');
if (!isSettingsBody(createVideoBody) || !isSettingsBody(confirmConceptBody)) {
  throw new Error('Fixture settings are missing');
}
const FIXTURE_SETTINGS = createVideoBody.settings;
const PIXEL_MANIFEST = fixtureBody('getCatalogItem') as StyleManifest;
const CONFIRM_SETTINGS = confirmConceptBody.settings;
const NOW = '2026-01-01T00:00:00Z';

const FONTS: PinnedRef[] = [
  DEFAULT_FONT_REF,
  {
    id: 'galmuri14',
    revision: '355a558936b62908cc39828c605dc2d5c2f5ac4c149c48114b725f61cf9d105f',
  },
];

const ORIGIN_PATHS = [
  '/language',
  '/target_duration_s',
  '/format/card_id',
  '/format/story_structure',
  '/format/layout',
  '/format/character_role',
  '/format/register',
  '/format/humor',
  '/format/progress_mode',
  '/format/scene_count',
  '/visual/art_style',
  '/visual/theme_id',
  '/visual/character',
  '/caption/mode',
  '/caption/font_id',
  '/caption/position',
  '/caption/highlight',
  '/audio/bgm/enabled',
  '/audio/bgm/mood',
  '/audio/bgm/gain_db_x10',
  '/audio/bgm/ducking',
  '/audio/sfx_enabled',
  '/motion/transition',
  '/motion/character_motion',
];

export class ConceptApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, status: number, message: string) {
    super(message);
    this.name = 'ConceptApiError';
    this.code = code;
    this.status = status;
  }
}

export interface ConceptStartInput {
  topic: string;
  cardId?: string | null;
  language?: 'ko' | 'en';
  duration?: number;
  attachments?: Attachment[];
}

export interface ConceptApplyResult {
  document: ConceptDocument;
  plan: Plan;
}

export interface ConceptApi {
  deployment(): Promise<Deployment>;
  catalog(): Promise<ConceptCatalog>;
  create(input: ConceptStartInput): Promise<ConceptDocument>;
  load(videoId: string): Promise<ConceptDocument>;
  save(videoId: string, settings: Settings): Promise<ConceptDocument>;
  confirm(videoId: string, baseRevision: number): Promise<ConceptDocument>;
  message(videoId: string, text: string, attachments: Attachment[]): Promise<ConceptJob>;
  submitStyle(videoId: string, prompt: string, attachment?: Attachment): Promise<ConceptJob>;
  submitReference(videoId: string, attachment: Attachment): Promise<ConceptJob>;
  getJob(jobId: string): Promise<ConceptJob>;
  applyPlan(videoId: string, planId: string, baseRevision: number): Promise<ConceptApplyResult>;
  rejectPlan(videoId: string, planId: string): Promise<Plan>;
}

export type ConceptRequestMethod =
  | 'deployment'
  | 'catalog'
  | 'create'
  | 'load'
  | 'save'
  | 'confirm'
  | 'message'
  | 'submitStyle'
  | 'submitReference'
  | 'getJob'
  | 'applyPlan'
  | 'rejectPlan'
  | 'bgm_upload';

export interface ConceptRequest {
  method: ConceptRequestMethod;
  videoId?: string;
  projectId?: string;
  kind?: string;
  payload: Record<string, unknown>;
}

export interface MockConceptApiOptions {
  jobPolls?: number;
  deployment?: Deployment;
}

interface GeneratedStyle {
  ref: PinnedRef;
  manifest: StyleManifest;
}

interface MockJob {
  job: ConceptJob;
  videoId: string;
  polls: number;
  complete: () => ConceptResult;
}

interface StoredPlan {
  plan: Plan;
  appliedDocument: ConceptDocument | null;
}

function localized(language: 'ko' | 'en', ko: string, en: string): string {
  return language === 'ko' ? ko : en;
}

function syntheticDigest(seed: string): string {
  let output = '';
  for (let round = 0; round < 8; round += 1) {
    let value = 0x811c9dc5;
    for (const char of `${seed}:${round}`) {
      value ^= char.codePointAt(0) ?? 0;
      value = Math.imul(value, 0x01000193) >>> 0;
    }
    output += value.toString(16).padStart(8, '0');
  }
  return output;
}

function cloneDocument(document: ConceptDocument): ConceptDocument {
  return JSON.parse(JSON.stringify(document)) as ConceptDocument;
}

function clonePlan(plan: Plan): Plan {
  return JSON.parse(JSON.stringify(plan)) as Plan;
}

function cloneJob(job: ConceptJob): ConceptJob {
  return JSON.parse(JSON.stringify(job)) as ConceptJob;
}

function serializeAttachment(attachment: Attachment): Record<string, unknown> {
  return {
    id: attachment.id,
    kind: attachment.kind,
    name: attachment.name,
    text: attachment.text,
    url: attachment.url,
    durationMs: attachment.durationMs,
    state: attachment.state,
    file: attachment.file === undefined
      ? undefined
      : { name: attachment.file.name, size: attachment.file.size, type: attachment.file.type },
  };
}

function initialSettings(
  language: 'ko' | 'en',
  duration: number,
  catalog: ConceptCatalog | null,
): Settings {
  const settings = cloneSettings(FIXTURE_SETTINGS);
  settings.language = language;
  settings.target_duration_s = duration as 30 | 60 | 120;
  settings.format = {
    ...settings.format,
    card_id: null,
    story_structure: 'numbered_three',
    layout: LAYOUT_REFS.fixed_stage,
    character_role: 'presenter',
    register: 'friendly',
    humor: 'none',
    progress_mode: 'numbered',
    scene_count: recommendedSceneCount(duration),
  };
  settings.visual = {
    ...settings.visual,
    art_style: PIXEL_REF,
    theme_id: 'day',
    character: {
      preset_id: null,
      slots: { ...DEFAULT_CHARACTER.slots },
    },
  };
  settings.caption = {
    ...settings.caption,
    mode: 'sentence',
    font_id: catalog?.fonts?.[0] ?? DEFAULT_FONT_REF,
    position: 'bottom',
    highlight: true,
  };
  settings.locks = Object.fromEntries(
    CONCEPT_LOCK_KEYS.map((key) => [key, 'varied']),
  ) as unknown as Settings['locks'];
  settings.origins = Object.fromEntries(
    ORIGIN_PATHS.map((path) => [path, 'default']),
  ) as unknown as Settings['origins'];
  settings.extra_instructions = [];
  return settings;
}

function effectiveOps(settings: Settings, ops: readonly SetOp[]): SetOp[] {
  return ops.filter(
    (op) =>
      JSON.stringify(getSettingsValue(settings, op.path)) !== JSON.stringify(op.value),
  );
}

function unsupportedText(language: 'ko' | 'en', key: string): string {
  const messages: Record<string, { ko: string; en: string }> = {
    'concept.reason.characterNoneWithParts': {
      ko: '캐릭터를 쓰지 않기로 한 설정과 부위가 맞지 않아요.',
      en: 'The selected character parts need a character role.',
    },
    'concept.reason.characterMissing': {
      ko: '이 역할에는 캐릭터 몸과 얼굴이 필요해요.',
      en: 'This role needs a character body and face.',
    },
    'concept.reason.typewriterNeedsDialog': {
      ko: '타자기 자막은 대화창 화면 틀에서만 쓸 수 있어요.',
      en: 'Typewriter captions need a dialog-stage layout.',
    },
    'concept.reason.unknownAsset': {
      ko: '이 그림체에 없는 부위가 있어 대체안을 확인해야 해요.',
      en: 'This style lacks some selected parts; review the replacements.',
    },
    'concept.reason.unknownStyle': {
      ko: '요청한 그림체를 찾지 못했어요.',
      en: 'I could not find that drawing style.',
    },
    'concept.reason.unknownTheme': {
      ko: '이 그림체에 없는 테마예요.',
      en: 'That theme is not part of this style.',
    },
    'concept.reason.unknownLayout': {
      ko: '요청한 화면 틀을 찾지 못했어요.',
      en: 'I could not find that layout.',
    },
    'concept.reason.unknownFont': {
      ko: '요청한 글꼴을 찾지 못했어요.',
      en: 'I could not find that font.',
    },
    'concept.reason.weakCombination': {
      ko: '이 조합은 가능하지만 어울리지 않을 수 있어요.',
      en: 'This combination works but may not fit well.',
    },
    'concept.reason.invalidValue': {
      ko: '이 요청은 컨셉 값으로 바꿀 수 없어요.',
      en: 'This request does not map to a concept value.',
    },
  };
  return localized(language, messages[key]?.ko ?? key, messages[key]?.en ?? key);
}

export class MockConceptApi implements ConceptApi {
  readonly requests: ConceptRequest[] = [];
  readonly sessions = new Map<string, ConceptDocument>();
  readonly jobs = new Map<string, MockJob>();
  readonly plans = new Map<string, StoredPlan>();
  readonly generatedStyles: GeneratedStyle[] = [];
  failCatalog = false;

  private readonly jobPolls: number;
  private readonly deploymentMode: Deployment;
  private sequence = 0;

  constructor(options: MockConceptApiOptions = {}) {
    this.jobPolls = Math.max(1, options.jobPolls ?? 2);
    this.deploymentMode = options.deployment ?? 'local';
  }

  deployment(): Promise<Deployment> {
    this.record('deployment', { payload: {} });
    return Promise.resolve(this.deploymentMode);
  }

  catalog(): Promise<ConceptCatalog> {
    this.record('catalog', { payload: {} });
    if (this.failCatalog) {
      return Promise.reject(new ConceptApiError('internal', 503, 'Catalog unavailable'));
    }
    return Promise.resolve(this.catalogValue());
  }

  catalogValue(): ConceptCatalog {
    const fullLayout = CONFIRM_SETTINGS.format.layout.id === 'full_stage'
      ? CONFIRM_SETTINGS.format.layout
      : LAYOUT_REFS.full_stage;
    const catalog: ConceptCatalog = {
      styles: [
        { ref: PIXEL_REF, manifest: PIXEL_MANIFEST },
        ...this.generatedStyles,
      ],
      layouts: [
        { ref: LAYOUT_REFS.fixed_stage, dialogBox: false },
        { ref: fullLayout, dialogBox: false },
        { ref: LAYOUT_REFS.dialog_stage, dialogBox: true },
      ],
      fonts: FONTS,
    };
    return JSON.parse(JSON.stringify(catalog)) as ConceptCatalog;
  }

  async create(input: ConceptStartInput): Promise<ConceptDocument> {
    const topic = input.topic.trim();
    if (topic === '') {
      throw new ConceptApiError('validation_failed', 400, 'Topic is required');
    }
    const language = input.language ?? 'ko';
    const duration = normalizeDuration(input.duration);
    let settings = initialSettings(language, duration, this.catalogValue());
    if (input.cardId !== undefined && input.cardId !== null) {
      const applied = changeCard(settings, input.cardId, duration, this.catalogValue());
      if (applied.kind === 'invalid') {
        throw new ConceptApiError('invalid_combination', 422, applied.issue.key);
      }
      if (applied.kind === 'replacement') {
        throw new ConceptApiError('invalid_combination', 422, 'Card needs replacements');
      }
      settings = applied.settings;
    }
    const attachments = await this.normalizeAttachments(input.attachments ?? []);
    const id = this.nextId('v');
    const projectId = this.nextId('p');
    const document: ConceptDocument = {
      id,
      projectId,
      revision: 1,
      topic,
      confirmed: false,
      settings,
      attachments: [],
    };
    if (this.textCount(document.attachments, attachments) > MAX_TEXT_ATTACHMENTS) {
      throw new ConceptApiError('material_limit', 422, 'At most five text materials');
    }
    document.attachments = this.appendAttachments(document.attachments, attachments);
    this.sessions.set(id, document);
    this.record('create', {
      projectId,
      payload: {
        topic,
        cardId: input.cardId ?? null,
        language,
        duration,
        attachments: attachments.map(serializeAttachment),
      },
    });
    return cloneDocument(document);
  }

  load(videoId: string): Promise<ConceptDocument> {
    this.record('load', { videoId, payload: {} });
    return Promise.resolve(cloneDocument(this.requireDocument(videoId)));
  }

  save(videoId: string, settings: Settings): Promise<ConceptDocument> {
    this.record('save', { videoId, payload: { settings: cloneSettings(settings) } });
    const document = this.requireDocument(videoId);
    if (document.confirmed) {
      const changedConcept =
        document.settings.format.story_structure !== settings.format.story_structure ||
        document.settings.format.card_id !== settings.format.card_id ||
        document.settings.format.character_role !== settings.format.character_role ||
        JSON.stringify(document.settings.visual.art_style) !== JSON.stringify(settings.visual.art_style) ||
        JSON.stringify(document.settings.visual.character) !== JSON.stringify(settings.visual.character);
      if (changedConcept) {
        throw new ConceptApiError('concept_locked', 409, 'The concept is confirmed');
      }
    }
    const validation = validateConcept(settings, this.catalogValue());
    if (!validation.ok) {
      throw new ConceptApiError('invalid_combination', 422, validation.blocked[0].key);
    }
    document.settings = cloneSettings(settings);
    document.revision += 1;
    return Promise.resolve(cloneDocument(document));
  }

  confirm(videoId: string, baseRevision: number): Promise<ConceptDocument> {
    this.record('confirm', { videoId, payload: { base_revision: baseRevision } });
    const document = this.requireDocument(videoId);
    if (document.confirmed) {
      return Promise.resolve(cloneDocument(document));
    }
    if (document.revision !== baseRevision) {
      throw new ConceptApiError('revision_conflict', 409, 'Revision conflict');
    }
    const validation = validateConcept(document.settings, this.catalogValue());
    if (!validation.ok) {
      throw new ConceptApiError('invalid_combination', 422, validation.blocked[0].key);
    }
    document.confirmed = true;
    document.revision += 1;
    return Promise.resolve(cloneDocument(document));
  }

  async message(videoId: string, text: string, attachments: Attachment[]): Promise<ConceptJob> {
    const document = this.requireDocument(videoId);
    const normalized = await this.normalizeAttachments(attachments);
    if (text.trim() === '' && normalized.length === 0) {
      throw new ConceptApiError('validation_failed', 400, 'Message is empty');
    }
    if (this.textCount(document.attachments, normalized) > MAX_TEXT_ATTACHMENTS) {
      throw new ConceptApiError('material_limit', 422, 'At most five text materials');
    }
    document.attachments = this.appendAttachments(document.attachments, normalized);

    const bgm = normalized.filter((attachment) => attachment.kind === 'bgm');
    const references = normalized.filter(
      (attachment) => attachment.kind === 'reference' || attachment.kind === 'link',
    );
    for (const attachment of bgm) {
      this.record('bgm_upload', {
        videoId,
        projectId: document.projectId,
        kind: 'bgm_upload',
        payload: { attachment: serializeAttachment(attachment) },
      });
    }
    for (const attachment of references) {
      this.record('message', {
        videoId,
        kind: attachment.kind,
        payload: { attachment: serializeAttachment(attachment) },
      });
    }
    const kind: ConceptJob['kind'] =
      text.trim() !== '' || normalized.some((attachment) => attachment.kind === 'text')
        ? 'chat'
        : bgm.length > 0 && references.length === 0
          ? 'bgm_upload'
          : 'reference';
    this.record('message', {
      videoId,
      kind,
      payload: { text, attachments: normalized.map(serializeAttachment) },
    });

    const job = this.createJob(videoId, kind, () =>
      this.completeMessage(document, text, normalized),
    );
    return cloneJob(job.job);
  }

  async submitStyle(videoId: string, prompt: string, attachment?: Attachment): Promise<ConceptJob> {
    const document = this.requireDocument(videoId);
    if (document.confirmed) {
      throw new ConceptApiError('concept_locked', 409, 'The concept is confirmed');
    }
    if (prompt.trim() === '' && attachment === undefined) {
      throw new ConceptApiError('validation_failed', 400, 'Style request is empty');
    }
    const checked = attachment === undefined ? undefined : this.checkedAttachment(attachment);
    if (checked !== undefined) {
      document.attachments = this.appendAttachments(document.attachments, [checked]);
    }
    this.record('submitStyle', {
      videoId,
      kind: 'style',
      payload: {
        prompt,
        attachment: checked === undefined ? null : serializeAttachment(checked),
      },
    });
    const generated = this.createGeneratedStyle(prompt, checked);
    const job = this.createJob(videoId, 'style', () => {
      this.generatedStyles.push(generated);
      const ops = styleOps(document.settings, generated.ref, this.catalogValue());
      const language = document.settings.language;
      const notes = [
        localized(
          language,
          `새 그림체 「${generated.manifest.label.ko}」가 준비됐어요. 대체 부위를 확인한 뒤 적용하세요.`,
          `The new style "${generated.manifest.label.en}" is ready. Review replacements before applying it.`,
        ),
      ];
      if (ops.length === 0) {
        return { plan: null, notes, unsupported: [] };
      }
      const plan = this.makePlan(document, ops, 'style', notes, []);
      return { plan, notes, unsupported: [] };
    });
    return cloneJob(job.job);
  }

  submitReference(videoId: string, attachment: Attachment): Promise<ConceptJob> {
    const document = this.requireDocument(videoId);
    if (attachment.kind !== 'reference' && attachment.kind !== 'link') {
      throw new ConceptApiError('validation_failed', 400, 'A reference file or link is required');
    }
    if (document.confirmed) {
      throw new ConceptApiError('concept_locked', 409, 'The concept is confirmed');
    }
    const checked = this.checkedAttachment(attachment);
    document.attachments = this.appendAttachments(document.attachments, [checked]);
    this.record('submitReference', {
      videoId,
      kind: checked.kind,
      payload: { attachment: serializeAttachment(checked) },
    });
    const job = this.createJob(videoId, 'reference', () => {
      const proposal = referenceProposal(document.settings, this.catalogValue());
      const language = document.settings.language;
      const unsupported = proposal.unsupported.map((key) => unsupportedText(language, key));
      const notes = [
        localized(
          language,
          proposal.ops.length === 0
            ? '참고 영상에서 새로 바꿀 값이 없어요.'
            : '참고 영상에서 채울 값을 찾았어요.',
          proposal.ops.length === 0
            ? 'The reference did not suggest a new value.'
            : 'The reference suggested concept values.',
        ),
      ];
      const plan = proposal.ops.length === 0
        ? null
        : this.makePlan(document, proposal.ops, 'reference', notes, unsupported);
      return { plan, notes, unsupported };
    });
    return Promise.resolve(cloneJob(job.job));
  }

  getJob(jobId: string): Promise<ConceptJob> {
    this.record('getJob', { payload: { jobId } });
    const stored = this.jobs.get(jobId);
    if (stored === undefined) {
      return Promise.reject(new ConceptApiError('not_found', 404, 'Unknown job'));
    }
    const job = stored.job;
    if (job.state === 'succeeded' || job.state === 'failed') {
      return Promise.resolve(cloneJob(job));
    }
    stored.polls += 1;
    if (stored.polls < this.jobPolls) {
      job.state = 'running';
      return Promise.resolve(cloneJob(job));
    }
    try {
      job.state = 'succeeded';
      job.result = stored.complete();
    } catch (error) {
      job.state = 'failed';
      job.result = {
        plan: null,
        notes: [],
        unsupported: [error instanceof Error ? error.message : 'Job failed'],
      };
    }
    return Promise.resolve(cloneJob(job));
  }

  applyPlan(videoId: string, planId: string, baseRevision: number): Promise<ConceptApplyResult> {
    this.record('applyPlan', {
      videoId,
      payload: { planId, base_revision: baseRevision },
    });
    const document = this.requireDocument(videoId);
    const stored = this.plans.get(planId);
    if (stored === undefined) {
      throw new ConceptApiError('not_found', 404, 'Unknown plan');
    }
    if (stored.plan.status === 'applied' && stored.appliedDocument !== null) {
      return Promise.resolve({
        document: cloneDocument(stored.appliedDocument),
        plan: clonePlan(stored.plan),
      });
    }
    if (stored.plan.status !== 'proposed') {
      throw new ConceptApiError('change_stale', 409, 'The plan is no longer proposed');
    }
    if (stored.plan.base_revision !== document.revision || baseRevision !== document.revision) {
      stored.plan.status = 'stale';
      throw new ConceptApiError('change_stale', 409, 'The plan base revision is stale');
    }
    if (document.confirmed && planTouchesLockedFields(this.planSetOps(stored.plan))) {
      throw new ConceptApiError('concept_locked', 409, 'The concept is confirmed');
    }
    const candidate = applySettingsOps(document.settings, this.planSetOps(stored.plan));
    const validation = validateConcept(candidate, this.catalogValue());
    if (!validation.ok) {
      throw new ConceptApiError('invalid_combination', 422, validation.blocked[0].key);
    }
    document.settings = candidate;
    document.revision += 1;
    stored.plan.status = 'applied';
    stored.plan.applied_revision = document.revision;
    stored.appliedDocument = cloneDocument(document);
    return Promise.resolve({
      document: cloneDocument(document),
      plan: clonePlan(stored.plan),
    });
  }

  rejectPlan(videoId: string, planId: string): Promise<Plan> {
    this.record('rejectPlan', { videoId, payload: { planId } });
    this.requireDocument(videoId);
    const stored = this.plans.get(planId);
    if (stored === undefined) {
      throw new ConceptApiError('not_found', 404, 'Unknown plan');
    }
    if (stored.plan.status !== 'proposed') {
      throw new ConceptApiError('change_stale', 409, 'The plan is no longer proposed');
    }
    stored.plan.status = 'rejected';
    return Promise.resolve(clonePlan(stored.plan));
  }

  private completeMessage(
    document: ConceptDocument,
    text: string,
    attachments: Attachment[],
  ): ConceptResult {
    const language = document.settings.language;
    const notes: string[] = [];
    const unsupported: string[] = [];
    const chat = text.trim() === ''
      ? { ops: [] as SetOp[], unsupported: [] as string[] }
      : chatProposal(document.settings, text, this.catalogValue());
    const ops = new Map<string, SetOp>();
    for (const op of chat.ops) {
      ops.set(op.path, op);
    }
    const references = attachments.filter(
      (attachment) => attachment.kind === 'reference' || attachment.kind === 'link',
    );
    if (references.length > 0) {
      const proposal = referenceProposal(document.settings, this.catalogValue());
      for (const op of proposal.ops) {
        if (!ops.has(op.path)) ops.set(op.path, op);
      }
      unsupported.push(...proposal.unsupported.map((key) => unsupportedText(language, key)));
      notes.push(
        localized(
          language,
          '참고 자료에서 채울 값을 찾았어요.',
          'The reference suggested concept values.',
        ),
      );
    }
    const texts = attachments.filter(
      (attachment) => attachment.kind === 'text' && (attachment.text ?? '').trim() !== '',
    );
    if (texts.length > 0) {
      notes.push(
        localized(
          language,
          `글 재료 ${texts.length}개를 영상에 더했어요.`,
          `Added ${texts.length} text material${texts.length === 1 ? '' : 's'}.`,
        ),
      );
    }
    if (attachments.some((attachment) => attachment.kind === 'bgm')) {
      notes.push(
        localized(
          language,
          'BGM을 이 프로젝트에 올렸어요.',
          'Uploaded the BGM to this project.',
        ),
      );
    }
    unsupported.push(...chat.unsupported.map((key) => `${text.trim()}: ${unsupportedText(language, key)}`));

    const list = [...ops.values()];
    if (list.length === 0) {
      notes.push(
        localized(
          language,
          '이 요청에서 바꿀 컨셉 값을 찾지 못했어요.',
          'I could not find a concept value to change in this request.',
        ),
      );
      return { plan: null, notes, unsupported };
    }
    const source: Plan['source'] = text.trim() === '' ? 'reference' : 'chat';
    const plan = this.makePlan(document, list, source, notes, unsupported);
    notes.push(
      localized(
        language,
        plan.requires_confirmation
          ? '적용 전에 바뀌는 값을 확인하세요.'
          : '컨셉 값에 반영했어요.',
        plan.requires_confirmation
          ? 'Review the proposed values before applying them.'
          : 'Updated the concept values.',
      ),
    );
    return { plan, notes, unsupported };
  }

  private makePlan(
    document: ConceptDocument,
    ops: readonly SetOp[],
    source: Plan['source'],
    notes: string[],
    unsupported: string[],
  ): Plan {
    const impact = planImpact(document.settings, ops, source);
    const id = this.nextId('c');
    const plan: Plan = {
      schema_version: 1,
      id,
      video_id: document.id,
      base_revision: document.revision,
      applied_revision: null,
      status: impact.requiresConfirmation ? 'proposed' : 'applied',
      source,
      target: { scene_id: null, pointer: null },
      ops: [...ops],
      effects: {
        script: false,
        scene_ids_text: [],
        scene_ids_tts: [],
        scene_ids_render: [],
        mix: false,
        assemble: false,
        locked_keys: impact.lockedKeys,
        overwrites_user_values: impact.overwrites,
      },
      requires_confirmation: impact.requiresConfirmation,
      confirmation_reasons: impact.reasons,
      warnings: impact.warnings,
      notes,
      unsupported,
      created_at: NOW,
    };
    if (!impact.requiresConfirmation) {
      document.settings = applySettingsOps(document.settings, ops);
      document.revision += 1;
      plan.applied_revision = document.revision;
    }
    this.plans.set(id, { plan, appliedDocument: null });
    return plan;
  }

  private createJob(
    videoId: string,
    kind: ConceptJob['kind'],
    complete: () => ConceptResult,
  ): MockJob {
    const id = this.nextId('j');
    const job: ConceptJob = { id, kind, state: 'queued' };
    const stored: MockJob = { job, videoId, polls: 0, complete };
    this.jobs.set(id, stored);
    return stored;
  }

  private requireDocument(videoId: string): ConceptDocument {
    const document = this.sessions.get(videoId);
    if (document === undefined) {
      throw new ConceptApiError('not_found', 404, 'Unknown video');
    }
    return document;
  }

  private nextId(prefix: 'v' | 'p' | 'c' | 'j'): string {
    this.sequence += 1;
    return `${prefix}_mock_${String(this.sequence).padStart(26, '0')}`;
  }

  private record(
    method: ConceptRequestMethod,
    request: Omit<ConceptRequest, 'method'>,
  ): void {
    this.requests.push({ method, ...request });
  }

  private checkedAttachment(attachment: Attachment): Attachment {
    if (attachment.kind !== 'link') {
      return attachment;
    }
    if (!linkPolicy(this.deploymentMode).enabled) {
      throw new ConceptApiError('link_disabled', 403, 'Links are disabled in this deployment');
    }
    if (attachment.url === undefined) {
      throw new ConceptApiError('url_not_allowed', 422, 'A reference link is required');
    }
    const checked = validateReferenceUrl(attachment.url);
    if (!checked.ok) {
      throw new ConceptApiError('url_not_allowed', 422, checked.reason);
    }
    return { ...attachment, url: checked.url };
  }

  private async normalizeAttachments(attachments: readonly Attachment[]): Promise<Attachment[]> {
    const normalized: Attachment[] = [];
    for (const raw of attachments) {
      const attachment = this.checkedAttachment(raw);
      if (attachment.kind === 'text' && attachment.text === undefined && attachment.file !== undefined) {
        normalized.push({ ...attachment, text: await readTextFile(attachment.file) });
      } else {
        normalized.push(attachment);
      }
    }
    return normalized;
  }

  private textCount(existing: readonly Attachment[], incoming: readonly Attachment[]): number {
    const ids = new Set(existing.filter((attachment) => attachment.kind === 'text').map((attachment) => attachment.id));
    let count = ids.size;
    for (const attachment of incoming) {
      if (attachment.kind === 'text' && !ids.has(attachment.id)) {
        ids.add(attachment.id);
        count += 1;
      }
    }
    return count;
  }

  private appendAttachments(
    existing: readonly Attachment[],
    incoming: readonly Attachment[],
  ): Attachment[] {
    const seen = new Set(existing.map((attachment) => attachment.id));
    const next = [...existing];
    for (const attachment of incoming) {
      if (!seen.has(attachment.id)) {
        seen.add(attachment.id);
        next.push(attachment);
      }
    }
    return next;
  }

  private createGeneratedStyle(prompt: string, attachment?: Attachment): GeneratedStyle {
    this.sequence += 1;
    const number = this.sequence;
    const id = `style_gen_${number}`;
    const ref: PinnedRef = {
      id,
      revision: syntheticDigest(`style:${id}:${prompt}:${attachment?.name ?? ''}`),
    };
    const asset = (slot: string): string => `gen${number}_${slot}`;
    const manifest: StyleManifest = {
      schema_version: 1,
      api_version: 1,
      id,
      version: '0.1.0',
      label: {
        ko: `내 스타일 ${number}`,
        en: `My style ${number}`,
      },
      origin: 'generated',
      status: 'ready',
      extends: PIXEL_REF,
      renderer: {
        kind: 'sandbox',
        program: 'program.py',
        program_digest: syntheticDigest(`program:${id}`),
        runtime_digest: syntheticDigest('runtime'),
        entry: 'build_assets',
      },
      canvas: { width: 180, height: 320, scale: 'nearest' },
      rig: {
        slots: {
          body: [asset('body')],
          face: [asset('face')],
          hair: [asset('hair')],
          hat: [asset('hat')],
          outfit: [asset('outfit')],
          prop: [asset('prop')],
        },
        expressions: [`gen${number}_happy`],
        poses: [`gen${number}_idle`],
        compat: [],
      },
      themes: [
        {
          id: 'day',
          label: { ko: '낮', en: 'Day' },
          palette: {
            bg: '#101018',
            ink: '#f4f1ea',
            accent: '#c8b27a',
            caption_text: '#f4f1ea',
            caption_box: '#1a1a22',
          },
          skin_id: asset('skin'),
          backgrounds: [asset('bg')],
        },
      ],
      assets: [
        ...(['body', 'face', 'hair', 'hat', 'outfit', 'prop'] as const).map((slot) => ({
          id: asset(slot),
          kind: 'part' as const,
          slot,
          file: `sprites/${asset(slot)}.json`,
          sha256: syntheticDigest(`asset:${id}:${slot}`),
          license_id: 'apache',
        })),
        {
          id: asset('bg'),
          kind: 'background',
          slot: null,
          file: `sprites/${asset('bg')}.json`,
          sha256: syntheticDigest(`asset:${id}:bg`),
          license_id: 'apache',
        },
        {
          id: asset('skin'),
          kind: 'skin',
          slot: null,
          file: `sprites/${asset('skin')}.json`,
          sha256: syntheticDigest(`asset:${id}:skin`),
          license_id: 'apache',
        },
        {
          id: `gen${number}_happy`,
          kind: 'expression',
          slot: null,
          file: `sprites/gen${number}_happy.json`,
          sha256: syntheticDigest(`asset:${id}:happy`),
          license_id: 'apache',
        },
        {
          id: `gen${number}_idle`,
          kind: 'pose',
          slot: null,
          file: `sprites/gen${number}_idle.json`,
          sha256: syntheticDigest(`asset:${id}:idle`),
          license_id: 'apache',
        },
      ],
      fonts: PIXEL_MANIFEST.fonts,
      capabilities: {
        layouts: ['fixed_stage', 'full_stage', 'dialog_stage'],
        caption_modes: ['sentence', 'phrase', 'typewriter'],
        character_roles: ['presenter', 'subject'],
      },
      licenses: {},
      provenance: {
        job_id: this.nextId('j'),
        provider: 'mock',
        model: 'mock',
        parent: PIXEL_REF,
        request_digest: syntheticDigest(`request:${id}`),
        reference_digest: attachment === undefined ? null : syntheticDigest(`reference:${attachment.id}`),
      },
      preview: null,
    };
    return { ref, manifest };
  }

  private planSetOps(plan: Plan): SetOp[] {
    return plan.ops.filter((op): op is SetOp => op.op === 'set');
  }
}

function styleOps(settings: Settings, ref: PinnedRef, catalog: ConceptCatalog): SetOp[] {
  const target = catalog.styles.find((style) => style.ref.id === ref.id);
  if (target === undefined) {
    return [];
  }
  const manifest = target.manifest;
  const ops: SetOp[] = [
    { op: 'set', path: '/visual/art_style', value: ref, origin: 'user' },
  ];
  const theme = manifest.themes.some((entry) => entry.id === settings.visual.theme_id)
    ? settings.visual.theme_id
    : manifest.themes[0]?.id;
  if (theme !== undefined && theme !== settings.visual.theme_id) {
    ops.push({ op: 'set', path: '/visual/theme_id', value: theme, origin: 'default' });
  }
  if (settings.visual.character !== null) {
    for (const slot of ['body', 'face', 'hair', 'hat', 'outfit', 'prop'] as const) {
      const asset = settings.visual.character.slots[slot];
      const available = asset === null
        ? true
        : manifest.assets.some((entry) => entry.id === asset && entry.kind === 'part' && entry.slot === slot);
      if (!available) {
        const replacement = manifest.assets.find(
          (entry) => entry.kind === 'part' && entry.slot === slot,
        )?.id ?? null;
        ops.push({
          op: 'set',
          path: `/visual/character/slots/${slot}`,
          value: replacement,
          origin: 'default',
        });
      }
    }
  }
  return effectiveOps(settings, ops);
}

export function createMockConceptApi(options: MockConceptApiOptions = {}): MockConceptApi {
  return new MockConceptApi(options);
}
