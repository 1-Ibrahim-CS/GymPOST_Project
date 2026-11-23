import { CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';

import { AuthService } from '../services/auth.service';

@Component({
  selector: 'app-navbar',
  imports: [CommonModule, RouterLink, RouterLinkActive],
  template: `
    <nav class="navbar navbar-expand-lg navbar-dark bg-brand sticky-top shadow-sm">
      <div class="container">
        <a class="navbar-brand fw-bold" routerLink="/">
          <i class="bi bi-activity me-1"></i> PulseFit
        </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#mainNav"
                aria-controls="mainNav" aria-expanded="false" aria-label="Toggle navigation">
          <span class="navbar-toggler-icon"></span>
        </button>

        <div class="collapse navbar-collapse" id="mainNav">
          <ul class="navbar-nav me-auto">
            <li class="nav-item" *ngFor="let link of links">
              <a class="nav-link" [routerLink]="link.path" routerLinkActive="active"
                 [routerLinkActiveOptions]="{ exact: link.path === '/' }">
                <i class="bi me-1" [ngClass]="link.icon"></i>{{ link.label }}
              </a>
            </li>
          </ul>

          <ng-container *ngIf="auth.session$ | async as session; else loggedOut">
            <ul class="navbar-nav">
              <li class="nav-item">
                <a class="nav-link" routerLink="/me" routerLinkActive="active">
                  <i class="bi bi-speedometer2 me-1"></i>My PulseFit
                </a>
              </li>
              <li class="nav-item dropdown">
                <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown" aria-expanded="false">
                  <i class="bi bi-person-circle me-1"></i>{{ session.user.username }}
                </a>
                <ul class="dropdown-menu dropdown-menu-end">
                  <li>
                    <span class="dropdown-item-text small">
                      Signed in as <span class="badge" [ngClass]="roleBadge(session.user.role)">{{ session.user.role }}</span>
                    </span>
                  </li>
                  <li><hr class="dropdown-divider"></li>
                  <li>
                    <button class="dropdown-item" (click)="logout()">
                      <i class="bi bi-box-arrow-right me-1"></i>Log out
                    </button>
                  </li>
                </ul>
              </li>
            </ul>
          </ng-container>

          <ng-template #loggedOut>
            <div class="d-flex gap-2">
              <a class="btn btn-outline-light btn-sm" routerLink="/login">Log in</a>
              <a class="btn btn-light btn-sm" routerLink="/register">Join PulseFit</a>
            </div>
          </ng-template>
        </div>
      </div>
    </nav>
  `
})
export class NavbarComponent {
  auth = inject(AuthService);
  private router = inject(Router);

  links = [
    { path: '/', label: 'Home', icon: 'bi-house' },
    { path: '/classes', label: 'Classes', icon: 'bi-calendar-event' },
    { path: '/exercises', label: 'Exercises', icon: 'bi-lightning-charge' },
    { path: '/branches', label: 'Branches', icon: 'bi-geo-alt' }
  ];

  roleBadge(role: string): string {
    switch (role) {
      case 'admin': return 'text-bg-danger';
      case 'trainer': return 'text-bg-warning';
      default: return 'text-bg-success';
    }
  }

  logout(): void {
    this.auth.logout().subscribe(() => this.router.navigate(['/']));
  }
}
