import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';

import { AuthService } from '../services/auth.service';
import { authGuard } from './auth.guard';

describe('authGuard', () => {
  let auth: jasmine.SpyObj<AuthService>;
  let router: Router;

  function runGuard(roles?: string[]) {
    const route = { data: roles ? { roles } : {} } as unknown as ActivatedRouteSnapshot;
    const state = { url: '/me' } as RouterStateSnapshot;
    return TestBed.runInInjectionContext(() => authGuard(route, state));
  }

  beforeEach(() => {
    auth = jasmine.createSpyObj<AuthService>('AuthService', ['isLoggedIn', 'hasRole']);
    TestBed.configureTestingModule({
      providers: [provideRouter([]), { provide: AuthService, useValue: auth }]
    });
    router = TestBed.inject(Router);
  });

  it('sends logged-out users to login with a return URL', () => {
    auth.isLoggedIn.and.returnValue(false);
    const result = runGuard() as UrlTree;
    expect(router.serializeUrl(result)).toBe('/login?returnUrl=%2Fme');
  });

  it('lets logged-in users through', () => {
    auth.isLoggedIn.and.returnValue(true);
    expect(runGuard()).toBeTrue();
  });

  it('blocks users without the required role', () => {
    auth.isLoggedIn.and.returnValue(true);
    auth.hasRole.and.returnValue(false);
    const result = runGuard(['admin']) as UrlTree;
    expect(router.serializeUrl(result)).toBe('/');
  });
});
