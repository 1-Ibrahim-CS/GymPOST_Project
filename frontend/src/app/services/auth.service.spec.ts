import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { environment } from '../../environments/environment';
import { Session } from '../models/user.model';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;

  const session: Session = {
    token: 'abc.def.ghi',
    expires_at: new Date(Date.now() + 8 * 60000).toISOString(),
    user: { user_id: 'u1', username: 'oliver.robinson', role: 'member', member_id: 'm1' }
  };

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()]
    });
    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    service.clearSession();
  });

  it('starts logged out', () => {
    expect(service.isLoggedIn()).toBeFalse();
    expect(service.token).toBeNull();
  });

  it('logs in with HTTP Basic auth and stores the session', () => {
    service.login('oliver.robinson', 'Password123!').subscribe();

    const req = http.expectOne(`${environment.apiUrl}/auth/login`);
    expect(req.request.method).toBe('GET');
    expect(req.request.headers.get('Authorization')).toBe('Basic ' + btoa('oliver.robinson:Password123!'));
    req.flush(session);

    expect(service.isLoggedIn()).toBeTrue();
    expect(service.token).toBe('abc.def.ghi');
    expect(service.user?.member_id).toBe('m1');
    expect(JSON.parse(localStorage.getItem('pulsefit_session')!).token).toBe('abc.def.ghi');
  });

  it('checks roles', () => {
    service.login('oliver.robinson', 'Password123!').subscribe();
    http.expectOne(`${environment.apiUrl}/auth/login`).flush(session);

    expect(service.hasRole('member')).toBeTrue();
    expect(service.hasRole('admin', 'trainer')).toBeFalse();
  });

  it('clears the session on logout even if the API call fails', () => {
    service.login('oliver.robinson', 'Password123!').subscribe();
    http.expectOne(`${environment.apiUrl}/auth/login`).flush(session);

    service.logout().subscribe();
    http.expectOne(`${environment.apiUrl}/auth/logout`).flush({ error: 'Token has expired' }, { status: 401, statusText: 'Unauthorized' });

    expect(service.isLoggedIn()).toBeFalse();
    expect(localStorage.getItem('pulsefit_session')).toBeNull();
  });

  it('ignores a saved session that has already expired', () => {
    localStorage.setItem('pulsefit_session', JSON.stringify({ ...session, expires_at: '2000-01-01T00:00:00Z' }));
    const fresh = TestBed.runInInjectionContext(() => new AuthService());
    expect(fresh.isLoggedIn()).toBeFalse();
  });
});
