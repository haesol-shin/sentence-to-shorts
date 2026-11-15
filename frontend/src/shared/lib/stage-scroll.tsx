import { createContext, useContext, type ReactNode } from 'react';

const StageScrollContext = createContext(false);

/**
 * Tells the stage body whether its own scroll area has been scrolled away from
 * the top, so a phone screen can fold its preview into a thumbnail.
 */
export function StageScrollProvider({
  scrolled,
  children,
}: {
  scrolled: boolean;
  children: ReactNode;
}) {
  return <StageScrollContext.Provider value={scrolled}>{children}</StageScrollContext.Provider>;
}

export function useStageScrolled(): boolean {
  return useContext(StageScrollContext);
}
