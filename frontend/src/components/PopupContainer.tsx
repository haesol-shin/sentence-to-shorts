import { createContext, useContext } from 'react';

/**
 * The element that nested menus, pickers, and tooltips should portal into.
 * It is set by a window so these popups paint above the window instead of
 * behind it. Null means the body portal, which is right outside a window.
 */
export const PopupContainerContext = createContext<HTMLElement | null>(null);

export function usePopupContainer(): HTMLElement | null {
  return useContext(PopupContainerContext);
}
