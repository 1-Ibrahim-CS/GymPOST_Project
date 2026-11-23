import { HttpErrorResponse, HttpParams } from '@angular/common/http';

// build query params from an object, leaving out empty values
export function toParams(values: object): HttpParams {
  let params = new HttpParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== null && value !== undefined && value !== '') {
      params = params.set(key, String(value));
    }
  }
  return params;
}

// the API always sends errors as { error: "...", details: {...} }
export function errorMessage(err: HttpErrorResponse): string {
  if (err.status === 0) {
    return 'Cannot reach the PulseFit API. Check that the Flask server is running on port 5001.';
  }
  return err.error?.error || `Something went wrong (${err.status})`;
}

// field-by-field messages, e.g. { email: "An account with this email already exists" }
export function errorDetails(err: HttpErrorResponse): Record<string, string> {
  const details = err.error?.details;
  if (!details || typeof details !== 'object') {
    return {};
  }
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(details)) {
    result[key] = typeof value === 'string' ? value : JSON.stringify(value);
  }
  return result;
}
