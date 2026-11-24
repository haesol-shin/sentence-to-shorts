import { useState } from 'react';
import { Image } from 'lucide-react';

import { listFormatCards, type Language } from '@/shared/api/client';
import { STORY_CARD_ORDER } from '@/features/concept/cards';
import type { Attachment } from '@/features/concept/types';
import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import type { LlmKey } from '@/features/runtime/use-runtime-head';
import { useLoad } from '@/shared/lib/use-load';
import { ApiKeyBlock } from './api-key-block';
import { useDeployment, Composer } from './shell/composer';
import type { CardPick } from './shell/shell-config';

/** The story cards read in the shared canon order; a card the order does not know follows them. */
function inCardOrder<T extends { id: string }>(items: readonly T[]): T[] {
  const rank = (id: string) => {
    const index = STORY_CARD_ORDER.indexOf(id);
    return index === -1 ? STORY_CARD_ORDER.length : index;
  };
  return [...items].sort((a, b) => rank(a.id) - rank(b.id));
}

/**
 * The first screen: the heading, the input and the three story cards share one
 * 672 column, centred in the area beside the sidebar marked by the same left and
 * right edge (SPEC 10a.2). No step indicator and no recent list live here.
 */
export function FirstScreen({
  draft,
  card,
  submitting,
  ready,
  llmKey,
  authFailureKey,
  onDraftChange,
  onKeySaved,
  onPickCard,
  onClearCard,
  onSubmit,
}: {
  draft: string;
  card: CardPick | null;
  submitting: boolean;
  /** The session is up, so the catalog may be read. */
  ready: boolean;
  /** What the runtime says about the user's own LLM key. */
  llmKey: LlmKey;
  /** The `errors` key of an `llm_auth` failure that asks for the key again; `null` when none stands. */
  authFailureKey: string | null;
  onDraftChange: (value: string) => void;
  /** The key is stored and the server reports it usable. */
  onKeySaved: () => void;
  onPickCard: (card: CardPick) => void;
  onClearCard: () => void;
  /** The start boundary receives the whole material, not only the sentence. */
  onSubmit: (
    text: string,
    attachments: Attachment[],
    options: { language: Language; duration: number },
  ) => void | Promise<void>;
}) {
  const { t, language } = useLocale();
  const cards = useLoad(listFormatCards, ready);
  const deployment = useDeployment(ready);
  const [chosenLanguage, setChosenLanguage] = useState<Language>(language);
  const [duration, setDuration] = useState(60);

  const start = async (attachments: Attachment[]) => {
    await onSubmit(draft, attachments, { language: chosenLanguage, duration });
  };

  // dev and fixture profiles never ask: they use their own adapter.
  const askKey = llmKey.release && (llmKey.needed || authFailureKey !== null);
  const saveKey = async (apiKey: string) => {
    const state = await llmKey.save(apiKey);
    if (state === 'ok' || state === 'unknown') onKeySaved();
  };

  return (
    // `my-auto` centres the column while it fits and lets it start at the top
    // once a phone keyboard or a short window takes the room away, so nothing
    // is ever clipped above the scroll area.
    <section data-slot="first-screen" className="my-auto flex w-full justify-center px-4 py-8">
      <div
        data-slot="first-group"
        className="flex w-full flex-col gap-12"
        style={{ maxWidth: 'var(--layout-first-w)' }}
      >
        <h1 className="self-center text-[length:var(--font-size-display)] leading-[var(--line-height-display)] font-bold text-[var(--text-strong)]">
          {t('shell.first.heading')}
        </h1>
        {askKey ? <ApiKeyBlock noticeKey={authFailureKey} onSave={saveKey} /> : null}
        <Composer
          face="first"
          label={t('shell.first.composerLabel')}
          placeholder={t('shell.first.composerPlaceholder')}
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
        <div className="flex flex-col gap-2.5">
          <h2 className="flex items-baseline justify-between gap-3 text-[17px] leading-5 font-bold text-[var(--text-strong)]">
            <span>{t('shell.first.cardsTitle')}</span>
            <small className="text-[15px] leading-5 font-normal text-[var(--text-muted)]">{t('shell.first.cardsHint')}</small>
          </h2>
          <section data-slot="first-cards" className="flex flex-wrap gap-3">
            {cards.failureKey === null || cards.pending ? null : (
              <p className="text-[15px] text-[var(--text-muted)]">{t('shell.first.cardsEmpty')}</p>
            )}
            {inCardOrder(cards.data ?? []).map((item) => {
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
                    'focus-ring box-border flex h-[266px] w-[216px] flex-col justify-center rounded-[var(--radius-content)] p-2 text-left transition-colors duration-[var(--motion-short)]',
                    selected
                      ? 'bg-[var(--surface-sunken)]'
                      : 'bg-transparent hover:bg-[var(--state-hover-gray)]',
                  )}
                >
                  <span
                    className={cn(
                      'flex h-[150px] w-[200px] shrink-0 items-center justify-center rounded-[var(--radius-media)] text-[var(--text-muted)]',
                      selected ? 'bg-[var(--surface-muted)]' : 'bg-[var(--surface-sunken)]',
                    )}
                    aria-hidden="true"
                  >
                    <Image size={32} />
                  </span>
                  <span
                    className={cn(
                      'mt-3 h-5 w-[200px] shrink-0 truncate text-[17px] leading-5 font-normal text-[var(--text-muted)]',
                      selected && 'font-bold text-[var(--text-strong)]',
                    )}
                  >
                    {item.label[language]}
                  </span>
                  {topic === topicKey ? null : (
                    <span className="mt-1 h-[18px] w-[200px] shrink-0 truncate text-[15px] leading-[18px] text-[var(--text-muted)]">
                      {t('shell.first.cardExample', { topic })}
                    </span>
                  )}
                </button>
              );
            })}
          </section>
        </div>
      </div>
    </section>
  );
}
