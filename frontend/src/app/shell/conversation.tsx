import { Check, X } from 'lucide-react';

import { Button } from '@/components/Button/Button';
import { conceptGreeting } from '@/features/concept/greeting';
import { useConcept } from '@/features/concept/store';
import { ChatAppLine, ChatLog, ChatUserLine, EditChatHistory } from '@/features/edit/chat-history';
import { useEditOptional } from '@/features/edit/edit-context';
import { applyTone, dismissTone, useScript } from '@/features/script/store';
import { useLocale } from '@/shared/lib/i18n/locale';

import type { Stage } from './shell-config';

/**
 * The conversation column's log. Every step opens with the sentence the video
 * started from and the app's line for that step, once the step has something
 * to show; edit and export go on with the edit conversation, and the script's
 * tone change is decided here, under the line that offers it.
 */
export function ConversationLog({
  stage,
  sentence,
  draftWaiting,
}: {
  stage: Stage;
  sentence: string | null;
  draftWaiting: boolean;
}) {
  const { t } = useLocale();
  const edit = useEditOptional();
  const script = useScript();
  const concept = useConcept();
  const said = sentence === null || sentence.trim() === '' ? null : <ChatUserLine>{sentence}</ChatUserLine>;

  if (stage === 'edit' || stage === 'export') {
    const count = edit?.video?.scene_order.length ?? 0;
    return (
      <EditChatHistory
        lead={said === null && count === 0 ? undefined : (
          <>
            {said}
            {count === 0 ? null : <ChatAppLine muted>{t('shell.conversation.edit', { count })}</ChatAppLine>}
          </>
        )}
      />
    );
  }

  const writingConcept = stage === 'concept' && (draftWaiting || concept?.readState === 'waiting');
  const ready =
    stage === 'concept'
      ? !writingConcept && concept?.readState === 'ready'
      : script !== null && script.document.scene_order.length > 0;
  return (
    <ChatLog slot="chat-log" label={t('edit.chat.label')}>
      {said}
      {ready ? (
        <ChatAppLine muted>
          {stage === 'concept'
            ? concept === null ? null : conceptGreeting(concept.opening, t)
            : t(`shell.conversation.${stage}`)}
        </ChatAppLine>
      ) : null}
      {writingConcept ? (
        <ChatAppLine muted>
          <span role="status" className="flex items-start gap-2">
            <span className="spinner shrink-0" aria-hidden="true" />
            {t('shell.conversation.conceptWaiting')}
          </span>
        </ChatAppLine>
      ) : null}
      {stage === 'script' && script?.tone != null ? (
        <ChatAppLine>
          {/* A line that asks for a choice reads on the 22 line, as the canon's question lines do. */}
          <span className="leading-[22px]">{t('script.tone.preview')}</span>
          <span className="flex flex-wrap gap-2">
            <Button size="36" variant="ghost" iconStart={<X aria-hidden size={16} />} onClick={dismissTone}>
              {t('edit.tone.keepAll')}
            </Button>
            <Button size="36" iconStart={<Check aria-hidden size={16} />} onClick={applyTone}>
              {t('edit.tone.applyAll')}
            </Button>
          </span>
        </ChatAppLine>
      ) : null}
    </ChatLog>
  );
}
