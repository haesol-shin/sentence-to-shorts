import { useId, useState, type ReactElement, type ReactNode } from 'react';
import { Check, Play, Square } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { CloseButton } from '@/components/CloseButton/CloseButton';
import { Dialog, DialogClose } from '@/components/Dialog/Dialog';
import { IconButton } from '@/components/IconButton/IconButton';
import { Notice } from '@/components/Notice/Notice';
import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { useLocale } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

import type { AudioPreview } from './use-audio-preview';
import './choice-dialog.css';

export interface ChoiceItem {
  id: string;
  label: string;
  /** The preview key and the loader of its audio URL. */
  previewKey: string;
  loadPreview: () => Promise<string | null>;
}

/**
 * A window to listen to a few items and pick one. Listening and picking are two
 * controls on every row, and nothing changes until 「적용」; Escape and 「취소」
 * leave the value as it was. With a container it lies over that panel.
 */
export function ChoiceDialog({
  open,
  onOpenChange,
  title,
  label,
  description,
  listLabel,
  emptyText,
  items,
  current,
  preview,
  onApply,
  disabled = false,
  container,
  trigger,
  details,
  showList = true,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The visible title. */
  title: string;
  /** The window name, which may say more than the short visible title. */
  label: string;
  description: string;
  listLabel: string;
  emptyText: string;
  items: readonly ChoiceItem[];
  current: string | null;
  preview: AudioPreview;
  onApply: (id: string) => void;
  disabled?: boolean;
  container?: HTMLElement;
  trigger: ReactElement;
  details?: ReactNode;
  showList?: boolean;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState({ current, picked: null as string | null });
  if (draft.current !== current) setDraft({ current, picked: null });
  /* The short visible title names the window only when it says everything. */
  const nameId = useId();
  const selected = items.some((item) => item.id === draft.picked) ? draft.picked : current;
  const problem = items.some((item) => item.previewKey === preview.problem?.key)
    ? preview.problem
    : null;
  const changed = selected !== null && selected !== current;

  const close = (next: boolean) => {
    if (!next) {
      preview.stop();
      setDraft({ current, picked: null });
    }
    onOpenChange(next);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      trigger={trigger}
      title={title}
      description={description}
      {...(label === title ? { label } : { labelledBy: nameId })}
      className="choice-sheet"
      container={container}
      actions={
        <>
          <DialogClose render={<Button variant="secondary">{t('audio.picker.cancel')}</Button>} />
          <Button
            disabled={!changed || disabled}
            onClick={() => {
              if (selected === null) return;
              preview.stop();
              setDraft({ current, picked: null });
              onApply(selected);
              onOpenChange(false);
            }}
          >
            {t('audio.picker.apply')}
          </Button>
        </>
      }
    >
      {label === title ? null : (
        <span id={nameId} className="sr-only">
          {label}
        </span>
      )}
      <DialogClose
        render={<CloseButton label={t('audio.picker.close')} data-slot="choice-close" className="whole-details-sheet__close" />}
      />
      {problem === null ? null : (
        <Notice tone="warning" className="mb-2">
          {t(problem.kind === 'unavailable' ? 'audio.preview.unavailable' : 'audio.preview.failed')}
        </Notice>
      )}
      {showList && (
        <ScrollPane label={listLabel} jumpLabel={t('shell.scroll.jump')} className="max-h-72 min-h-0">
          <ul className="flex flex-col" data-slot="choice-list">
            {items.length === 0 ? (
              <li className="px-3 py-2 text-[15px] text-[var(--text-muted)]">{emptyText}</li>
            ) : (
              items.map((item) => {
                const active = item.id === selected;
                const sounding = preview.playing === item.previewKey;
                return (
                  <li key={item.id} className="choice-row" data-slot="choice-row">
                    <IconButton
                      className={cn('choice-listen', active && 'choice-listen--current')}
                      label={t(sounding ? 'audio.preview.stopNamed' : 'audio.preview.listenNamed', {
                        name: item.label,
                      })}
                      data-slot="choice-listen"
                      onClick={() => preview.toggle(item.previewKey, item.loadPreview)}
                    >
                      {sounding ? <Square aria-hidden fill="currentColor" /> : <Play aria-hidden fill="currentColor" className="play-glyph" />}
                    </IconButton>
                    <button
                      type="button"
                      aria-pressed={active}
                      data-slot="choice-select"
                      onClick={() => setDraft({ current, picked: item.id })}
                      className="choice-select focus-ring"
                    >
                      <span className="truncate">{item.label}</span>
                      {active ? <Check aria-hidden size={20} className="shrink-0" /> : null}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </ScrollPane>
      )}
      {details === undefined ? null : <div className="mt-4">{details}</div>}
    </Dialog>
  );
}
