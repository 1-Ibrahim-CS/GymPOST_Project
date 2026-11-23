import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { BehaviorSubject, Observable, catchError, finalize, of, tap } from 'rxjs';

import { environment } from '../../environments/environment';
import { CurrentUser, RegisterData, Role, Session, SessionUser } from '../models/user.model';

const STORAGE_KEY = 'pulsefit_session';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);
  private api = environment.apiUrl;
  private expiryTimer: ReturnType<typeof setTimeout> | null = null;

  // components subscribe to this to update when the user logs in or out
  private sessionSubject = new BehaviorSubject<Session | null>(null);
  session$ = this.sessionSubject.asObservable();

  constructor() {
    const saved = this.loadSession();
    if (saved) {
      this.startSession(saved);
    }
  }

  // the API uses HTTP Basic auth for login and returns a JWT
  login(username: string, password: string): Observable<Session> {
    const bytes = new TextEncoder().encode(username + ':' + password);
    const encoded = btoa(String.fromCharCode(...bytes));
    const headers = new HttpHeaders({ Authorization: 'Basic ' + encoded });
    return this.http.get<Session>(`${this.api}/auth/login`, { headers }).pipe(
      tap(session => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
        this.startSession(session);
      })
    );
  }

  register(data: RegisterData): Observable<{ message: string; id: string; user_id: string }> {
    return this.http.post<{ message: string; id: string; user_id: string }>(`${this.api}/auth/register`, data);
  }

  // blacklist the token on the server, then forget it here even if that call fails
  logout(): Observable<unknown> {
    return this.http.get(`${this.api}/auth/logout`).pipe(
      catchError(() => of(null)),
      finalize(() => this.clearSession())
    );
  }

  me(): Observable<CurrentUser> {
    return this.http.get<CurrentUser>(`${this.api}/auth/me`);
  }

  get token(): string | null {
    return this.sessionSubject.value?.token ?? null;
  }

  get user(): SessionUser | null {
    return this.sessionSubject.value?.user ?? null;
  }

  get expiresAt(): Date | null {
    const session = this.sessionSubject.value;
    return session ? new Date(session.expires_at) : null;
  }

  isLoggedIn(): boolean {
    const expires = this.expiresAt;
    return expires !== null && expires.getTime() > Date.now();
  }

  hasRole(...roles: Role[]): boolean {
    return this.isLoggedIn() && roles.includes(this.user!.role);
  }

  clearSession(): void {
    localStorage.removeItem(STORAGE_KEY);
    if (this.expiryTimer) {
      clearTimeout(this.expiryTimer);
      this.expiryTimer = null;
    }
    this.sessionSubject.next(null);
  }

  // tokens only last 8 minutes, so log the user out when it runs out
  private startSession(session: Session): void {
    this.sessionSubject.next(session);
    if (this.expiryTimer) {
      clearTimeout(this.expiryTimer);
    }
    const msLeft = new Date(session.expires_at).getTime() - Date.now();
    this.expiryTimer = setTimeout(() => {
      this.clearSession();
      this.router.navigate(['/login'], { queryParams: { expired: 1 } });
    }, msLeft);
  }

  private loadSession(): Session | null {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') as Session | null;
      if (saved && new Date(saved.expires_at).getTime() > Date.now()) {
        return saved;
      }
    } catch {
      // ignore a broken value and start logged out
    }
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}
