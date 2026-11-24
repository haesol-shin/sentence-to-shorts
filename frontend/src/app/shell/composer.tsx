import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react';
import { Check, FileText, Film, Info, Link2, Music, Plus, X } from 'lucide-react';

import type { Language } from '@/shared/api/client';
import { chatProposal } from '@/features/concept/model';
import {
  applyConceptPlan,
  chooseConcept,
  getConceptSnapshot,
  loadConceptDeployment,
  sendConcept,
  setConceptDraft,
  useConcept,
} from '@/features/concept/store';
import { useEditOptional } from '@/features/edit/edit-context';
import { sceneNumber } from '@/features/edit/model';
import { ChangeReview } from '@/features/concept/concept-screen';
import {
  MAX_TEXT_ATTACHMENTS,
  attachmentKindOf,
  formatDurationMs,
  linkPolicy,
  newAttachmentId,
  readTextFile,
  validateReferenceUrl,
  type Deployment,
} from '@/features/concept/attachments';
import type { Attachment } from '@/features/concept/types';
import { sceneNumber as scriptSceneNumber } from '@/features/script/model';
import { applyTone, clearTarget as clearScriptTarget, dismissTone, useScript } from '@/features/script/store';
import { LANGUAGES } from '@/shared/lib/i18n/catalog';
import { useLocale } from '@/shared/lib/i18n/locale';
import { useLoad } from '@/shared/lib/use-load';
import { Button } from '@/components/Button/Button';
import { Chip } from '@/components/Chip/Chip';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { IconButton } from '@/components/IconButton/IconButton';
import { SendButton } from '@/components/SendButton/SendButton';
import { Tag } from '@/components/Tag/Tag';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { cn } from '@/shared/lib/utils';

import { useShellView } from './shell-view';

/** One line of the text field; ten of them plus the box padding is the tallest the box may grow. */
const LINE_HEIGHT = 24;
const FIELD_PADDING = 20;
const MAX_TEXT_HEIGHT = LINE_HEIGHT * 10 + FIELD_PADDING;
const TOUCH_TARGET = 44;
const SEND_VISUAL = 32;
const DURATION_VALUES = [30, 60, 120] as const;

const KIND_LABEL_KEYS: Record<Attachment['kind'], string> = {
  reference: 'concept.composer.kindReference',
  bgm: 'concept.composer.kindBgm',
  text: 'concept.composer.kindText',
  link: 'concept.composer.kindLink',
};



/** Reference links stay unavailable until the host identifies itself as local. */
export function useDeployment(ready = true): Deployment {
  const deployment = useLoad(loadConceptDeployment, ready);
  return deployment.data === 'local' ? 'local' : 'hosted';
}

type ComposerSubmit = (attachments: Attachment[]) => void | Promise<void>;

interface ComposerBoxProps {
  label: string;
  placeholder: string;
  sendLabel: string;
  /** The first screen rounds its box 24; the chat face rounds it 28. */
  face?: 'first' | 'chat';
  onCancel?: () => void;
  cancelActive?: boolean;
  value: string;
  disabled?: boolean;
  onChange?: (value: string) => void;
  onSubmit?: ComposerSubmit;
  card?: { label: string } | null;
  onClearCard?: () => void;
  targetChip?: { label: string; removeLabel: string; onRemove: () => void } | null;
  options?: ReactNode;
  language?: Language;
  duration?: number;
  onLanguageChange?: (language: Language) => void;
  onDurationChange?: (duration: number) => void;
  deployment?: Deployment;
  /** Read once on mount; the box always owns its attachment list afterwards. */
  initialAttachments?: Attachment[];
  onAttachmentsChange?: (attachments: Attachment[]) => void;
  onEditBgm?: (file: File, isAudio: boolean) => void;
  editBgmBusy?: boolean;
  className?: string;
}

function AttachmentIcon({ kind }: { kind: Attachment['kind'] }) {
  if (kind === 'reference') {
    return <Film aria-hidden size={16} className="shrink-0" />;
  }
  if (kind === 'bgm') {
    return <Music aria-hidden size={16} className="shrink-0" />;
  }
  if (kind === 'link') {
    return <Link2 aria-hidden size={16} className="shrink-0" />;
  }
  return <FileText aria-hidden size={16} className="shrink-0" />;
}

