import { ConceptScreen } from '@/features/concept/concept-screen';

import { Composer } from '../shell/composer';

export function ConceptRoute() {
  return <ConceptScreen ComposerComponent={Composer} />;
}
