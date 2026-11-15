import { API_BASE, setTransport, type ApiRequest, type ApiResponse } from '../client';

interface Fixture {
  operationId: string;
  method: string;
  path_template: string;
  response: {
    status: number;
    media_type: string | null;
    body: unknown;
  };
}

// The recorded API answers live in the repository fixtures, outside the
// frontend root, so a mock run speaks the same bodies as the contract tests.
const files = import.meta.glob('../../../../../fixtures/api/*.json', { eager: true }) as Record<
  string,
  { default: Fixture }
>;

const fixtures = Object.values(files).map((module) => module.default);

function templatePattern(template: string): RegExp {
  const source = template
    .split(/(\{[^}]+\})/u)
    .map((part) =>
      part.startsWith('{') ? '[^/]+' : part.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'),
    )
    .join('');
  return new RegExp(`^${source}$`, 'u');
}

const routes = fixtures.map((fixture) => ({
  fixture,
  pattern: templatePattern(fixture.path_template),
}));

/**
 * The recorded answer for a request, or a 404 when no fixture covers it. The
 * transport sees the path without the base, while fixtures record the full one.
 */
export function mockResponse(request: ApiRequest): ApiResponse {
  const path = `${API_BASE}${request.path}`;
  const match = routes.find(
    ({ fixture, pattern }) => fixture.method === request.method && pattern.test(path),
  );
  if (match === undefined) {
    return { status: 404, headers: {}, body: null };
  }
  return { status: match.fixture.response.status, headers: {}, body: match.fixture.response.body };
}

/** Serves `fixtures/api/` instead of the network when VITE_API_MODE=mock. */
export function installMockApi(): void {
  setTransport(async (request) => mockResponse(request));
}

export const mockFixtureCount = fixtures.length;
