import { useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { Image, LockKeyhole, Sparkles } from 'lucide-react';

import { useLocale } from '@/shared/lib/i18n/locale';
import { Button } from '@/shared/ui/button';
import { Chip } from '@/shared/ui/chip';

import {
  analyzeConceptReference, applyConceptPlan, chooseCard, chooseConcept,
  confirmConcept, createConceptStyle, ensureConcept, rejectConceptPlan,
  reloadConceptCatalog, resetConcept, toggleConceptLock, undoConcept, useConcept,
} from './store';
import type { Attachment, ConceptSnapshot, LockKey, Plan, Settings, Slot } from './types';
import './concept.css';

const STORIES = ['just_three', 'its_like', 'what_if'];
const STRUCTURES = ['numbered_three', 'single_analogy', 'hypothetical'];
const SLOTS: Slot[] = ['body', 'face', 'hair', 'hat', 'outfit', 'prop'];

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

function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
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
      <div className="flex flex-col gap-4 p-6">
        <h2 className="text-[22px] font-bold">{title}</h2>
        {children}
        <button ref={cancel} type="button" className="concept-small-button" onClick={onClose}>
          {t('concept.cancel')}
        </button>
      </div>
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

export function ChangeReview({ plan, settings, busy }: { plan: Plan; settings: Settings; busy: boolean }) {
  const { t } = useLocale();
  const name = (path: string) => {
    const normalized = path.replace(/^\/settings/u, '');
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
        <Button variant="ghost" disabled={busy} onClick={rejectConceptPlan}>{t('concept.keep')}</Button>
        <Button disabled={busy} onClick={() => void applyConceptPlan()}>{t('concept.apply')}</Button>
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
      <p>{t('concept.mockNotice')}</p>
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
  return (
    <section data-slot="concept-screen" className="concept-screen" aria-label={t('concept.title')}>
      <div className="concept-content">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div><h1 className="text-[22px] font-bold">{t('concept.title')}</h1>
            <p>{doc.topic}</p><p className="text-[15px]">{t(doc.confirmed ? 'concept.confirmed' : 'concept.intro')}</p></div>
          <div className="flex flex-wrap gap-3">
            {field('/target_duration_s', [30, 60, 120])}
            {field('/format/scene_count', [5, 8, 11])}
          </div>
        </header>
        <p className="text-[15px]">{t('concept.mockNotice')}</p>
        {snapshot.error === null ? null : <div role="alert" className="concept-review">
          <p>{snapshot.error.startsWith('concept.') ? t(snapshot.error) : snapshot.error}</p>
          <Button variant="ghost" disabled={snapshot.loading} onClick={() => void reloadConceptCatalog()}>{t('concept.retryCatalog')}</Button>
        </div>}
        {snapshot.loading ? <p role="status">{t('concept.loading')}</p> : null}
        <section aria-labelledby="concept-story-title" className="concept-group">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="concept-story-title" className="text-[22px] font-bold">{t('concept.story')}</h2>
            <Button variant="ghost" disabled={frozen} onClick={() => setEntry('reference')}>{t('concept.reference')}</Button>
          </div>
          <div className="concept-tiles">
            {STORIES.map((id, index) => <button type="button" key={id} disabled={frozen}
              className="concept-tile" aria-pressed={settings.format.story_structure === STRUCTURES[index]}
              onClick={() => chooseCard(id)}>
              <span className="concept-picture"><Image aria-hidden size={28} /></span>
              <strong>{t(`concept.card.${id}`)}</strong><span>{t(`concept.example.${id}`)}</span>
            </button>)}
          </div>
          <div className="concept-fields">
            {field('/format/story_structure', STRUCTURES, 'story_structure')}
            {field('/format/register', ['friendly', 'neutral', 'casual'], 'register')}
            {field('/format/humor', ['none', 'light'], 'humor')}
          </div>
        </section>
        <section aria-labelledby="concept-style-title" className="concept-group">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 id="concept-style-title" className="text-[22px] font-bold">{t('concept.style')}</h2>
            <div className="flex flex-wrap gap-1">
              <Button variant="ghost" disabled={frozen} onClick={() => setEntry('style')}>{t('concept.entry.style')}</Button>
              <Button variant="ghost" disabled={frozen} onClick={() => setEntry('styleReference')}>{t('concept.entry.styleReference')}</Button>
            </div>
          </div>
          <p>{t('concept.style.groups')}</p>
          <div className="concept-tiles">
            {(catalog?.styles ?? []).map((item) => <button type="button" key={item.ref.id}
              disabled={frozen} className="concept-tile" aria-pressed={settings.visual.art_style.id === item.ref.id}
              onClick={() => chooseConcept('/visual/art_style', item.ref)}>
              <span className="concept-picture"><Sparkles aria-hidden size={28} /></span>
              <strong>{item.manifest.label[language]}</strong>
              <span>{t(item.manifest.origin === 'builtin' ? 'concept.style.builtin' : 'concept.style.mine')}</span>
            </button>)}
          </div>
          <div className="concept-fields">
            <Field snapshot={snapshot} path="/visual/art_style" name={t('concept.field.visual.art_style')}
              options={(catalog?.styles ?? []).map((item) => ({ value: item.ref, label: item.manifest.label[language] }))} lockKey="art_style" />
            <Field snapshot={snapshot} path="/visual/theme_id" name={t('concept.field.visual.theme_id')}
              options={(style?.themes ?? []).map((theme) => ({ value: theme.id, label: theme.label[language] }))} lockKey="theme" />
          </div>
        </section>
        <section aria-labelledby="concept-character-title" className="concept-group">
          <h2 id="concept-character-title" className="text-[22px] font-bold">{t('concept.character')}</h2>
          <div className="concept-fields">
            {field('/format/character_role', ['none', 'presenter', 'subject'], 'character_role')}
            {SLOTS.map((slot) => <Field key={slot} snapshot={snapshot} path={`/visual/character/slots/${slot}`}
              name={t(`concept.slot.${slot}`)} options={choices([
                ...(['body', 'face'].includes(slot) ? [] : [null]), ...(style?.rig.slots[slot] ?? []),
              ])} lockKey={slot === 'body' ? 'character' : undefined} />)}
          </div>
          <div className="concept-example" role="img" aria-label={t('concept.preview')}>
            <Image aria-hidden size={36} /><span>{t('concept.preview')}</span>
            <span>{valueLabel(settings.visual.art_style, t)} · {valueLabel(settings.visual.theme_id, t)} · {valueLabel(settings.visual.character?.slots.body, t)}</span>
          </div>
        </section>
        <details className="concept-group">
          <summary className="min-h-11 cursor-pointer font-bold">{t('concept.details')}</summary>
          <div className="concept-fields">
            <Field snapshot={snapshot} path="/format/layout" name={t('concept.field.format.layout')}
              options={(catalog?.layouts ?? []).map((item) => ({ value: item.ref, label: valueLabel(item.ref, t) }))} lockKey="layout" />
            {field('/caption/mode', ['sentence', 'phrase', 'typewriter'], 'caption_mode')}
            {field('/caption/font_id', catalog?.fonts ?? [settings.caption.font_id], 'caption_font')}
            {field('/caption/position', ['top', 'middle', 'bottom'])}
            {field('/motion/transition', ['cut', 'fade'])}
            {field('/motion/character_motion', ['none', 'pop', 'bob'])}
            {field('/audio/bgm/mood', ['curious', 'playful', 'tense', 'calm'], 'bgm')}
            {field('/audio/bgm/gain_db_x10', [-200, -120, -60])}
          </div>
        </details>
        <details className="concept-group">
          <summary className="min-h-11 cursor-pointer font-bold">{t('concept.sceneLayer')}</summary>
          <p>{t('concept.sceneLayer.help')}</p>
        </details>
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
      </div>
      <footer className="concept-footer">
        {snapshot.canUndo ? <Button variant="ghost" disabled={snapshot.busy || doc.confirmed} onClick={undoConcept}>{t('concept.undo')}</Button> : null}
        {doc.confirmed ? <span className="flex items-center gap-2"><LockKeyhole aria-hidden size={20} />{t('concept.confirmed.next')}</span>
          : <Button disabled={frozen || snapshot.pending !== null} onClick={() => setConfirming(true)}>{t('concept.confirm')}</Button>}
      </footer>
      {entry === null ? null : <Entry mode={entry} onClose={() => setEntry(null)} ComposerComponent={ComposerComponent} />}
      {confirming ? <Modal title={t('concept.confirm.title')} onClose={() => setConfirming(false)}>
        <p>{t('concept.confirm.help')}</p>
        <ul className="list-disc pl-5"><li>{valueLabel(settings.format.story_structure, t)}</li>
          <li>{valueLabel(settings.visual.art_style, t)}</li><li>{valueLabel(settings.visual.character, t)}</li></ul>
        <p>{t('concept.confirm.kept')}</p>
        <Button disabled={snapshot.busy} onClick={() => void confirmConcept().then(() => setConfirming(false))}>{t('concept.confirm')}</Button>
      </Modal> : null}
    </section>
  );
}
