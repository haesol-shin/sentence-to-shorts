import { Children, useEffect, useLayoutEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { Check, ChevronDown, ChevronRight, Image, LockKeyhole, Video, X } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { Chip } from '@/components/Chip/Chip';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { Tag } from '@/components/Tag/Tag';
import { useLocale } from '@/shared/lib/i18n/locale';

import { CARD_DESCRIPTION_LIMIT, clampCardText, cardColumns, STORY_CARD_ORDER, visibleCardCount } from './cards';
import { cardIdForSettings, originOf, SHORT_OPTIONS } from './model';
import {
  analyzeConceptReference, applyConceptPlan, chooseCardTune, chooseConcept,
  confirmConcept, conceptApiIsMock, createConceptStyle, ensureConcept, rejectConceptPlan,
  reloadConceptCatalog, resetConcept, toggleConceptLock, undoConcept, useConcept,
} from './store';
import type { Attachment, ConceptSnapshot, LockKey, Plan, Settings, Slot } from './types';
import './concept.css';

const STORIES = STORY_CARD_ORDER;
const SLOTS: Slot[] = ['body', 'face', 'hair', 'hat', 'outfit', 'prop'];
// Art styles the canon shows as coming soon beside the built-in one; they cannot be picked yet.
const SOON_STYLES = ['cutout', 'sketch'] as const;

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

function valueLabel(value: unknown, t: (key: string) => string): string {
  if (value === null || value === undefined) return t('concept.value.none');
  if (typeof value === 'object') {
    if ('id' in value) return valueLabel(value.id, t);
    return Object.entries(value).map(([key, part]) => `${key}: ${valueLabel(part, t)}`).join(', ');
  }
  const key = `concept.value.${String(value)}`;
  const label = t(key);
  return label === key ? String(value) : label;
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

function Field({ snapshot, path, name, options, lockKey }: {
  snapshot: ConceptSnapshot; path: string; name: string;
  options: { value: unknown; label: string }[]; lockKey?: LockKey;
}) {
  const { t } = useLocale();
  const current = read(snapshot.document.settings, path);
  const index = options.findIndex((option) => JSON.stringify(option.value) === JSON.stringify(current));
  const origins = snapshot.document.settings.origins;
  let origin = origins[path];
  for (let parent = path.slice(0, path.lastIndexOf('/')); origin === undefined && parent !== ''; parent = parent.slice(0, parent.lastIndexOf('/'))) {
    origin = origins[parent];
  }
  const locked = lockKey === undefined ? undefined : snapshot.document.settings.locks[lockKey] ?? 'varied';
  return (
    <div className="concept-field" data-field={path}>
      <label className="flex min-w-0 flex-col gap-2">
        <span className="font-bold">{name}</span>
        <select aria-label={name} disabled={snapshot.document.confirmed || snapshot.busy || snapshot.catalog === null
          || (path.startsWith('/visual/character/') && snapshot.document.settings.visual.character === null)}
          value={index < 0 ? '' : index} onChange={(event) => {
            const option = options[Number(event.target.value)];
            if (option !== undefined) chooseConcept(path, option.value);
          }}>
          {index < 0 ? <option value="" disabled>{valueLabel(current, t)}</option> : null}
          {options.map((option, i) => <option key={i} value={i}>{option.label}</option>)}
        </select>
      </label>
      <div className="flex flex-wrap items-center gap-1 text-[15px]">
        <span className="concept-origin">{t(`concept.origin.${origin ?? 'default'}`)}</span>
        {origin === 'user' ? <span>{t('concept.changed')}</span> : null}
        {locked === undefined ? null : <button type="button" className="concept-small-button"
          disabled={snapshot.document.confirmed || snapshot.busy}
          aria-label={`${name}: ${t(`concept.lock.${locked}`)}`} aria-pressed={locked === 'locked'}
          onClick={() => toggleConceptLock(lockKey!)}>{t(`concept.lock.${locked}`)}</button>}
        <button type="button" className="concept-small-button"
          aria-label={`${name}: ${t('concept.reset')}`} disabled={snapshot.document.confirmed || snapshot.busy}
          onClick={() => resetConcept(path)}>{t('concept.reset')}</button>
      </div>
    </div>
  );
}

/**
 * Lock and origin controls for a value whose value field lives elsewhere, so
 * the fine-tune panel and the title row keep one value and the lock and reset stay reachable.
 */
function LockRow({ snapshot, path, name, lockKey, resettable = true }: {
  snapshot: ConceptSnapshot; path: string; name: string; lockKey?: LockKey; resettable?: boolean;
}) {
  const { t } = useLocale();
  const locked = lockKey === undefined ? undefined : snapshot.document.settings.locks[lockKey] ?? 'varied';
  const origin = originOf(snapshot.document.settings, path);
  return (
    <div className="concept-field" data-field={path}>
      <span className="font-bold">{name}</span>
      <div className="flex flex-wrap items-center gap-1 text-[15px]">
        <span className="concept-origin">{t(`concept.origin.${origin}`)}</span>
        {locked === undefined ? null : <button type="button" className="concept-small-button"
          disabled={snapshot.document.confirmed || snapshot.busy}
          aria-label={`${name}: ${t(`concept.lock.${locked}`)}`} aria-pressed={locked === 'locked'}
          onClick={() => toggleConceptLock(lockKey!)}>{t(`concept.lock.${locked}`)}</button>}
        {resettable ? <button type="button" className="concept-small-button"
          aria-label={`${name}: ${t('concept.reset')}`} disabled={snapshot.document.confirmed || snapshot.busy}
          onClick={() => resetConcept(path)}>{t('concept.reset')}</button> : null}
      </div>
    </div>
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
 * the face; a tile (art style) is its own 216 face. A `tag` marks a tile that
 * cannot be picked yet.
 */
function PictureCard({ title, description, selected, disabled, onClick, tile = false, tag }: {
  title: string; description?: string; selected: boolean; disabled: boolean; onClick: () => void; tile?: boolean;
  tag?: string;
}) {
  return (
    <button type="button" className={tile ? 'concept-card concept-card--tile' : 'concept-card'} aria-label={title} title={title}
      aria-pressed={selected} disabled={disabled} onClick={onClick} data-soon={tag === undefined ? undefined : ''}>
      <span className="concept-card__picture"><Image aria-hidden size={32} /></span>
      {tag === undefined ? null : <Tag className="concept-card__tag">{tag}</Tag>}
      <span className="concept-card__title">{clampCardText(title)}</span>
      <span className="concept-card__description">{clampCardText(description ?? '', CARD_DESCRIPTION_LIMIT)}</span>
    </button>
  );
}

function StoryCard({ id, title, description, selected, disabled, open, onPick, onToggle, panel }: {
  id: string; title: string; description: string; selected: boolean; disabled: boolean;
  open: boolean; onPick: () => void; onToggle: () => void; panel: ReactNode;
}) {
  const { t } = useLocale();
  return (
    <div className="concept-card-slot" data-card={id} data-selected={selected ? '' : undefined}>
      <PictureCard title={title} description={description} selected={selected} disabled={disabled} onClick={onPick} />
      <button type="button" className="concept-tune-toggle" aria-expanded={open}
        aria-label={`${title} ${t('concept.tune')}`} aria-controls={`concept-tune-${id}`}
        onClick={onToggle}>
        <span>{t('concept.tune')}</span><ChevronDown aria-hidden size={20} />
      </button>
      {open ? <section id={`concept-tune-${id}`} data-slot="concept-detail" className="concept-tune-panel" aria-label={`${title} ${t('concept.tune')}`}>
        {panel}
      </section> : null}
    </div>
  );
}

/** A value pick drawn as name, bold value and chevron; the select over it is the control. */
function TuneChip({ name, label, path, options, value, disabled, className }: {
  name: string; label?: string; path: string; options: { value: unknown; label: string }[]; value: unknown;
  disabled: boolean; className?: string;
}) {
  const { t } = useLocale();
  const index = options.findIndex((option) => JSON.stringify(option.value) === JSON.stringify(value));
  const current = index < 0 ? valueLabel(value, t) : options[index].label;
  return (
    <label className={className === undefined ? 'concept-tune-chip' : `concept-tune-chip ${className}`}>
      <span className="concept-tune-chip__label">{label ?? name}</span>
      <span className="concept-tune-chip__value">{current}</span>
      <ChevronDown aria-hidden size={20} className="concept-tune-chip__icon" />
      <select className="concept-tune-chip__select" aria-label={name} disabled={disabled}
        value={index < 0 ? '' : index} onChange={(event) => {
          const option = options[Number(event.target.value)];
          if (option !== undefined) chooseConcept(path, option.value);
        }}>
        {index < 0 ? <option value="" disabled>{current}</option> : null}
        {options.map((option, i) => <option key={i} value={i}>{option.label}</option>)}
      </select>
    </label>
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
  mode: 'reference' | 'style' | 'styleReference'; onClose: () => void;
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
    if ((mode !== 'style' && reference === undefined) || (mode === 'style' && prompt.trim() === '')) {
      setError('concept.entry.required'); throw new Error(t('concept.entry.required'));
    }
    setSubmitting(true);
    try {
      if (mode === 'reference') await analyzeConceptReference(reference!);
      else await createConceptStyle(prompt.trim() || t('concept.entry.referencePrompt'), reference);
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

export function ConceptScreen({ ComposerComponent }: { ComposerComponent: ComponentType<EntryComposerProps> }) {
  const { t, language } = useLocale();
  const snapshot = useConcept();
  const [entry, setEntry] = useState<'reference' | 'style' | 'styleReference' | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [openTune, setOpenTune] = useState<string | null>(null);
  useEffect(() => { ensureConcept(); }, []);
  if (snapshot === null) return <p role="status">{t('concept.loading')}</p>;
  const { document: doc, catalog } = snapshot;
  const settings = doc.settings;
  const style = catalog?.styles.find((item) => item.ref.id === settings.visual.art_style.id)?.manifest;
  const frozen = doc.confirmed || snapshot.busy || catalog === null;
  const choices = (values: readonly unknown[]) => values.map((value) => ({ value, label: valueLabel(value, t) }));
  const field = (path: string, values: readonly unknown[], lockKey?: LockKey) => (
    <Field snapshot={snapshot} path={path} name={t(`concept.field.${path.slice(1).replaceAll('/', '.')}`)}
      options={choices(values)} lockKey={lockKey} />
  );
  const activeCardId = cardIdForSettings(settings) ?? '';
  const pickCard = (id: string) => {
    if (frozen || id === activeCardId) return;
    chooseCardTune(id);
  };
  const onCard = (id: string) => {
    pickCard(id);
    if (openTune !== null) setOpenTune(id);
  };
  const toggleTune = (id: string) => {
    if (id !== activeCardId) {
      if (frozen) return;
      pickCard(id);
    }
    setOpenTune((open) => open === id ? null : id);
  };
  const openCardId = openTune !== null && openTune === activeCardId ? openTune : null;
  const tuneOrigins = ['/format/layout', '/format/register', '/format/humor']
    .map((path) => originOf(settings, path));
  const tuneSummary = tuneOrigins.includes('user')
    ? 'concept.tune.userValues'
    : tuneOrigins.includes('reference') ? 'concept.tune.referenceValues' : 'concept.tune.cardValues';
  const layoutOptions = (catalog?.layouts ?? []).map((item) => ({ value: item.ref, label: valueLabel(item.ref, t) }));
  const registerOptions = choices(SHORT_OPTIONS.register);
  const humorOptions = choices(SHORT_OPTIONS.humor);
  const tunePanel = (id: string) => (
    <>
      <div className="concept-tune-panel__head">
        <span className="concept-tune-panel__mark"><Image aria-hidden size={20} /></span>
        <div className="concept-tune-panel__names">
          <strong>{t(`concept.card.${id}`)}</strong><span>{t(tuneSummary)}</span>
        </div>
      </div>
      <div className="concept-tune-panel__grid">
        <TuneChip name={t('concept.field.format.layout')} path="/format/layout" options={layoutOptions} value={settings.format.layout} disabled={frozen} />
        <TuneChip name={t('concept.field.format.register')} path="/format/register" options={registerOptions} value={settings.format.register} disabled={frozen} />
        <TuneChip name={t('concept.field.format.humor')} path="/format/humor" options={humorOptions} value={settings.format.humor} disabled={frozen} />
      </div>
    </>
  );
  return (
    <section data-slot="concept-screen" className="concept-screen" aria-label={t('concept.title')}>
      <ScrollPane label={t('concept.document')} jumpLabel={t('shell.scroll.jump')} className="concept-content">
        <header className="concept-head">
          <div className="concept-head__names"><h1>{t('concept.title')}</h1>
            <p className="concept-head__topic">{doc.topic}</p>
            <p className="concept-head__scope">{t(doc.confirmed ? 'concept.confirmed' : 'concept.intro')}</p></div>
          <div className="concept-head__fields">
            <TuneChip className="concept-tune-chip--head" name={t('concept.field.target_duration_s')} label={t('concept.head.duration')}
              path="/target_duration_s" options={choices([30, 60, 120])} value={settings.target_duration_s} disabled={frozen} />
            <TuneChip className="concept-tune-chip--head" name={t('concept.field.format.scene_count')} label={t('concept.head.sceneCount')}
              path="/format/scene_count" options={[5, 8, 11].map((count) => ({ value: count, label: t('concept.head.sceneCountValue', { count }) }))}
              value={settings.format.scene_count} disabled={frozen} />
          </div>
        </header>
        {snapshot.error === null ? null : <div role="alert" className="concept-review">
          <p>{snapshot.error.startsWith('concept.') ? t(snapshot.error) : snapshot.error}</p>
          <Button variant="ghost" disabled={snapshot.loading} onClick={() => void reloadConceptCatalog()}>{t('concept.retryCatalog')}</Button>
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
            <span>{t('concept.story')}<small aria-hidden="true">{t('concept.chooseOne')}</small></span>
          </h2>
          <CardGrid>
            {STORIES.map((id) => (
              <StoryCard key={id} id={id} title={t(`concept.card.${id}`)} description={t(`concept.example.${id}`)}
                selected={activeCardId === id} disabled={frozen}
                open={openCardId === id} onPick={() => onCard(id)} onToggle={() => toggleTune(id)}
                panel={openCardId === id ? tunePanel(id) : null} />
            ))}
          </CardGrid>
        </section>
        <section aria-labelledby="concept-style-title" className="concept-group">
          <div className="concept-group__head">
            <h2 id="concept-style-title" className="concept-group__title">
              <span>{t('concept.style')}<small aria-hidden="true">{t('concept.chooseOne')}</small></span>
            </h2>
            <div className="flex flex-wrap gap-1">
              <Button variant="ghost" disabled={frozen} onClick={() => setEntry('style')}>{t('concept.entry.style')}</Button>
              <Button variant="ghost" disabled={frozen} onClick={() => setEntry('styleReference')}>{t('concept.entry.styleReference')}</Button>
            </div>
          </div>
          <CardGrid>
            {(catalog?.styles ?? []).map((item) => (
              <PictureCard key={item.ref.id} tile title={item.manifest.label[language]}
                description={t(item.manifest.origin === 'builtin' ? 'concept.style.builtin' : 'concept.style.mine')}
                selected={settings.visual.art_style.id === item.ref.id} disabled={frozen}
                onClick={() => chooseConcept('/visual/art_style', item.ref)} />
            ))}
            {SOON_STYLES.map((id) => (
              <PictureCard key={id} tile title={t(`concept.style.soon.${id}`)}
                description={t(`concept.style.soon.${id}.description`)} tag={t('concept.style.soon')}
                selected={false} disabled onClick={() => undefined} />
            ))}
          </CardGrid>
          <div className="concept-fields">
            <Field snapshot={snapshot} path="/visual/art_style" name={t('concept.field.visual.art_style')}
              options={(catalog?.styles ?? []).map((item) => ({ value: item.ref, label: item.manifest.label[language] }))} lockKey="art_style" />
            <Field snapshot={snapshot} path="/visual/theme_id" name={t('concept.field.visual.theme_id')}
              options={(style?.themes ?? []).map((theme) => ({ value: theme.id, label: theme.label[language] }))} lockKey="theme" />
          </div>
        </section>
        <section aria-labelledby="concept-character-title" className="concept-group">
          <h2 id="concept-character-title" className="concept-group__title"><span>{t('concept.character')}</span></h2>
          <div className="concept-fields">
            {SLOTS.map((slot) => <Field key={slot} snapshot={snapshot} path={`/visual/character/slots/${slot}`}
              name={t(`concept.slot.${slot}`)} options={choices([
                ...(['body', 'face'].includes(slot) ? [] : [null]), ...(style?.rig.slots[slot] ?? []),
              ])} lockKey={slot === 'body' ? 'character' : undefined} />)}
          </div>
          <div className="concept-example">
            <Image aria-hidden size={36} /><span>{t('concept.preview')}</span>
            <span>{valueLabel(settings.visual.art_style, t)} · {valueLabel(settings.visual.theme_id, t)} · {valueLabel(settings.visual.character?.slots.body, t)}</span>
          </div>
        </section>
        <details className="concept-group">
          <summary className="min-h-11 cursor-pointer font-bold">{t('concept.details')}</summary>
          <div className="concept-fields">
            {field('/caption/mode', ['sentence', 'phrase', 'typewriter'], 'caption_mode')}
            {field('/caption/font_id', catalog?.fonts ?? [settings.caption.font_id], 'caption_font')}
            {field('/caption/position', ['top', 'middle', 'bottom'])}
            {field('/motion/transition', ['cut', 'fade'])}
            {field('/motion/character_motion', ['none', 'pop', 'bob'])}
            {field('/audio/bgm/mood', ['curious', 'playful', 'tense', 'calm'], 'bgm')}
            {field('/audio/bgm/gain_db_x10', [-200, -120, -60])}
          </div>
          <h3 className="font-bold">{t('concept.locks')}</h3>
          <div className="concept-fields">
            <LockRow snapshot={snapshot} path="/target_duration_s" name={t('concept.field.target_duration_s')} />
            <LockRow snapshot={snapshot} path="/format/scene_count" name={t('concept.field.format.scene_count')} />
            <LockRow snapshot={snapshot} path="/format/story_structure" name={t('concept.field.format.story_structure')} lockKey="story_structure" resettable={false} />
            <LockRow snapshot={snapshot} path="/format/layout" name={t('concept.field.format.layout')} lockKey="layout" />
            <LockRow snapshot={snapshot} path="/format/character_role" name={t('concept.field.format.character_role')} lockKey="character_role" />
            <LockRow snapshot={snapshot} path="/format/register" name={t('concept.field.format.register')} lockKey="register" />
            <LockRow snapshot={snapshot} path="/format/humor" name={t('concept.field.format.humor')} lockKey="humor" />
          </div>
        </details>
        <details className="concept-group">
          <summary className="min-h-11 cursor-pointer font-bold">{t('concept.sceneLayer')}</summary>
          <p>{t('concept.sceneLayer.help')}</p>
        </details>
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
      <footer className="concept-footer">
        {snapshot.canUndo ? <Button variant="ghost" disabled={snapshot.busy || doc.confirmed} onClick={undoConcept}>{t('concept.undo')}</Button> : null}
        {doc.confirmed ? <span className="flex items-center gap-2"><LockKeyhole aria-hidden size={20} />{t('concept.confirmed.next')}</span>
          : <Button disabled={frozen || snapshot.pending !== null} onClick={() => setConfirming(true)}>{t('concept.confirm')}</Button>}
      </footer>
      {entry === null ? null : <Entry mode={entry} onClose={() => setEntry(null)} ComposerComponent={ComposerComponent} />}
      {confirming ? <Modal title={t('concept.confirm.title')} onClose={() => setConfirming(false)}
        actions={<Button disabled={snapshot.busy} onClick={() => void confirmConcept().then(() => setConfirming(false))}>{t('concept.confirm')}</Button>}>
        <p className="concept-dialog__help">{t('concept.confirm.help')}</p>
        <dl className="concept-dialog__values">
          <div><dt>{t('concept.story')}</dt><dd>{valueLabel(settings.format.story_structure, t)}</dd></div>
          <div><dt>{t('concept.style')}</dt><dd>{valueLabel(settings.visual.art_style, t)}</dd></div>
          <div><dt>{t('concept.character')}</dt><dd>{valueLabel(settings.visual.character, t)}</dd></div>
        </dl>
      </Modal> : null}
    </section>
  );
}
