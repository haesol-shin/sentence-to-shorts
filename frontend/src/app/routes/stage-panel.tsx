import { useLocale } from '@/shared/lib/i18n/locale';

import type { Stage } from '../shell/shell-config';

/** A stage screen with nothing in it yet: the title and one honest line. */
export function StagePanel({ stage }: { stage: Stage }) {
  const { t } = useLocale();
  return (
    <section
      data-slot="stage-panel"
      data-stage={stage}
      aria-label={t(`shell.stage.${stage}`)}
      className="flex min-h-full flex-col gap-3 p-6"
    >
      <h2 className="text-[22px] font-bold text-[var(--text-strong)]">{t(`shell.stage.${stage}`)}</h2>
      <p className="text-[15px] text-[var(--text-muted)]">{t('shell.placeholder.empty')}</p>
    </section>
  );
}
