import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';

// adds the JWT to every request and sends the user to login when the API says it has expired
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.token;

  // the login request uses Basic auth instead, so leave it alone
  if (token && !req.headers.has('Authorization')) {
    req = req.clone({ setHeaders: { 'x-access-token': token } });
  }

  return next(req).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status === 401 && token && !req.url.endsWith('/auth/logout')) {
        auth.clearSession();
        router.navigate(['/login'], { queryParams: { expired: 1, returnUrl: router.url } });
      }
      return throwError(() => err);
    })
  );
};
