import { ConceptScreen } from '@/features/concept/concept-screen';

import { Composer } from '../shell/composer';

/** The concept step; confirming it opens the script step through `onNext`. */
export function ConceptRoute({ onNext }: { onNext?: () => void }) {
  return <ConceptScreen ComposerComponent={Composer} onConfirmed={onNext} />;
}
