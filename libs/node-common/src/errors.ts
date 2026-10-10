/** Uniform error format: {"error": "<code>", "message": "<text>", ...extra}. */
export const DEFAULT_CODES: Record<number, string> = {
  400: 'bad_request',
  401: 'unauthorized',
  403: 'forbidden',
  404: 'not_found',
  405: 'method_not_allowed',
  409: 'conflict',
  422: 'invalid_arguments',
  429: 'rate_limited',
  500: 'internal_error',
  502: 'bad_gateway',
  503: 'service_unavailable',
  504: 'timeout',
};

/** Throw anywhere in a service to return a structured error response (HTTP or gRPC). */
export class AppError extends Error {
  constructor(
    readonly status: number,
    readonly error: string,
    message: string,
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message);
  }

  body(): Record<string, unknown> {
    return { error: this.error, message: this.message, ...this.extra };
  }
}

export function errorBody(error: string, message: string, extra: Record<string, unknown> = {}) {
  return { error, message, ...extra };
}
