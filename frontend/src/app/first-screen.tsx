import { useState } from 'react';

import { listFormatCards, listRecentProjects, type Language } from '@/shared/api/client';
import { beginConcept } from '@/features/concept/store';
import type { Attachment } from '@/features/concept/types';
import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import { useLoad } from '@/shared/lib/use-load';
import { useDeployment, Composer } from './shell/composer';
import type { CardPick } from './shell/shell-config';

/**
 * The first screen: the heading, the input, the three cards and the recent
 * projects share one column, centred in the area beside the sidebar marked by
 * the same left and right edge (SPEC 10a.2). No step indicator lives here.
 */
export function FirstScreen({
  draft,
  card,
  submitting,
  ready,
  onDraftChange,
  onPickCard,
  onClearCard,
  onSubmit,
}: {
  draft: string;
  card: CardPick | null;
  submitting: boolean;
  /** The session is up, so the catalog and the project list may be read. */
  ready: boolean;
  onDraftChange: (value: string) => void;
  onPickCard: (card: CardPick) => void;
  onClearCard: () => void;
  /** The start boundary receives the whole material, not only the sentence. */
  onSubmit: (text: string, attachments: Attachment[]) => void | Promise<void>;
}) {
  const { t, language } = useLocale();
  const cards = useLoad(listFormatCards, ready);
  const projects = useLoad(listRecentProjects, ready);
  const deployment = useDeployment(ready);
  const [chosenLanguage, setChosenLanguage] = useState<Language>(language);
  const [duration, setDuration] = useState(60);

  const start = async (attachments: Attachment[]) => {
    await beginConcept({
      topic: draft,
      cardId: card?.id ?? null,
      language: chosenLanguage,
      duration,
      attachments,
    });
    await onSubmit(draft, attachments);
  };

  return (
    // `my-auto` centres the column while it fits and lets it start at the top
    // once a phone keyboard or a short window takes the room away, so nothing
    // is ever clipped above the scroll area.
    <section data-slot="first-screen" className="my-auto flex w-full justify-center px-4 py-8">
      <div
        className="flex w-full flex-col gap-8"
        style={{ maxWidth: 'var(--layout-first-w)' }}
      >
        <h1 className="text-[22px] font-bold text-[var(--text-strong)]">{t('shell.first.heading')}</h1>
        <Composer
          label={t('shell.first.composerLabel')}
          placeholder={t('shell.first.composerLabel')}
          sendLabel={t('shell.first.send')}
          value={draft}
          onChange={onDraftChange}
          onSubmit={start}
          card={card}
          onClearCard={onClearCard}
          language={chosenLanguage}
          duration={duration}
          onLanguageChange={setChosenLanguage}
          onDurationChange={setDuration}
          deployment={deployment}
          disabled={submitting}
        />
        <section data-slot="first-cards" className="flex flex-col gap-3">
          <h2 className="text-[15px] font-bold text-[var(--text-strong)]">
            {t('shell.first.cardsHeading')}
          </h2>
          {cards.failureKey === null || cards.pending ? null : (
            <p className="text-[15px] text-[var(--text-muted)]">{t('shell.first.cardsEmpty')}</p>
          )}
          <div className="grid gap-3 sm:grid-cols-3">
            {(cards.data ?? []).map((item) => {
              const topicKey = `shell.cardTopic.${item.id}`;
              const topic = t(topicKey);
              const selected = card?.id === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onPickCard({ id: item.id, label: item.label[language] })}
                  className={cn(
                    'focus-ring flex min-h-[var(--size-control)] flex-col items-start justify-start gap-1 rounded-[var(--radius-card)] bg-[var(--surface-muted)] p-5 text-left transition-colors duration-[var(--motion-short)] hover:bg-[var(--surface-sunken)]',
                    selected && 'outline-2 outline-[var(--text-strong)]',
                  )}
                >
                  <span className="text-[15px] font-bold text-[var(--text-strong)]">
                    {item.label[language]}
                  </span>
                  {topic === topicKey ? null : (
                    <span className="text-[15px] text-[var(--text-muted)]">
                      {t('shell.first.cardExample', { topic })}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </section>
        <section data-slot="first-recent" className="flex flex-col gap-2">
          <h2 className="text-[15px] font-bold text-[var(--text-strong)]">
            {t('shell.first.recentHeading')}
          </h2>
          {projects.pending ? null : projects.failureKey !== null ? (
            <p className="text-[15px] text-[var(--text-muted)]">{t('shell.first.recentUnavailable')}</p>
          ) : (projects.data ?? []).length === 0 ? (
            <p className="text-[15px] text-[var(--text-muted)]">{t('shell.first.recentEmpty')}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {(projects.data ?? []).map((project) => (
                <li
                  key={project.id}
                  className="flex items-center justify-between gap-3 rounded-[var(--radius-panel)] bg-[var(--surface-muted)] px-3 py-2"
                >
                  <span className="truncate text-[15px] text-[var(--text-strong)]">
                    {project.title}
                  </span>
                  <span className="shrink-0 text-[15px] text-[var(--text-muted)]">
                    {t('shell.first.recentCount', { count: project.video_count })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </section>
  );
}
