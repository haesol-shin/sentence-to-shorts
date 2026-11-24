import { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';

import { STAGES, type Stage } from './shell-config';

// Each step is a 44 high capsule with 14 on each side; the current one carries a dot at its foot.
const STEP = 'relative inline-flex h-[var(--size-control)] items-center rounded-[var(--radius-capsule)] px-3.5 text-[15px] whitespace-nowrap';

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
      className="flex items-center gap-4"
    >
      {STAGES.map((stage, index) => {
        const isCurrent = stage === current;
        const isPast = index < currentIndex;
        return (
          <span key={stage} className="flex">
            {isCurrent ? (
              <span
                aria-current="step"
                className={cn(STEP, 'font-bold text-[var(--text-strong)]')}
              >
                {t(`shell.stage.${stage}`)}
                <span
                  aria-hidden
                  className="absolute bottom-[3px] left-1/2 size-[5px] -translate-x-1/2 rounded-[var(--radius-capsule)] bg-[var(--text-strong)]"
                />
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onSelect(stage)}
                className={cn(
                  STEP,
                  'focus-ring hover:underline',
                  isPast ? 'text-[var(--text-strong)]' : 'text-[var(--text-disabled)]',
                )}
              >
                {t(`shell.stage.${stage}`)}
              </button>
            )}
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
        // The phone keeps the 48 touch target; the desktop bar matches its 44 controls.
        className="inline-flex min-h-[var(--touch-target)] shrink-0 items-center gap-1 rounded-[var(--radius-capsule)] px-3 text-[15px] font-bold whitespace-nowrap text-[var(--text-strong)] hover:bg-[var(--surface-muted)] md:min-h-[var(--size-control)]"
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
