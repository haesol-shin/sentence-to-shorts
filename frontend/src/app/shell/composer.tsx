import type { KeyboardEvent, ReactNode } from 'react';
import { ArrowUp, X } from 'lucide-react';

import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import { Chip } from '@/shared/ui/chip';
import { IconButton } from '@/shared/ui/icon-button';
import { Tooltip } from '@/shared/ui/tooltip';

interface ComposerBoxProps {
  label: string;
  placeholder: string;
  sendLabel: string;
  value: string;
  disabled?: boolean;
  onChange?: (value: string) => void;
  onSubmit?: () => void;
  card?: { label: string } | null;
  onClearCard?: () => void;
  options?: ReactNode;
}

function ComposerBox({
  label,
  placeholder,
  sendLabel,
  value,
  disabled = false,
  onChange,
  onSubmit,
  card = null,
  onClearCard,
  options,
}: ComposerBoxProps) {
  const { t } = useLocale();
  const canSend = !disabled && value.trim() !== '';

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter that settles a Korean or Japanese composition is not a send.
    if (event.nativeEvent.isComposing || event.keyCode === 229) {
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (canSend) {
        onSubmit?.();
      }
    }
  };

  return (
    <div
      data-slot="composer"
      data-state={disabled ? 'placeholder' : 'active'}
      className="w-full rounded-[var(--radius-input)] bg-[var(--surface-muted)] p-3"
    >
      {card === null ? null : (
        <div className="mb-2 flex">
          <Chip>
            {t('shell.first.cardChip', { label: card.label })}
            {onClearCard === undefined ? null : (
              <button
                type="button"
                aria-label={t('shell.first.cardChipRemove')}
                onClick={onClearCard}
                className="-mr-1 inline-flex size-6 items-center justify-center rounded-[var(--radius-capsule)] hover:bg-[var(--surface-sunken)]"
              >
                <X aria-hidden size={14} />
              </button>
            )}
          </Chip>
        </div>
      )}
      <textarea
        aria-label={label}
        placeholder={placeholder}
        value={value}
        disabled={disabled}
        rows={2}
        onChange={(event) => onChange?.(event.target.value)}
        onKeyDown={onKeyDown}
        onFocus={(event) => {
          // A browser that only shrinks the visual viewport still scrolls the
          // focused input into sight; the dock handles the rest of the inset.
          event.currentTarget.scrollIntoView?.({ block: 'nearest' });
        }}
        className="w-full resize-none bg-transparent text-[17px] text-[var(--text-strong)] outline-none placeholder:text-[var(--text-disabled)] disabled:cursor-not-allowed"
      />
      <div className="mt-2 flex items-center gap-2">
        {options}
        <div className="flex-1" />
        <IconButton
          label={sendLabel}
          disabled={!canSend}
          onClick={() => onSubmit?.()}
          className="bg-[var(--text-strong)] text-[var(--surface)] hover:bg-[var(--text)] disabled:bg-[var(--surface-sunken)] disabled:text-[var(--text-disabled)] disabled:hover:bg-[var(--surface-sunken)]"
        >
          <ArrowUp aria-hidden size={20} />
        </IconButton>
      </div>
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
  onSubmit: () => void;
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
 * A box the shell shows but cannot use yet. The reason sits in a tooltip, so
 * the grey box never claims to work (SPEC 10a.1).
 */
export function PlaceholderComposer({
  reason,
  ...rest
}: Omit<ComposerBoxProps, 'value' | 'onChange' | 'onSubmit' | 'disabled'> & { reason: string }) {
  return (
    <Tooltip label={reason} side="top" className={cn('w-full')}>
      <ComposerBox {...rest} value="" disabled />
    </Tooltip>
  );
}
