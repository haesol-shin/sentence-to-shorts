import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { Gallery } from './gallery';

const root = document.getElementById('root');

if (root === null) {
  throw new Error('root element is missing');
}

createRoot(root).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
);
