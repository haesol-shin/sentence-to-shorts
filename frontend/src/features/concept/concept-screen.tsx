import { Children, useEffect, useLayoutEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { Check, ChevronDown, ChevronRight, Image, Video, X } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { Chip } from '@/components/Chip/Chip';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { ValueField } from '@/components/ValueField/ValueField';
import { useLocale } from '@/shared/lib/i18n/locale';

import { CARD_DESCRIPTION_LIMIT, clampCardText, cardColumns, STORY_CARD_ORDER, visibleCardCount } from './cards';
import { valueLabel } from './labels';
import { cardIdForSettings, originOf, SHORT_OPTIONS } from './model';
import {
  acknowledgeConceptChanged, analyzeConceptReference, applyConceptPlan, chooseCardTune, chooseConcept,
  conceptPathTouches, confirmConcept, conceptApiIsMock, consumeConceptChanged, createConceptStyle, ensureConcept,
  rejectConceptPlan, reloadConcept, reloadConceptCatalog, undoConcept, useConcept, useConceptStyleEntry,
} from './store';
import type { Attachment, ConceptChange, Plan, Settings, Slot } from './types';
import './concept.css';

const STORIES = STORY_CARD_ORDER;
// A character card is its body; the other parts live in that card's fine-tune board.
const PARTS: Slot[] = ['face', 'hair', 'hat', 'outfit', 'prop'];
/** One animation of the canon's one-time changed mark. */
const CHANGED_HIGHLIGHT_MS = 700;
const NO_CHANGED_PATHS: ConceptChange[] = [];

export interface EntryComposerProps {
  label: string;
  placeholder: string;
  sendLabel: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (attachments: Attachment[]) => Promise<void>;
  disabled: boolean;
}

function read(settings: Settings, path: string): unknown {
  return path.split('/').filter(Boolean).reduce<unknown>((value, key) =>
    value !== null && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined,
  settings);
}

/** A modal window: title, the caller's body, then cancel and the caller's actions on the right. */
function Modal({ title, children, actions, onClose }: {
  title: string; children: ReactNode; actions?: ReactNode; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const { t } = useLocale();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.showModal?.();
    cancel.current?.focus();
    return () => {
      node?.close?.();
      previous?.focus();
    };
  }, []);
  return (
    <dialog ref={dialog} aria-label={title} className="concept-dialog" onCancel={(event) => {
      event.preventDefault(); onClose();
    }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <ScrollPane label={title} jumpLabel={t('shell.scroll.jump')} className="concept-dialog__pane">
        <div className="concept-dialog__body">
          <h2 className="concept-dialog__title">{title}</h2>
          {children}
          <div className="concept-dialog__actions">
            <button ref={cancel} type="button" className="concept-dialog__cancel" onClick={onClose}>
              {t('concept.cancel')}
            </button>
            {actions}
          </div>
        </div>
      </ScrollPane>
    </dialog>
  );
}

function CardGrid({ children }: { children: ReactNode }) {
  const { t } = useLocale();
  const grid = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(3);
  const [expanded, setExpanded] = useState(false);
  useLayoutEffect(() => {
    const node = grid.current;
    if (node === null) return undefined;
    const update = () => setColumns(cardColumns(node.clientWidth));
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const items = Children.toArray(children);
  const shown = expanded ? items : items.slice(0, visibleCardCount(items.length, columns));
  return (
    <>
      <div ref={grid} className="concept-card-grid">{shown}</div>
      {expanded || items.length <= shown.length ? null : (
        <Button variant="ghost" className="concept-more" onClick={() => setExpanded(true)}>{t('concept.more')}</Button>
      )}
    </>
  );
}

/**
 * A picture card. A story card's body sits bare inside its slot, which carries
 * the face; a tile (art style) is its own 216 face.
 */
function PictureCard({ title, description, selected, disabled, onClick, changed, tile = false }: {
  title: string; description?: string; selected: boolean; disabled: boolean; onClick: () => void;
  changed?: number; tile?: boolean;
}) {
  return (
    <button type="button" className={tile ? 'concept-card concept-card--tile' : 'concept-card'} aria-label={title} title={title}
      aria-pressed={selected} data-changed={changed === undefined ? undefined : String(changed % 2)}
      disabled={disabled} onClick={onClick}>
      <span className="concept-card__picture"><Image aria-hidden size={32} /></span>
      <span className="concept-card__title">{clampCardText(title)}</span>
      <span className="concept-card__description">{clampCardText(description ?? '', CARD_DESCRIPTION_LIMIT)}</span>
    </button>
  );
}

/** The style's own one line when the locale has it, otherwise where the style came from. */
function styleDescription(id: string, builtin: boolean, t: (key: string) => string): string {
  const key = `concept.style.description.${id}`;
  const own = t(key);
  return own === key ? t(builtin ? 'concept.style.builtin' : 'concept.style.mine') : own;
}

/**
 * A detail panel consumes only the mark versions it actually showed, once it
 * leaves the screen. The microtask lets StrictMode's test unmount cancel it.
 */
function TunePanel({ videoId, entries, children }: {
  videoId: string; entries: ConceptChange[]; children: ReactNode;
}) {
  const latest = useRef(entries);
  latest.current = entries;
  const pending = useRef<number | null>(null);
  useEffect(() => {
    if (pending.current !== null) {
      window.clearTimeout(pending.current);
      pending.current = null;
    }
    return () => {
      const shown = latest.current;
      if (shown.length === 0) return;
      pending.current = window.setTimeout(() => {
        pending.current = null;
        consumeConceptChanged(videoId, shown);
      }, 0);
    };
  }, [videoId]);
  return <>{children}</>;
}

/** A card with a fine-tune toggle under it; the board opens below the card row. */
function TunedCard({ id, title, description, selected, disabled, open, onPick, onToggle, panel, changed, tile = false }: {
  id: string; title: string; description: string; selected: boolean; disabled: boolean;
  open: boolean; onPick: () => void; onToggle: () => void; panel: ReactNode;
  changed?: number; tile?: boolean;
}) {
  const { t } = useLocale();
  return (
    <div className={tile ? 'concept-card-slot concept-card-slot--tile' : 'concept-card-slot'}
      data-card={id} data-selected={!tile && selected ? '' : undefined}
      data-changed={changed === undefined ? undefined : String(changed % 2)}>
      <PictureCard title={title} description={description} selected={selected} disabled={disabled} onClick={onPick} tile={tile} />
      <button type="button" className="concept-tune-toggle" aria-expanded={open}
        aria-label={`${title} ${t('concept.tune')}`} aria-controls={`concept-tune-${id}`}
        disabled={disabled && !selected} onClick={onToggle}>
        <span>{t('concept.tune')}</span><ChevronDown aria-hidden size={20} />
      </button>
      {open ? <section id={`concept-tune-${id}`} data-slot="concept-detail" className="concept-tune-panel" aria-label={`${title} ${t('concept.tune')}`}>
        {panel}
      </section> : null}
    </div>
  );
}

/** A value pick in the value field the canon draws: name, bold value and chevron, its menu below. */
function TuneField({ name, label, path, options, value, disabled, changed, className }: {
  name: string; label?: string; path: string; options: { value: unknown; label: string }[]; value: unknown;
  disabled: boolean; changed?: number; className?: string;
}) {
  const { t } = useLocale();
  const index = options.findIndex((option) => JSON.stringify(option.value) === JSON.stringify(value));
  return (
    <span className="concept-tune-slot" data-changed={changed === undefined ? undefined : String(changed % 2)}>
      <ValueField<number> className={className} label={name} name={label ?? name}
        placeholder={valueLabel(value, t)} disabled={disabled}
        items={options.map((option, i) => ({ value: i, label: option.label }))}
        value={index} onValueChange={(i) => {
          const option = options[i];
          if (option !== undefined) chooseConcept(path, option.value);
        }} />
    </span>
  );
}

export function ChangeReview({ plan, settings, busy }: { plan: Plan; settings: Settings; busy: boolean }) {
  const { t } = useLocale();
  const name = (path: string) => {
    const normalized = path.replace(/^\/settings/u, '');
    if (normalized === '/format/story_structure' || normalized === '/format/card_id') return t('concept.story');
    const key = `concept.field.${normalized.split('/').filter(Boolean).join('.')}`;
    return t(key) === key ? normalized : t(key);
  };
  return (
    <section className="concept-review" aria-label={t('concept.review.title')}>
      <h3 className="font-bold">{t('concept.review.title')}</h3>
      <ul className="list-disc pl-5">
        {plan.ops.map((op, index) => <li key={index}>{op.op === 'set'
          ? `${name(op.path)}: ${valueLabel(read(settings, op.path.replace(/^\/settings/u, '')), t)} → ${valueLabel(op.value, t)}`
          : t(`concept.operation.${op.op}`)}</li>)}
      </ul>
      <p>{t('concept.review.locks')}: {plan.effects.locked_keys.length === 0 ? t('concept.value.none') : plan.effects.locked_keys.map((key) => t(`concept.field.${key}`)).join(', ')}</p>
      <p>{t('concept.review.overwrites')}: {plan.effects.overwrites_user_values.length === 0 ? t('concept.value.none') : plan.effects.overwrites_user_values.map(name).join(', ')}</p>
      <p>{t('concept.review.rebuild')}: {[
        plan.effects.script ? t('concept.review.script') : '',
        plan.effects.scene_ids_text.length ? t('concept.review.text') : '',
        plan.effects.scene_ids_tts.length ? t('concept.review.tts') : '',
        plan.effects.scene_ids_render.length ? t('concept.review.render') : '',
        plan.effects.mix ? t('concept.review.mix') : '',
        plan.effects.assemble ? t('concept.review.assemble') : '',
      ].filter(Boolean).join(', ') || t('concept.value.none')}</p>
      <p>{t('concept.review.stageUnchanged')}</p>
      {plan.confirmation_reasons.map((reason) => <p key={reason}>{t(`concept.reason.${reason}`)}</p>)}
      {plan.warnings.map((warning, index) => <p key={index}>{t(`concept.warning.${warning.code}`)}</p>)}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" disabled={busy} iconStart={<X aria-hidden size={16} />} onClick={rejectConceptPlan}>{t('concept.keep')}</Button>
        <Button disabled={busy} iconStart={<Check aria-hidden size={16} />} onClick={() => void applyConceptPlan()}>{t('concept.apply')}</Button>
      </div>
    </section>
  );
}

function Entry({ mode, onClose, ComposerComponent }: {
  mode: 'reference' | 'style'; onClose: () => void;
  ComposerComponent: ComponentType<EntryComposerProps>;
}) {
  const { t } = useLocale();
  const [prompt, setPrompt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const title = t(`concept.entry.${mode}`);
  const submit = async (attachments: Attachment[]) => {
    const references = attachments.filter((attachment) => attachment.kind === 'reference' || attachment.kind === 'link');
    const reference = references[0];
    if (references.length > 1 || attachments.some((attachment) => attachment.kind === 'text' || attachment.kind === 'bgm')) {
      setError('concept.entry.oneReference'); throw new Error(t('concept.entry.oneReference'));
    }
    if ((mode === 'reference' && reference === undefined) || (mode === 'style' && prompt.trim() === '')) {
      setError('concept.entry.required'); throw new Error(t('concept.entry.required'));
    }
    setSubmitting(true);
    try {
      if (mode === 'reference') await analyzeConceptReference(reference!);
      else await createConceptStyle(prompt.trim(), reference);
      onClose();
    } finally { setSubmitting(false); }
  };
  return (
    <Modal title={title} onClose={onClose}>
      {conceptApiIsMock() ? <p>{t('concept.mockNotice')}</p> : null}
      <p>{t('concept.entry.help')}</p>
      {error === null ? null : <p role="alert">{t(error)}</p>}
      <ComposerComponent label={title} placeholder={t('concept.entry.placeholder')}
        sendLabel={t('concept.entry.start')} value={prompt} onChange={setPrompt}
        onSubmit={submit} disabled={submitting} />
    </Modal>
  );
}

/**
 * The concept step. Confirming the concept hands the video to the script
 * step through `onConfirmed`, so the confirm button keeps its word.
 */
export function ConceptScreen({ ComposerComponent, onConfirmed }: {
  ComposerComponent: ComponentType<EntryComposerProps>; onConfirmed?: () => void;
}) {
  const { t, language } = useLocale();
  const snapshot = useConcept();
  const [entry, setEntry] = useState<'reference' | 'style' | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [openTune, setOpenTune] = useState<string | null>(null);
  const styleEntry = useConceptStyleEntry();
  // A stale count from an earlier visit must not open the window; only a new ask does.
  const seenStyleEntry = useRef(styleEntry);
  useEffect(() => { ensureConcept(); }, []);
  // The `+` menu asks for a style made from words; this screen owns its window.
  useEffect(() => {
    if (styleEntry > seenStyleEntry.current) {
      seenStyleEntry.current = styleEntry;
      setEntry('style');
    }
  }, [styleEntry]);
  const pendingChanged = snapshot?.changedPaths ?? NO_CHANGED_PATHS;
  const [changed, setChanged] = useState<ReadonlyMap<string, number>>(
    () => new Map(pendingChanged.map((entry) => [entry.path, entry.version])),
  );
  // The store holds each mark until the screen shows it, so a remount never replays.
  useEffect(() => {
    if (pendingChanged.length === 0) return;
    setChanged((previous) => {
      const next = new Map(previous);
      for (const entry of pendingChanged) next.set(entry.path, entry.version);
      return next;
    });
    acknowledgeConceptChanged();
  }, [pendingChanged]);
  // The canon marks a value once; the attribute goes so the next change animates again.
  useEffect(() => {
    if (changed.size === 0) return undefined;
    const timer = window.setTimeout(() => setChanged(new Map()), CHANGED_HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [changed]);
  // The store is the one place that invalidates a mark; the screen follows it.
  const forgotten = snapshot?.forgotten ?? null;
  useEffect(() => {
    if (forgotten === null) return;
    setChanged((previous) => {
      const next = new Map(previous);
      if (forgotten.changes !== undefined) {
        for (const change of forgotten.changes) {
          const shown = next.get(change.path);
          if (shown !== undefined && shown <= change.version) next.delete(change.path);
        }
      } else {
        for (const mark of previous.keys()) {
          if (forgotten.paths.some((path) => conceptPathTouches(mark, path))) {
            next.delete(mark);
          }
        }
      }
      return next.size === previous.size ? previous : next;
    });
  }, [forgotten]);
  if (snapshot === null) return <p role="status">{t('concept.loading')}</p>;
  const { document: doc, catalog } = snapshot;
  const settings = doc.settings;
  const style = catalog?.styles.find((item) => item.ref.id === settings.visual.art_style.id)?.manifest;
  const frozen = doc.confirmed || snapshot.busy || catalog === null;
  const choices = (values: readonly unknown[]) => values.map((value) => ({ value, label: valueLabel(value, t) }));
  const activeCardId = cardIdForSettings(settings) ?? '';
  const character = settings.visual.character;
  const activeCharacterId = character === null ? '' : `character-${character.slots.body}`;
  const characterFrozen = frozen || character === null;
  const versionOf = (...paths: string[]): number | undefined => paths.reduce<number | undefined>(
    (latest, path) => {
      const version = changed.get(path);
      if (version === undefined) return latest;
      return latest === undefined ? version : Math.max(latest, version);
    },
    undefined,
  );
  const tunePanelEntries = ['/format/layout', '/format/register', '/format/humor'].flatMap((path) => {
    const version = changed.get(path);
    return version === undefined ? [] : [{ path, version }];
  });
  const characterPanelEntries = PARTS.flatMap((slot) => {
    const path = `/visual/character/slots/${slot}`;
    const version = changed.get(path);
    return version === undefined ? [] : [{ path, version }];
  });
  const pickCard = (id: string) => {
    if (frozen || id === activeCardId) return;
    chooseCardTune(id);
  };
  const pickCharacter = (body: string) => {
    if (characterFrozen || `character-${body}` === activeCharacterId) return;
    chooseConcept('/visual/character/slots/body', body);
  };
  // An open board follows the picked card of its own row.
  const onCard = (id: string) => {
    pickCard(id);
    if (openTune !== null && !openTune.startsWith('character-')) setOpenTune(id);
  };
  const onCharacter = (body: string) => {
    pickCharacter(body);
    if (openTune?.startsWith('character-')) setOpenTune(`character-${body}`);
  };
  const toggleTune = (id: string) => {
    if (openTune === id) {
      setOpenTune(null);
      return;
    }
    if (id !== activeCardId) {
      if (frozen) return;
      pickCard(id);
    }
    setOpenTune(id);
  };
  const toggleCharacter = (body: string) => {
    const id = `character-${body}`;
    if (openTune === id) {
      setOpenTune(null);
      return;
    }
    if (id !== activeCharacterId) {
      if (characterFrozen) return;
      pickCharacter(body);
    }
    setOpenTune(id);
  };
  const openCardId = openTune !== null && (openTune === activeCardId || openTune === activeCharacterId) ? openTune : null;
  const tuneOrigins = ['/format/layout', '/format/register', '/format/humor']
    .map((path) => originOf(settings, path));
  const tuneSummary = tuneOrigins.includes('user')
    ? 'concept.tune.userValues'
    : tuneOrigins.includes('reference') ? 'concept.tune.referenceValues' : 'concept.tune.cardValues';
  const layoutOptions = (catalog?.layouts ?? []).map((item) => ({ value: item.ref, label: valueLabel(item.ref, t) }));
  const registerOptions = choices(SHORT_OPTIONS.register);
  const humorOptions = choices(SHORT_OPTIONS.humor);
  const panelHead = (name: string, summary: string) => (
    <div className="concept-tune-panel__head">
      <span className="concept-tune-panel__mark"><Image aria-hidden size={20} /></span>
      <div className="concept-tune-panel__names">
        <strong>{name}</strong><span>{summary}</span>
      </div>
    </div>
  );
  const tunePanel = (id: string) => (
    <>
      {panelHead(t(`concept.card.${id}`), t(tuneSummary))}
      <div className="concept-tune-panel__grid">
        <TuneField className="concept-tune-field" name={t('concept.field.format.layout')} path="/format/layout"
          options={layoutOptions} value={settings.format.layout} disabled={frozen}
          changed={changed.get('/format/layout')} />
        <TuneField className="concept-tune-field" name={t('concept.field.format.register')} path="/format/register"
          options={registerOptions} value={settings.format.register} disabled={frozen}
          changed={changed.get('/format/register')} />
        <TuneField className="concept-tune-field" name={t('concept.field.format.humor')} path="/format/humor"
          options={humorOptions} value={settings.format.humor} disabled={frozen}
          changed={changed.get('/format/humor')} />
      </div>
    </>
  );
  const characterPanel = (body: string) => (
    <>
      {panelHead(valueLabel(body, t), t('concept.character.parts'))}
      <div className="concept-tune-panel__grid">
        {PARTS.map((slot) => (
          <TuneField key={slot} className="concept-tune-field" name={t(`concept.slot.${slot}`)}
            path={`/visual/character/slots/${slot}`} value={character?.slots[slot] ?? null} disabled={characterFrozen}
            changed={changed.get(`/visual/character/slots/${slot}`)}
            options={choices([...(slot === 'face' ? [] : [null]), ...(style?.rig.slots[slot] ?? [])])} />
        ))}
      </div>
    </>
  );
  return (
    <section data-slot="concept-screen" className="concept-screen" aria-label={t('concept.title')}>
      <ScrollPane label={t('concept.document')} jumpLabel={t('shell.scroll.jump')} className="concept-content">
        <header className="concept-head">
          {/* The video's name rides the top bar, so the head carries only the step. */}
          <div className="concept-head__names"><h1>{t('concept.title')}</h1>
            {doc.confirmed ? <p className="concept-head__scope">{t('concept.confirmed')}</p> : null}</div>
          <div className="concept-head__fields">
            <TuneField name={t('concept.field.target_duration_s')} label={t('concept.head.duration')}
              path="/target_duration_s" options={choices([30, 60, 120])} value={settings.target_duration_s}
              disabled={frozen} changed={changed.get('/target_duration_s')} />
            <TuneField name={t('concept.field.format.scene_count')} label={t('concept.head.sceneCount')}
              path="/format/scene_count" options={[5, 8, 11].map((count) => ({ value: count, label: t('concept.head.sceneCountValue', { count }) }))}
              value={settings.format.scene_count} disabled={frozen} changed={changed.get('/format/scene_count')} />
          </div>
        </header>
        {snapshot.readError === null ? null : <div role="alert" className="concept-review">
          <p>{snapshot.readError.startsWith('concept.') ? t(snapshot.readError) : snapshot.readError}</p>
          <Button variant="ghost" disabled={snapshot.busy || snapshot.readState === 'waiting'}
            onClick={() => void reloadConcept(doc.id)}>
            {t('shell.prepare.retry')}
          </Button>
        </div>}
        {snapshot.readNotice === null ? null : <p role="status">{t(snapshot.readNotice)}</p>}
        {snapshot.error === null ? null : <div role="alert" className="concept-review">
          <p>{snapshot.error.startsWith('concept.') ? t(snapshot.error) : snapshot.error}</p>
          <Button variant="ghost" disabled={snapshot.loading} onClick={() => void reloadConceptCatalog()}>
            {t('concept.retryCatalog')}
          </Button>
        </div>}
        {snapshot.loading ? <p role="status">{t('concept.loading')}</p> : null}
        <button type="button" className="concept-reference-band" aria-label={t('concept.reference')}
          disabled={frozen} onClick={() => setEntry('reference')}>
          <span className="concept-reference-band__mark"><Video aria-hidden size={20} /></span>
          <span className="concept-reference-band__text">
            <strong>{t('concept.reference')}</strong><span>{t('concept.reference.help')}</span>
          </span>
          <ChevronRight aria-hidden size={20} className="concept-reference-band__icon" />
        </button>
        <section aria-labelledby="concept-story-title" className="concept-group">
          <h2 id="concept-story-title" className="concept-group__title">
            <span>{t('concept.story')}</span>
          </h2>
          <CardGrid>
            {STORIES.map((id) => (
              <TunedCard key={id} id={id} title={t(`concept.card.${id}`)} description={t(`concept.example.${id}`)}
                selected={activeCardId === id} disabled={frozen}
                changed={activeCardId === id
                  ? versionOf('/format/story_structure', '/format/card_id')
                  : undefined}
                open={openCardId === id} onPick={() => onCard(id)} onToggle={() => toggleTune(id)}
                panel={openCardId === id ? <TunePanel videoId={doc.id} entries={tunePanelEntries}>{tunePanel(id)}</TunePanel> : null} />
            ))}
          </CardGrid>
        </section>
        <section aria-labelledby="concept-style-title" className="concept-group">
          {/* The canon row is the title and the cards only; a style made from words
              opens from the conversation box's `+` menu. */}
          <h2 id="concept-style-title" className="concept-group__title">
            <span>{t('concept.style')}</span>
          </h2>
          <CardGrid>
            {(catalog?.styles ?? []).map((item) => (
              <PictureCard key={item.ref.id} tile title={item.manifest.label[language]}
                description={styleDescription(item.ref.id, item.manifest.origin === 'builtin', t)}
                selected={settings.visual.art_style.id === item.ref.id} disabled={frozen}
                changed={settings.visual.art_style.id === item.ref.id
                  ? changed.get('/visual/art_style')
                  : undefined}
                onClick={() => {
                  chooseConcept('/visual/art_style', item.ref);
                }} />
            ))}
          </CardGrid>
        </section>
        <section aria-labelledby="concept-character-title" className="concept-group">
          <h2 id="concept-character-title" className="concept-group__title">
            <span>{t('concept.character')}</span>
          </h2>
          <CardGrid>
            {(style?.rig.slots.body ?? []).map((body) => {
              const id = `character-${body}`;
              return (
                <TunedCard key={id} id={id} title={valueLabel(body, t)} description=""
                  selected={activeCharacterId === id} disabled={characterFrozen} tile
                  changed={activeCharacterId === id ? changed.get('/visual/character/slots/body') : undefined}
                  open={openCardId === id} onPick={() => onCharacter(body)} onToggle={() => toggleCharacter(body)}
                  panel={openCardId === id ? <TunePanel videoId={doc.id} entries={characterPanelEntries}>{characterPanel(body)}</TunePanel> : null} />
              );
            })}
          </CardGrid>
        </section>
        {/* The mock notice stays readable at the end of the document, below the picks. */}
        {conceptApiIsMock() ? <p className="text-[15px]">{t('concept.mockNotice')}</p> : null}
        {settings.format.register === 'neutral' && settings.format.humor === 'light'
          ? <p role="status">{t('concept.weakCombination')}</p> : null}
        {settings.extra_instructions.length ? <div><h3 className="font-bold">{t('concept.extra')}</h3>
          {settings.extra_instructions.map((instruction, index) => <Chip key={index}>{instruction}</Chip>)}</div> : null}
        <section aria-live="polite" className="flex flex-col gap-2">
          {snapshot.job === null ? null : <p role="status">{t(`concept.job.${snapshot.job.kind}`)}: {t(`concept.job.${snapshot.job.state}`)}</p>}
          {snapshot.notes.map((note, index) => <p key={`n${index}`}>{note}</p>)}
          {snapshot.unsupported.length ? <div><h3 className="font-bold">{t('concept.unsupported')}</h3>
            {snapshot.unsupported.map((text, index) => <p key={index}>{text}</p>)}</div> : null}
        </section>
        {snapshot.pending?.status === 'proposed' ? <ChangeReview plan={snapshot.pending} settings={settings} busy={snapshot.busy} /> : null}
      </ScrollPane>
      {doc.confirmed ? null : <footer className="concept-footer">
        {snapshot.canUndo ? <Button variant="ghost" disabled={snapshot.busy} onClick={undoConcept}>{t('concept.undo')}</Button> : null}
        <Button disabled={frozen || snapshot.pending !== null} onClick={() => setConfirming(true)}>{t('concept.confirm')}</Button>
      </footer>}
      {entry === null ? null : <Entry mode={entry} onClose={() => setEntry(null)} ComposerComponent={ComposerComponent} />}
      {confirming ? <Modal title={t('concept.confirm.title')} onClose={() => setConfirming(false)}
        actions={<Button disabled={snapshot.busy} onClick={() => void confirmConcept().then(() => {
          setConfirming(false);
          onConfirmed?.();
        }, () => undefined)}>{t('concept.confirm')}</Button>}>
        <p className="concept-dialog__help">{t('concept.confirm.help')}</p>
        <dl className="concept-dialog__values">
          <div><dt>{t('concept.story')}</dt><dd>{activeCardId === '' ? valueLabel(settings.format.story_structure, t) : t(`concept.card.${activeCardId}`)}</dd></div>
          <div><dt>{t('concept.style')}</dt><dd>{valueLabel(settings.visual.art_style, t)}</dd></div>
          <div><dt>{t('concept.character')}</dt><dd>{valueLabel(settings.visual.character?.slots.body, t)}</dd></div>
        </dl>
      </Modal> : null}
    </section>
  );
}
