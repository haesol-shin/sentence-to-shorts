import type { ReactNode } from 'react';

import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { useLocale } from '@/shared/lib/i18n/locale';
import { cn } from '@/shared/lib/utils';

import { useEdit } from './edit-context';
import { sceneNumber } from './model';

/**
 * The user's words: a grey bubble at the right. The canon draws it in the
 * raised grey a pressed grey part takes, so it stands off the white column.
 */
export function ChatUserLine({ children }: { children: ReactNode }) {
  return (
    <li
      data-slot="chat-user"
      className="max-w-[85%] self-end rounded-[var(--radius-row)] bg-[var(--state-hover-gray)] px-3.5 py-[9px] text-[15px] leading-[18px] text-[var(--text-strong)]"
    >
      {children}
    </li>
  );
}

/** The app's words: plain text at the left. A line that only reports a step is muted. */
export function ChatAppLine({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  return (
    <li
      data-slot="chat-assistant"
      className={cn(
        'flex flex-col items-start gap-2 text-[15px] leading-[18px]',
        muted ? 'text-[var(--text-muted)]' : 'text-[var(--text)]',
      )}
    >
      {children}
    </li>
  );
}

/** The conversation of every step: lines from the top of the column, 12 apart. */
export function ChatLog({ slot, label, children }: { slot: string; label: string; children: ReactNode }) {
  const { t } = useLocale();
  return (
    <div data-slot={slot} className="flex min-h-0 flex-1 flex-col">
      <ScrollPane label={label} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
        <ol className="flex flex-col gap-3 px-1">{children}</ol>
      </ScrollPane>
    </div>
  );
}

/**
 * The edit conversation sits above its composer, after the lines the shell
 * opens it with. Only the result stays in the history; the explanation is
 * available on the result row as a tooltip.
 */
export function EditChatHistory({ lead }: { lead?: ReactNode }) {
  const { t } = useLocale();
  const edit = useEdit();
  return (
    <ChatLog slot="edit-chat" label={t('edit.chat.label')}>
      {lead}
      {edit.messages.length === 0 && lead === undefined ? (
        <ChatAppLine muted>{t('edit.chat.empty')}</ChatAppLine>
      ) : null}
      {edit.messages.map((message) => {
        const label = message.kind === undefined ? message.text ?? '' : t(`edit.chat.${message.kind}`);
        const scenes = (message.sceneIds !== undefined && message.sceneIds.length > 0
          ? message.sceneIds
          : message.targetId !== null && message.targetId !== undefined
            ? [message.targetId]
            : []
        ).map((sceneId) => (
          <button
            key={sceneId}
            type="button"
            data-slot="chat-scene"
            onClick={() => {
              edit.selectScene(sceneId);
              window.requestAnimationFrame(() => {
                document
                  .querySelector<HTMLElement>(`[data-slot="scene-card"][data-scene-id="${sceneId}"]`)
                  ?.scrollIntoView({ block: 'nearest' });
              });
            }}
            className="w-fit rounded-[var(--radius-capsule)] text-[13px] text-[var(--text-muted)] underline-offset-2 hover:underline"
          >
            {t('edit.chat.target', { number: sceneNumber(edit.video, sceneId) })}
          </button>
        ));
        const body = (
          <span className="flex flex-col items-start gap-1">
            {scenes}
            <span>{label}</span>
          </span>
        );
        const content =
          message.detail === undefined || message.detail === '' ? (
            body
          ) : (
            <Tooltip content={message.detail} side="top">
              {body}
            </Tooltip>
          );
        return message.role === 'user' ? (
          <ChatUserLine key={message.id}>{content}</ChatUserLine>
        ) : (
          <ChatAppLine key={message.id}>{content}</ChatAppLine>
        );
      })}
    </ChatLog>
  );
}
