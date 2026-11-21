import { ScrollPane } from '@/components/ScrollPane/ScrollPane';
import { Tooltip } from '@/components/Tooltip/Tooltip';
import { useLocale } from '@/shared/lib/i18n/locale';

import { useEdit } from './edit-context';
import { sceneNumber } from './model';

/**
 * The edit conversation sits above its composer. Only the result stays in the
 * history; the explanation is available on the result row as a tooltip.
 */
export function EditChatHistory() {
  const { t } = useLocale();
  const edit = useEdit();
  return (
    <div data-slot="edit-chat" className="flex min-h-0 flex-1 flex-col">
      <ScrollPane label={t('edit.chat.label')} jumpLabel={t('shell.scroll.jump')} className="min-h-0 flex-1">
        {edit.messages.length === 0 ? (
          <p className="px-1 py-2 text-[15px] text-[var(--text-muted)]">{t('edit.chat.empty')}</p>
        ) : (
          <ol className="flex flex-col gap-2 px-1 py-2">
            {edit.messages.map((message) => {
              const label = message.kind === undefined ? message.text ?? '' : t(`edit.chat.${message.kind}`);
              const content = (
                <div
                  data-slot="chat-message"
                  data-role={message.role}
                  className="flex flex-col gap-1 rounded-[var(--radius-panel)] bg-[var(--surface-muted)] px-3 py-2 text-[15px] text-[var(--text)]"
                >
                  {(message.sceneIds !== undefined && message.sceneIds.length > 0
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
                  ))}
                  <span>{label}</span>
                </div>
              );
              return (
                <li key={message.id} className={message.role === 'user' ? 'self-end' : 'self-start'}>
                  {message.detail === undefined || message.detail === '' ? (
                    content
                  ) : (
                    <Tooltip content={message.detail} side="top">
                      {content}
                    </Tooltip>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </ScrollPane>
    </div>
  );
}
