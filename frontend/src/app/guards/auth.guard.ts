import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { Role } from '../models/user.model';
import { AuthService } from '../services/auth.service';

// logged-in users only; add data: { roles: ['admin'] } to a route to limit it to some roles
export const authGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!auth.isLoggedIn()) {
    return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  }
  const roles = route.data['roles'] as Role[] | undefined;
  if (roles && !auth.hasRole(...roles)) {
    return router.createUrlTree(['/']);
  }
  return true;
};

// login and register pages are for logged-out users only
export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return auth.isLoggedIn() ? router.createUrlTree(['/me']) : true;
};
