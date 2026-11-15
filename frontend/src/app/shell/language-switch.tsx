import { cn } from '@/shared/lib/utils';
import { LANGUAGES } from '@/shared/lib/i18n/catalog';
import { useLocale } from '@/shared/lib/i18n/locale';

/**
 * The screen language. It sits in the rail so the phone top bar keeps only the
 * step menu and the next action (SPEC 10a.2).
 */
export function LanguageSwitch() {
  const { language, setLanguage, t } = useLocale();
  return (
    <div
      role="group"
      aria-label={t('shell.language.label')}
      className="mt-auto flex flex-col items-center gap-1"
    >
      {LANGUAGES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={option === language}
          aria-label={t(`shell.language.${option}`)}
          onClick={() => setLanguage(option)}
          className={cn(
            'flex items-center justify-center rounded-[var(--radius-capsule)] text-[13px] whitespace-nowrap transition-colors duration-[var(--motion-short)]',
            option === language
              ? 'bg-[var(--surface-muted)] font-bold text-[var(--text-strong)]'
              : 'text-[var(--text-muted)] hover:bg-[var(--surface-muted)]',
          )}
          style={{ width: 'var(--touch-target)', height: 'var(--touch-target)' }}
        >
          {t(`shell.language.short.${option}`)}
        </button>
      ))}
    </div>
  );
}
