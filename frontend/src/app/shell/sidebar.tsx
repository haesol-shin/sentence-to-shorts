import { Library, Plus, Settings, type LucideIcon } from 'lucide-react';

import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import { IconButton } from '@/shared/ui/icon-button';
import { Tooltip } from '@/shared/ui/tooltip';

import { LanguageSwitch } from './language-switch';
import { NAV_LABEL_MODE, type View } from './shell-config';

interface NavItem {
  id: string;
  labelKey: string;
  icon: LucideIcon;
  enabled: boolean;
  reasonKey?: string;
}

const ITEMS: readonly NavItem[] = [
  { id: 'newVideo', labelKey: 'shell.nav.newVideo', icon: Plus, enabled: true },
  {
    id: 'myVideos',
    labelKey: 'shell.nav.myVideos',
    icon: Library,
    enabled: false,
    reasonKey: 'shell.nav.myVideosReason',
  },
  {
    id: 'settings',
    labelKey: 'shell.nav.settings',
    icon: Settings,
    enabled: false,
    reasonKey: 'shell.nav.settingsReason',
  },
];

/**
 * The collapsed rail. A screen that is not built yet stays visible: it is
 * greyed, tagged and explains itself in the tooltip (SPEC 10a.1).
 */
export function Sidebar({ view, onNewVideo }: { view: View; onNewVideo: () => void }) {
  const { t } = useLocale();
  const inline = NAV_LABEL_MODE === 'inline';

  return (
    <aside
      data-slot="sidebar"
      aria-label={t('shell.nav.label')}
      className="flex w-[var(--layout-sidebar-w-sm)] shrink-0 flex-col items-center gap-2 py-3 md:w-[var(--layout-sidebar-w)]"
    >
      <span
        aria-hidden
        data-slot="logo"
        className="mb-1 size-8 rounded-[10px] bg-[var(--text-strong)]"
      />
      <nav className="flex flex-col items-center gap-1">
        {ITEMS.map((item) => {
          const name = t(item.labelKey);
          const reason = item.reasonKey === undefined ? null : t(item.reasonKey);
          const active = item.id === 'newVideo' && view === 'first';
          const label = item.enabled || reason === null ? name : `${name} · ${t('shell.nav.soon')}`;

          if (inline) {
            return (
              <button
                key={item.id}
                type="button"
                disabled={!item.enabled}
                aria-current={active ? 'page' : undefined}
                onClick={item.id === 'newVideo' ? onNewVideo : undefined}
                title={reason ?? undefined}
                className={cn(
                  'flex items-center gap-2 rounded-[var(--radius-capsule)] px-3 text-[15px] text-[var(--text)] disabled:text-[var(--text-disabled)]',
                  active && 'font-bold text-[var(--text-strong)]',
                )}
                style={{ minHeight: 'var(--touch-target)' }}
              >
                <item.icon aria-hidden size={20} />
                <span>{name}</span>
                {item.enabled ? null : <span className="text-[15px]">{t('shell.nav.soon')}</span>}
              </button>
            );
          }

          return (
            <Tooltip
              key={item.id}
              label={reason === null ? label : `${label}: ${reason}`}
              side="right"
            >
              <IconButton
                label={name}
                disabled={!item.enabled}
                aria-current={active ? 'page' : undefined}
                onClick={item.id === 'newVideo' ? onNewVideo : undefined}
                className={cn(active && 'bg-[var(--surface-muted)] text-[var(--text-strong)]')}
              >
                <item.icon aria-hidden size={20} />
              </IconButton>
            </Tooltip>
          );
        })}
      </nav>
      <LanguageSwitch />
    </aside>
  );
}
