import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { AuthService } from '../services/auth.service';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let auth: AuthService;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting()
      ]
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    httpMock.verify();
    auth.clearSession();
  });

  function logIn(): void {
    auth.login('member', 'pw').subscribe();
    httpMock.expectOne(req => req.url.endsWith('/auth/login')).flush({
      token: 'my-token',
      expires_at: new Date(Date.now() + 60000).toISOString(),
      user: { user_id: 'u1', username: 'member', role: 'member', member_id: 'm1' }
    });
  }

  it('sends no token when logged out', () => {
    http.get('/api/test').subscribe();
    const req = httpMock.expectOne('/api/test');
    expect(req.request.headers.has('x-access-token')).toBeFalse();
    req.flush({});
  });

  it('adds the x-access-token header when logged in', () => {
    logIn();
    http.get('/api/test').subscribe();
    const req = httpMock.expectOne('/api/test');
    expect(req.request.headers.get('x-access-token')).toBe('my-token');
    req.flush({});
  });

  it('logs out and goes to the login page on a 401', () => {
    logIn();
    const navigate = spyOn(router, 'navigate').and.resolveTo(true);

    http.get('/api/test').subscribe({ error: () => undefined });
    httpMock.expectOne('/api/test').flush({ error: 'Token has expired' }, { status: 401, statusText: 'Unauthorized' });

    expect(auth.isLoggedIn()).toBeFalse();
    expect(navigate).toHaveBeenCalledWith(['/login'], jasmine.objectContaining({ queryParams: jasmine.objectContaining({ expired: 1 }) }));
  });
});
