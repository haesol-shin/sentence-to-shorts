import { fireEvent, render, screen } from '@testing-library/react';
import { StrictMode } from 'react';

import { App } from '@/app/App';

import { shellRoutes, stubApi, type ApiStub, type RouteHandler } from './api';

export const FIRST_HEADING = '한 문장으로 영상을 만들어요';
export const COMPOSER_LABEL = '만들고 싶은 영상을 한 문장으로 적어 주세요';

/** Renders the app over the stubbed answers and waits for the first screen. */
export async function renderApp(
  routes: Record<string, RouteHandler> = shellRoutes(),
  { strict = false }: { strict?: boolean } = {},
): Promise<ApiStub> {
  const api = stubApi(routes);
  render(
    strict ? (
      <StrictMode>
        <App />
      </StrictMode>
    ) : (
      <App />
    ),
  );
  await screen.findByRole('heading', { name: FIRST_HEADING });
  return api;
}

/** Types one sentence into the first screen and presses send. */
export function sendSentence(message: string): void {
  fireEvent.change(screen.getByRole('textbox', { name: COMPOSER_LABEL }), {
    target: { value: message },
  });
  fireEvent.click(screen.getByRole('button', { name: '보내기' }));
}