function AttachmentChip({
  attachment,
  disabled,
  onRemove,
}: {
  attachment: Attachment;
  disabled: boolean;
  onRemove: () => void;
}) {
  const { t } = useLocale();
  const showsDuration = attachment.kind === 'reference' || attachment.kind === 'bgm';
  const status =
    attachment.state === 'receiving'
      ? t('concept.composer.linkReceiving')
      : attachment.state === 'failed'
        ? t('concept.composer.linkFailed')
        : null;

  const detail = [
    t(KIND_LABEL_KEYS[attachment.kind]),
    showsDuration
      ? attachment.durationMs === undefined
        ? t('concept.composer.durationUnknown')
        : formatDurationMs(attachment.durationMs)
      : null,
    status,
  ].filter((part) => part !== null);

  return (
    <span
      data-slot="composer-attachment"
      data-kind={attachment.kind}
      data-attachment-state={attachment.state}
      className="inline-flex max-w-full"
    >
      <Chip
        state={
          attachment.state === 'receiving' ? 'loading' : attachment.state === 'failed' ? 'error' : 'default'
        }
        lead={<AttachmentIcon kind={attachment.kind} />}
        remove={
          <CloseButton
            size="sm"
            label={t('concept.composer.attachmentRemove', { name: attachment.name })}
            disabled={disabled}
            onClick={onRemove}
          />
        }
      >
        {[attachment.name, ...detail].join(' · ')}
      </Chip>
    </span>
  );
}

function MenuItem({
  label,
  onSelect,
  disabled = false,
  soon,
  reason,
}: {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  soon?: string;
  reason?: string;
}) {
  const button = (
    <button
      type="button"
      role="menuitem"
      aria-disabled={disabled ? true : undefined}
      data-disabled={disabled ? 'true' : undefined}
      onClick={() => {
        if (!disabled) {
          onSelect();
        }
      }}
      className={cn(
        'flex min-h-11 w-full items-center gap-2 rounded-[var(--radius-panel)] px-3 text-left text-[15px]',
        disabled
          ? 'cursor-not-allowed text-[var(--text-disabled)]'
          : 'text-[var(--text)] hover:bg-[var(--surface-muted)]',
      )}
    >
      <span className="min-w-0 flex-1">{label}</span>
      {soon === undefined ? null : (
        <Tag variant="neutral" icon={<Info aria-hidden size={16} />}>
          {soon}
        </Tag>
      )}
    </button>
  );

  if (!disabled || reason === undefined) {
    return button;
  }
  return (
    <Tooltip content={reason} side="top">
      {button}
    </Tooltip>
  );
}

