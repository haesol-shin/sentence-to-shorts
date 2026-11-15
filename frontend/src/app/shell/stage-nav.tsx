import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';

import { STAGES, type Stage } from './shell-config';

const STEP = 'text-[15px] whitespace-nowrap';

/**
 * The four step names with a dot under the current one. Every other step can be
 * opened: a later step stays lighter, and tapping ahead is allowed because the
 * steps need not be visited in order (SPEC 10a.2).
 */
export function StageIndicator({
  current,
  onSelect,
}: {
  current: Stage;
  onSelect: (stage: Stage) => void;
}) {
  const { t } = useLocale();
  const currentIndex = STAGES.indexOf(current);

  return (
    <nav
      data-slot="stage-indicator"
      aria-label={t('shell.stage.list')}
      className="flex items-start gap-5"
    >
      {STAGES.map((stage, index) => {
        const isCurrent = stage === current;
        const isPast = index < currentIndex;
        return (
          <span key={stage} className="flex flex-col items-center gap-1">
            {isCurrent ? (
              <span
                aria-current="step"
                className={cn(STEP, 'font-bold text-[var(--text-strong)]')}
              >
                {t(`shell.stage.${stage}`)}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onSelect(stage)}
                className={cn(
                  STEP,
                  'hover:underline',
                  isPast ? 'text-[var(--text-strong)]' : 'text-[var(--text-disabled)]',
                )}
              >
                {t(`shell.stage.${stage}`)}
              </button>
            )}
            <span
              aria-hidden
              className={cn(
                'size-[5px] rounded-[var(--radius-capsule)]',
                isCurrent ? 'bg-[var(--text-strong)]' : 'bg-transparent',
              )}
            />
          </span>
        );
      })}
    </nav>
  );
}

/** Opens any step. The phone top bar uses it because the indicator is hidden. */
export function StageMenu({
  current,
  onSelect,
}: {
  current: Stage;
  onSelect: (stage: Stage) => void;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const frame = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (frame.current !== null && !frame.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div ref={frame} data-slot="stage-menu" className="relative">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('shell.stage.menu')}
        onClick={() => setOpen((previous) => !previous)}
        className="inline-flex shrink-0 items-center gap-1 rounded-[var(--radius-capsule)] px-3 text-[15px] font-bold whitespace-nowrap text-[var(--text-strong)] hover:bg-[var(--surface-muted)]"
        style={{ minHeight: 'var(--touch-target)' }}
      >
        {t(`shell.stage.${current}`)}
        <ChevronDown
          aria-hidden
          size={18}
          className="transition-transform duration-[var(--motion-short)]"
          style={{ transform: open ? 'rotate(180deg)' : 'none' }}
        />
      </button>
      {open ? (
        <ul
          role="menu"
          aria-label={t('shell.stage.list')}
          className="absolute top-[calc(100%+4px)] left-0 z-20 min-w-40 rounded-[var(--radius-panel)] bg-[var(--surface)] p-1 shadow-[0_12px_32px_rgba(0,0,0,0.16)]"
        >
          {STAGES.map((stage) => (
            <li key={stage}>
              <button
                type="button"
                role="menuitem"
                aria-current={stage === current ? 'true' : undefined}
                onClick={() => {
                  setOpen(false);
                  onSelect(stage);
                }}
                className={cn(
                  'flex w-full items-center rounded-[var(--radius-panel)] px-3 text-left text-[15px]',
                  stage === current
                    ? 'bg-[var(--surface-muted)] font-bold text-[var(--text-strong)]'
                    : 'text-[var(--text)] hover:bg-[var(--surface-muted)]',
                )}
                style={{ minHeight: 'var(--touch-target)' }}
              >
                {t(`shell.stage.${stage}`)}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
