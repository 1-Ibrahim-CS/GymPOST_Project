import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { BehaviorSubject } from 'rxjs';

import { Role, Session } from '../models/user.model';
import { AuthService } from '../services/auth.service';
import { HasRoleDirective } from './has-role.directive';

@Component({
  imports: [HasRoleDirective],
  template: `
    <p id="admin" *appHasRole="'admin'">admin only</p>
    <p id="staff" *appHasRole="['admin', 'trainer']">staff only</p>
  `
})
class HostComponent {}

describe('HasRoleDirective', () => {
  let role: Role | null;
  const session$ = new BehaviorSubject<Session | null>(null);
  const fakeAuth = {
    session$,
    hasRole: (...roles: Role[]) => role !== null && roles.includes(role)
  };

  beforeEach(() => {
    role = null;
    TestBed.configureTestingModule({
      imports: [HostComponent],
      providers: [{ provide: AuthService, useValue: fakeAuth }]
    });
  });

  function render() {
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    return fixture;
  }

  it('hides everything when logged out', () => {
    const el = render().nativeElement as HTMLElement;
    expect(el.querySelector('#admin')).toBeNull();
    expect(el.querySelector('#staff')).toBeNull();
  });

  it('shows only the matching blocks for a trainer', () => {
    role = 'trainer';
    const el = render().nativeElement as HTMLElement;
    expect(el.querySelector('#admin')).toBeNull();
    expect(el.querySelector('#staff')).not.toBeNull();
  });

  it('updates when the user logs in', () => {
    const fixture = render();
    role = 'admin';
    session$.next(null);      // any session change makes the directive check again
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#admin')).not.toBeNull();
  });
});
