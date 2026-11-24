import type { ReactNode } from 'react';
import { Folder, Plus, Settings, type LucideIcon } from 'lucide-react';

import { cn } from '@/shared/lib/utils';
import { useLocale } from '@/shared/lib/i18n/locale';
import { SidebarItem } from '@/components/SidebarItem/SidebarItem';
import { Tooltip } from '@/components/Tooltip/Tooltip';

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
    icon: Folder,
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
export function Sidebar({
  view,
  onNewVideo,
  brand,
}: {
  view: View;
  onNewVideo: () => void;
  brand: ReactNode;
}) {
  const { t } = useLocale();
  const inline = NAV_LABEL_MODE === 'inline';

  const renderItem = (item: NavItem) => {
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

    const control = (
      <SidebarItem
        label={name}
        disabled={!item.enabled}
        selected={active}
        // New video is the rail's one filled action on every screen.
        className={item.id === 'newVideo' ? 'sidebar-item--primary' : undefined}
        onClick={item.id === 'newVideo' ? onNewVideo : undefined}
      >
        <item.icon aria-hidden size={20} />
      </SidebarItem>
    );

    return (
      <Tooltip
        key={item.id}
        content={reason === null ? label : `${label}: ${reason}`}
        side="right"
      >
        {item.enabled ? (
          control
        ) : (
          // A disabled button takes no pointer or focus, so the seat carries the reason.
          <span tabIndex={0} className="inline-flex">
            {control}
          </span>
        )}
      </Tooltip>
    );
  };

  return (
    <aside
      data-slot="sidebar"
      aria-label={t('shell.nav.label')}
      className="flex w-[var(--layout-sidebar-w-sm)] shrink-0 flex-col items-center bg-[var(--surface)] md:w-[var(--layout-sidebar-w)]"
    >
      <span
        aria-hidden
        data-slot="logo"
        className="mt-3 size-8 shrink-0 rounded-[10px] bg-[var(--text-strong)]"
      />
      {/* The logo is the app's mark; the name stays for a screen reader. */}
      <span data-slot="brand" className="sr-only">
        {brand}
      </span>
      <nav className="mt-7 flex flex-col items-center gap-3">
        {ITEMS.filter((item) => item.id !== 'settings').map(renderItem)}
      </nav>
      <LanguageSwitch />
      {/* Settings keeps the bottom corner of the rail, under the screen language. */}
      <div className="mt-3 mb-5 flex flex-col items-center">
        {ITEMS.filter((item) => item.id === 'settings').map(renderItem)}
      </div>
    </aside>
  );
}