function ComposerBox({
  label,
  placeholder,
  sendLabel,
  face = 'first',
  onCancel,
  cancelActive = false,
  value,
  disabled = false,
  onChange,
  onSubmit,
  card = null,
  onClearCard,
  targetChip = null,
  options,
  language,
  duration,
  onLanguageChange,
  onDurationChange,
  deployment,
  initialAttachments,
  onAttachmentsChange,
  onEditBgm,
  editBgmBusy = false,
  className,
}: ComposerBoxProps) {
  const { t } = useLocale();
  const [attachments, setAttachments] = useState<Attachment[]>(initialAttachments ?? []);
  const attachmentsRef = useRef<Attachment[]>(initialAttachments ?? []);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuUp, setMenuUp] = useState(true);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkValue, setLinkValue] = useState('');
  const [consent, setConsent] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const referenceInput = useRef<HTMLInputElement>(null);
  const bgmInput = useRef<HTMLInputElement>(null);
  const textInput = useRef<HTMLInputElement>(null);

  const busy = disabled || submitting;
  const canSend =
    !busy && onSubmit !== undefined && (value.trim() !== '' || attachments.length > 0);
  const discoveredDeployment = useDeployment(deployment === undefined);
  const policy = linkPolicy(deployment ?? discoveredDeployment);

  const updateAttachments = useCallback(
    (next: Attachment[]) => {
      attachmentsRef.current = next;
      setAttachments(next);
      onAttachmentsChange?.(next);
    },
    [onAttachmentsChange],
  );

  const measureText = useCallback(() => {
    const node = textareaRef.current;
    if (node === null) {
      return;
    }
    // Measuring from `auto` keeps the box from growing beyond its content.
    node.style.height = 'auto';
    const needed = node.scrollHeight;
    const next = Math.min(Math.max(needed, LINE_HEIGHT), MAX_TEXT_HEIGHT);
    node.style.height = `${next}px`;
    const nextOverflowing = needed > MAX_TEXT_HEIGHT;
    setOverflowing((previous) => (previous === nextOverflowing ? previous : nextOverflowing));
  }, []);

  useLayoutEffect(() => {
    measureText();
  }, [measureText, value, disabled]);

  useEffect(() => {
    const onResize = () => measureText();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [measureText]);

  useEffect(() => {
    if (!menuOpen && !linkOpen) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false);
        setLinkOpen(false);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [linkOpen, menuOpen]);

  const addFiles = async (
    files: File[],
    fallbackKind?: 'reference' | 'bgm' | 'text',
  ): Promise<void> => {
    setError(null);
    for (const file of files) {
      const detected = attachmentKindOf(file);
      if (onEditBgm !== undefined && (fallbackKind === 'bgm' || detected === 'bgm')) {
        onEditBgm(file, detected === 'bgm');
        continue;
      }
      const kind = detected ?? fallbackKind;
      if (kind === 'image') {
        setError(t('concept.composer.fileUnsupported', { name: file.name }));
        continue;
      }
      if (kind === undefined || kind === null) {
        setError(t('concept.composer.fileUnsupported', { name: file.name }));
        continue;
      }
      if (
        kind === 'text' &&
        attachmentsRef.current.filter((attachment) => attachment.kind === 'text').length >=
          MAX_TEXT_ATTACHMENTS
      ) {
        setError(t('concept.composer.fileTooMany', { max: MAX_TEXT_ATTACHMENTS }));
        continue;
      }

      let text: string | undefined;
      if (kind === 'text') {
        try {
          text = await readTextFile(file);
        } catch {
          setError(t('concept.composer.fileReadFailed', { name: file.name }));
          continue;
        }
      }
      if (
        kind === 'text' &&
        attachmentsRef.current.filter((attachment) => attachment.kind === 'text').length >=
          MAX_TEXT_ATTACHMENTS
      ) {
        setError(t('concept.composer.fileTooMany', { max: MAX_TEXT_ATTACHMENTS }));
        continue;
      }

      const attachment: Attachment = {
        id: newAttachmentId(),
        kind,
        name: file.name,
        state: 'ready',
        ...(kind === 'text' ? { text } : { file }),
      };
      updateAttachments([...attachmentsRef.current, attachment]);
    }
  };

  const onFileInput = (
    kind: 'reference' | 'bgm' | 'text',
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (files.length > 0) {
      void addFiles(files, kind);
    }
  };

  const openPicker = (input: HTMLInputElement | null) => {
    setMenuOpen(false);
    setError(null);
    input?.click();
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) {
      void addFiles(files);
    }
  };

  const onDragLeave = (event: DragEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as Node | null;
    if (next === null || !event.currentTarget.contains(next)) {
      setDragging(false);
    }
  };

  const submitLink = () => {
    if (!policy.enabled) {
      setError(t('concept.composer.hostedLinkReason'));
      return;
    }
    if (policy.consentRequired && !consent) {
      return;
    }
    const checked = validateReferenceUrl(linkValue);
    if (!checked.ok) {
      setError(
        checked.reason === 'length'
          ? t('concept.composer.linkTooLong')
          : t('concept.composer.linkInvalid'),
      );
      return;
    }
    const host = new URL(checked.url).hostname.replace(/^www\./u, '');
    updateAttachments([
      ...attachmentsRef.current,
      {
        id: newAttachmentId(),
        kind: 'link',
        name: host,
        url: checked.url,
        state: 'receiving',
      },
    ]);
    setLinkOpen(false);
    setLinkValue('');
    setConsent(false);
    setError(null);
  };

  const submit = async () => {
    if (!canSend || submitting) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setMenuOpen(false);
    setLinkOpen(false);
    const payload: Attachment[] = attachmentsRef.current.map((attachment) =>
      attachment.kind === 'link' ? { ...attachment, state: 'ready' } : { ...attachment },
    );
    try {
      await onSubmit?.(payload);
      // Files dropped or read while the send ran were not in the payload; keep them.
      const sent = new Set(payload.map((attachment) => attachment.id));
      updateAttachments(attachmentsRef.current.filter((attachment) => !sent.has(attachment.id)));
    } catch {
      setError(t('concept.composer.sendFailed'));
      updateAttachments(
        attachmentsRef.current.map((attachment) =>
          attachment.kind === 'link' && attachment.state === 'receiving'
            ? { ...attachment, state: 'failed' }
            : attachment,
        ),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    // Enter that settles a Korean or Japanese composition is not a send.
    if (event.nativeEvent.isComposing || event.keyCode === 229) {
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  const languageName = (code: Language) =>
    code === 'ko' ? t('concept.composer.languageKo') : t('concept.composer.languageEn');
  const durationName = (seconds: number) => {
    if (seconds === 30) return t('concept.composer.duration30');
    if (seconds === 60) return t('concept.composer.duration60');
    if (seconds === 120) return t('concept.composer.duration120');
    return `${seconds}s`;
  };
  const maskStyle = overflowing
    ? {
        maskImage: 'linear-gradient(to bottom, transparent 0, black 20px)',
        WebkitMaskImage: 'linear-gradient(to bottom, transparent 0, black 20px)',
      }
    : undefined;

  return (
    <div
      ref={rootRef}
      data-slot="composer"
      data-state={onSubmit === undefined ? 'placeholder' : 'active'}
      data-dragging={dragging ? 'true' : undefined}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={cn(
        'relative flex w-full flex-col gap-2 border-2 border-transparent bg-[var(--surface-muted)] p-3 transition-colors',
        face === 'first' ? 'rounded-[var(--radius-input)]' : 'rounded-[var(--radius-composer)]',
        dragging && 'border-dashed border-[var(--text-muted)]',
        className,
      )}
    >
      {card === null && targetChip === null && attachments.length === 0 ? null : (
        <div data-slot="composer-attachments" className="flex min-w-0 flex-col items-start gap-1">
          {targetChip === null ? null : (
            <span data-slot="composer-target" data-kind="scene" className="inline-flex max-w-full">
              <Chip
                remove={
                  <CloseButton
                    size="sm"
                    label={targetChip.removeLabel}
                    disabled={submitting}
                    onClick={targetChip.onRemove}
                  />
                }
              >
                {targetChip.label}
              </Chip>
            </span>
          )}
          {card === null ? null : (
            <span data-slot="composer-action" data-kind="card" className="inline-flex max-w-full">
              <Chip
                remove={
                  onClearCard === undefined ? undefined : (
                    <CloseButton
                      size="sm"
                      label={t('shell.first.cardChipRemove')}
                      disabled={busy}
                      onClick={onClearCard}
                    />
                  )
                }
              >
                {t('shell.first.cardChip', { label: card.label })}
              </Chip>
            </span>
          )}
          {attachments.map((attachment) => (
            <AttachmentChip
              key={attachment.id}
              attachment={attachment}
              disabled={busy}
              onRemove={() =>
                updateAttachments(
                  attachmentsRef.current.filter((item) => item.id !== attachment.id),
                )
              }
            />
          ))}
        </div>
      )}

      <textarea
        ref={textareaRef}
        aria-label={label}
        placeholder={placeholder}
        value={value}
        disabled={busy}
        rows={1}
        data-slot="composer-input"
        onChange={(event) => onChange?.(event.target.value)}
        onKeyDown={onKeyDown}
        onFocus={(event) => {
          // A browser that only shrinks the visual viewport still scrolls the
          // focused input into sight; the dock handles the rest of the inset.
          event.currentTarget.scrollIntoView?.({ block: 'nearest' });
        }}
        style={maskStyle}
        className="block max-h-[260px] w-full resize-none overflow-y-auto bg-transparent px-0 py-2.5 text-[17px] leading-6 text-[var(--text-strong)] outline-none placeholder:text-[var(--text-disabled)] disabled:cursor-not-allowed"
      />

      {linkOpen ? (
        <div data-slot="composer-link" className="flex flex-col gap-2 text-[15px]">
          <p className="text-[var(--text-muted)]">{t('concept.composer.linkWarning')}</p>
          <input
            aria-label={t('concept.composer.linkLabel')}
            placeholder={t('concept.composer.linkPlaceholder')}
            value={linkValue}
            disabled={busy}
            onChange={(event) => {
              setLinkValue(event.target.value);
              setError(null);
            }}
            className="h-11 w-full rounded-[var(--radius-panel)] bg-[var(--surface)] px-3 text-[15px] text-[var(--text-strong)] outline-none disabled:cursor-not-allowed"
          />
          {policy.consentRequired ? (
            <label className="flex min-h-11 items-center gap-2 text-[var(--text)]">
              <input
                type="checkbox"
                checked={consent}
                disabled={busy}
                onChange={(event) => setConsent(event.target.checked)}
              />
              <span>{t('concept.composer.linkConsent')}</span>
            </label>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setLinkOpen(false);
                setLinkValue('');
                setConsent(false);
                setError(null);
              }}
            >
              {t('concept.composer.cancel')}
            </Button>
            <Button
              disabled={
                busy ||
                linkValue.trim() === '' ||
                (policy.consentRequired && !consent)
              }
              onClick={submitLink}
            >
              {t('concept.composer.attachLink')}
            </Button>
          </div>
        </div>
      ) : null}

      {error === null ? null : (
        <p role="alert" data-slot="composer-error" className="text-[15px] text-[var(--text)]">
          {error}
        </p>
      )}

      <div
        data-slot="composer-actions"
        // One row at every width: wrapping would drop the send button onto a
        // second line (WebKit sizes a select wider than Blink does) and make
        // the docked box taller than the room a phone keyboard leaves it.
        className="flex min-w-0 items-center gap-2"
      >
        <div data-slot="composer-plus" data-hit={TOUCH_TARGET} className="relative shrink-0">
          <IconButton
            label={t('concept.composer.plus')}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            disabled={busy}
            onClick={() => {
              if (!menuOpen) {
                setMenuUp((rootRef.current?.getBoundingClientRect().top ?? 0) >= 260);
              }
              setMenuOpen((open) => !open);
              setLinkOpen(false);
              setError(null);
            }}
          >
            <Plus aria-hidden size={20} />
          </IconButton>
          {menuOpen ? (
            <div
              role="menu"
              aria-label={t('concept.composer.menuLabel')}
              data-slot="composer-menu"
              className={cn(
                'absolute left-0 z-30 flex w-64 max-w-[calc(100vw-32px)] flex-col gap-1 rounded-[var(--radius-panel)] bg-[var(--surface)] p-1 shadow-lg',
                menuUp ? 'bottom-[calc(100%+8px)]' : 'top-[calc(100%+8px)]',
              )}
            >
              <MenuItem
                label={t('concept.composer.addReference')}
                onSelect={() => openPicker(referenceInput.current)}
              />
              <MenuItem
                label={t('concept.composer.addLink')}
                disabled={!policy.enabled}
                reason={t('concept.composer.hostedLinkReason')}
                onSelect={() => {
                  setMenuOpen(false);
                  setLinkOpen(true);
                  setError(null);
                }}
              />
              <MenuItem
                label={t('concept.composer.addBgm')}
                disabled={editBgmBusy}
                onSelect={() => openPicker(bgmInput.current)}
              />
              <MenuItem
                label={t('concept.composer.addImage')}
                disabled
                soon={t('concept.composer.soon')}
                reason={t('concept.composer.imageSoonReason')}
                onSelect={() => undefined}
              />
              <MenuItem
                label={t('concept.composer.addText')}
                onSelect={() => openPicker(textInput.current)}
              />
            </div>
          ) : null}
        </div>

        {options}

        {language === undefined ? null : onLanguageChange === undefined ? (
          <span data-slot="composer-action" data-kind="language" className="inline-flex min-w-0">
            <Chip>{languageName(language)}</Chip>
          </span>
        ) : (
          <span data-slot="composer-action" data-kind="language" className="inline-flex min-w-0 shrink">
            <select
              aria-label={t('concept.composer.languageLabel')}
              value={language}
              disabled={busy}
              onChange={(event) => onLanguageChange(event.target.value as Language)}
              className="h-9 w-full min-w-0 max-w-32 rounded-[var(--radius-capsule)] bg-[var(--surface-muted)] px-2.5 text-[15px] text-[var(--text)] disabled:cursor-not-allowed disabled:text-[var(--text-disabled)]"
            >
              {LANGUAGES.map((code) => (
                <option key={code} value={code}>
                  {languageName(code)}
                </option>
              ))}
            </select>
          </span>
        )}

        {duration === undefined ? null : onDurationChange === undefined ? (
          <span data-slot="composer-action" data-kind="duration" className="inline-flex min-w-0">
            <Chip>{durationName(duration)}</Chip>
          </span>
        ) : (
          <span data-slot="composer-action" data-kind="duration" className="inline-flex min-w-0 shrink">
            <select
              aria-label={t('concept.composer.durationLabel')}
              value={duration}
              disabled={busy}
              onChange={(event) => onDurationChange(Number(event.target.value))}
              className="h-9 w-full min-w-0 rounded-[var(--radius-capsule)] bg-[var(--surface-muted)] px-2.5 text-[15px] text-[var(--text)] disabled:cursor-not-allowed disabled:text-[var(--text-disabled)]"
            >
              {DURATION_VALUES.map((seconds) => (
                <option key={seconds} value={seconds}>
                  {durationName(seconds)}
                </option>
              ))}
            </select>
          </span>
        )}

        <div
          data-slot="composer-send"
          data-hit={TOUCH_TARGET}
          className="ml-auto flex size-11 shrink-0 items-center justify-center"
        >
          {onCancel !== undefined && (cancelActive || disabled) ? (
            <SendButton
              label={sendLabel}
              stopLabel={t('edit.composer.cancel')}
              loading
              onClick={onCancel}
              data-slot="composer-send-visual"
              data-size={SEND_VISUAL}
            />
          ) : (
            <SendButton
              label={sendLabel}
              stopLabel={t('edit.composer.cancel')}
              disabled={!canSend}
              onClick={() => void submit()}
              data-slot="composer-send-visual"
              data-size={SEND_VISUAL}
            />
          )}
        </div>
      </div>

      <input
        ref={referenceInput}
        data-slot="composer-file"
        data-kind="reference"
        type="file"
        accept="video/*"
        multiple
        className="hidden"
        onChange={(event) => onFileInput('reference', event)}
      />
      <input
        ref={bgmInput}
        data-slot="composer-file"
        data-kind="bgm"
        type="file"
        accept="audio/*"
        multiple={onEditBgm === undefined}
        className="hidden"
        onChange={(event) => onFileInput('bgm', event)}
      />
      <input
        ref={textInput}
        data-slot="composer-file"
        data-kind="text"
        type="file"
        accept=".md,.txt,text/markdown,text/plain"
        multiple
        className="hidden"
        onChange={(event) => onFileInput('text', event)}
      />
    </div>
  );
}

/** The first screen and the conversation rail use this one input. */
export function Composer({
  value,
  onChange,
  onSubmit,
  disabled = false,
  ...rest
}: Omit<ComposerBoxProps, 'disabled' | 'value' | 'onChange' | 'onSubmit'> & {
  value: string;
  onChange: (value: string) => void;
  onSubmit: ComposerSubmit;
  disabled?: boolean;
}) {
  return (
    <ComposerBox
      {...rest}
      value={value}
      onChange={onChange}
      onSubmit={onSubmit}
      disabled={disabled}
    />
  );
}

/**
 * The edit conversation. The scene chip is the request target; clearing it
 * sends the sentence to the whole video. A whole-video sentence that changes
 * the tone waits for the user's decision before the concept's tone changes.
 * The input stays active while a video job runs, because the job belongs to
 * the top bar, not the composer.
 */
function EditComposer({
  reason,
  rest,
}: {
  reason?: string;
  rest: Omit<ComposerBoxProps, 'value' | 'onChange' | 'onSubmit' | 'disabled'>;
}) {
  const { t } = useLocale();
  const edit = useEditOptional();
  const [value, setValue] = useState('');
  const concept = useConcept();
  const [toneRequest, setToneRequest] = useState<string | null>(null);
  const [toneFailed, setToneFailed] = useState(false);
  const decideTone = async (change: boolean) => {
    const text = toneRequest;
    setToneRequest(null);
    if (!change || text === null) return;
    setToneFailed(false);
    try {
      await sendConcept(text);
      if (getConceptSnapshot()?.pending?.status === 'proposed') await applyConceptPlan();
    } catch {
      setToneFailed(true);
    }
  };
  if (edit === null || edit.video === null) {
    return (
      <Tooltip content={reason ?? t('concept.composer.noSession')} side="top">
        <div className="w-full">
          <ComposerBox
            face="chat"
            label={rest.label}
            placeholder={rest.placeholder}
            sendLabel={rest.sendLabel}
            value=""
            disabled
          />
        </div>
      </Tooltip>
    );
  }
  const number = edit.targetId === null ? 0 : sceneNumber(edit.video, edit.targetId);
  const bgm = edit.bgmWork;
  return (
    <div className="flex w-full flex-col gap-2">
      {toneRequest === null ? null : (
        <div className="flex flex-col gap-2">
          <p>{t('edit.tone.preview')}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" iconStart={<X aria-hidden size={16} />} onClick={() => void decideTone(false)}>{t('edit.tone.keepAll')}</Button>
            <Button iconStart={<Check aria-hidden size={16} />} onClick={() => void decideTone(true)}>{t('edit.tone.applyAll')}</Button>
          </div>
        </div>
      )}
      {toneFailed ? <p role="alert">{t('edit.tone.failed')}</p> : null}
      {bgm.error?.kind === 'upload' ? (
        <p role="alert" data-slot="bgm-upload-error">{t(bgm.error.key)}</p>
      ) : null}
      {bgm.running === 'upload' ? (
        <Button variant="ghost" disabled={bgm.stopping} onClick={bgm.stop}>
          {t(bgm.stopping ? 'audio.bgm.stopping' : 'audio.bgm.stopUpload')}
        </Button>
      ) : null}
      <Composer
        {...rest}
        face="chat"
        label={rest.label}
        placeholder={number > 0 ? t('edit.composer.placeholderScene', { number }) : t('edit.composer.placeholder')}
        sendLabel={rest.sendLabel}
        onCancel={edit.chatBusy ? edit.cancelChat : undefined}
        cancelActive={edit.chatBusy}
        onEditBgm={bgm.upload}
        editBgmBusy={bgm.running !== null || bgm.waitingToApply}
        value={value}
        onChange={setValue}
        onSubmit={() => {
          const text = value.trim();
          if (text === '') return;
          const changesTone =
            number === 0 &&
            concept !== null &&
            chatProposal(concept.document.settings, text, null).ops.some((op) => op.path === '/format/register');
          if (changesTone) {
            setToneFailed(false);
            setToneRequest(text);
          } else {
            edit.sendMessage(text);
          }
          setValue('');
        }}
        targetChip={
          number > 0
            ? {
                label: t('edit.chat.target', { number }),
                removeLabel: t('edit.chat.targetRemove'),
                onRemove: edit.clearTarget,
              }
            : null
        }
      />
    </div>
  );
}

function ScriptComposer({
  reason,
  rest,
}: {
  reason?: string;
  rest: Omit<ComposerBoxProps, 'value' | 'onChange' | 'onSubmit' | 'disabled'>;
}) {
  const { t } = useLocale();
  const script = useScript();
  const number = script?.targetSceneId == null ? null : scriptSceneNumber(script.document, script.targetSceneId);
  return (
    <div className="flex w-full flex-col gap-2">
      {script?.tone == null ? null : (
        <div className="flex flex-col gap-2">
          <p>{t('script.tone.preview')}</p>
          <div className="flex flex-wrap gap-2">
            <Button size="36" variant="ghost" iconStart={<X aria-hidden size={16} />} onClick={dismissTone}>{t('edit.tone.keepAll')}</Button>
            <Button size="36" iconStart={<Check aria-hidden size={16} />} onClick={applyTone}>{t('edit.tone.applyAll')}</Button>
          </div>
        </div>
      )}
      <Tooltip content={reason ?? t('shell.stage.composerReason')} side="top">
        <div className="w-full">
          <ComposerBox
            {...rest}
            face="chat"
            value=""
            disabled
            placeholder={number === null ? rest.placeholder : t('edit.composer.placeholderScene', { number })}
            targetChip={number === null ? null : {
              label: t('edit.chat.target', { number }),
              removeLabel: t('edit.chat.targetRemove'),
              onRemove: clearScriptTarget,
            }}
          />
        </div>
      </Tooltip>
    </div>
  );
}

/**
 * The conversation rail. With a live concept it sends into that same concept
 * state; only when no video session is open does it stay a named placeholder.
 */
export function PlaceholderComposer({
  reason,
  ...rest
}: Omit<ComposerBoxProps, 'value' | 'onChange' | 'onSubmit' | 'disabled'> & {
  reason?: string;
}) {
  const { t } = useLocale();
  const view = useShellView();
  const snapshot = useConcept();
  const deployment = useDeployment();

  if (view === 'edit' || view === 'export') {
    return <EditComposer reason={reason} rest={rest} />;
  }
  if (view === 'script') {
    return <ScriptComposer reason={reason} rest={rest} />;
  }

  if (snapshot === null) {
    return (
      <Tooltip content={reason ?? t('concept.composer.noSession')} side="top">
        <div className="w-full">
          <ComposerBox {...rest} face="chat" value="" disabled />
        </div>
      </Tooltip>
    );
  }

  const settings = snapshot.document.settings;
  const jobLabel =
    snapshot.job === null
      ? null
      : t(
          {
            queued: 'concept.composer.jobQueued',
            running: 'concept.composer.jobRunning',
            succeeded: 'concept.composer.jobSucceeded',
            failed: 'concept.composer.jobFailed',
          }[snapshot.job.state],
        );

  return (
    <div className="flex w-full flex-col gap-2">
      {jobLabel === null ? null : (
        <p
          data-slot="composer-status"
          role="status"
          className="px-1 text-[15px] text-[var(--text-muted)]"
        >
          {jobLabel}
        </p>
      )}
      {snapshot.error === null ? null : (
        <p role="alert" className="px-1 text-[15px] text-[var(--text)]">
          {t(snapshot.error)}
        </p>
      )}
      {snapshot.notes.length === 0 && snapshot.unsupported.length === 0 && snapshot.pending === null ? null : (
        <details className="max-h-48 overflow-y-auto px-1 text-[15px]">
          <summary className="min-h-11 cursor-pointer">{t('concept.results')}</summary>
          {snapshot.notes.map((note, index) => <p key={`n${index}`}>{note}</p>)}
          {snapshot.unsupported.map((text, index) => <p key={`u${index}`}>{t('concept.unsupported')}: {text}</p>)}
          {snapshot.pending?.status === 'proposed' ? (
            <ChangeReview plan={snapshot.pending} settings={settings} busy={snapshot.busy} />
          ) : null}
        </details>
      )}
      <Composer
        {...rest}
        face="chat"
        value={snapshot.draft}
        onChange={setConceptDraft}
        onSubmit={(attachments) => sendConcept(snapshot.draft, attachments)}
        disabled={snapshot.busy}
        language={settings.language}
        duration={settings.target_duration_s}
        onLanguageChange={(value) => chooseConcept('/language', value)}
        onDurationChange={(value) => chooseConcept('/target_duration_s', value)}
        deployment={deployment}
      />
    </div>
  );
}
