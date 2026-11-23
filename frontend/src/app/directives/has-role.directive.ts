import { Directive, Input, OnDestroy, OnInit, TemplateRef, ViewContainerRef, inject } from '@angular/core';
import { Subscription } from 'rxjs';

import { Role } from '../models/user.model';
import { AuthService } from '../services/auth.service';

// structural directive: <button *appHasRole="'admin'"> or *appHasRole="['admin', 'trainer']"
// shows the element only for those roles and updates when the user logs in or out
@Directive({ selector: '[appHasRole]' })
export class HasRoleDirective implements OnInit, OnDestroy {
  private templateRef = inject(TemplateRef<unknown>);
  private viewContainer = inject(ViewContainerRef);
  private auth = inject(AuthService);
  private roles: Role[] = [];
  private shown = false;
  private sub?: Subscription;

  @Input() set appHasRole(roles: Role | Role[]) {
    this.roles = Array.isArray(roles) ? roles : [roles];
    this.update();
  }

  ngOnInit(): void {
    this.sub = this.auth.session$.subscribe(() => this.update());
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  private update(): void {
    const allowed = this.auth.hasRole(...this.roles);
    if (allowed && !this.shown) {
      this.viewContainer.createEmbeddedView(this.templateRef);
      this.shown = true;
    } else if (!allowed && this.shown) {
      this.viewContainer.clear();
      this.shown = false;
    }
  }
}
