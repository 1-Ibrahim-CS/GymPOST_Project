import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { MemberBooking } from '../../models/gym-class.model';
import { Pagination } from '../../models/page.model';
import { CurrentUser } from '../../models/user.model';
import { HasRoleDirective } from '../../directives/has-role.directive';
import { TimeUntilPipe } from '../../pipes/time-until.pipe';
import { errorMessage } from '../../services/api-helpers';
import { AuthService } from '../../services/auth.service';
import { ClassService } from '../../services/class.service';
import { MemberService } from '../../services/member.service';
import { PaginationComponent } from '../../shared/pagination.component';

type BookingTab = 'upcoming' | 'past';

@Component({
  selector: 'app-dashboard',
  imports: [CommonModule, RouterLink, HasRoleDirective, TimeUntilPipe, PaginationComponent],
  templateUrl: './dashboard.component.html'
})
export class DashboardComponent implements OnInit {
  auth = inject(AuthService);
  private memberService = inject(MemberService);
  private classService = inject(ClassService);
  private route = inject(ActivatedRoute);

  me: CurrentUser | null = null;
  welcome = this.route.snapshot.queryParamMap.has('welcome');
  error = '';

  tab: BookingTab = 'upcoming';
  bookings: MemberBooking[] = [];
  pagination: Pagination | null = null;
  bookingsLoading = false;
  message = '';

  ngOnInit(): void {
    this.auth.me().subscribe({
      next: me => this.me = me,
      error: (err: HttpErrorResponse) => this.error = errorMessage(err)
    });
    if (this.auth.hasRole('member')) {
      this.loadBookings(1);
    }
  }

  // days until the membership ends (negative once it has expired)
  daysLeft(): number {
    const end = this.me?.member?.membership.end_date;
    return end ? Math.ceil((new Date(end).getTime() - Date.now()) / 86400000) : 0;
  }

  showTab(tab: BookingTab): void {
    this.tab = tab;
    this.loadBookings(1);
  }

  loadBookings(page: number): void {
    const memberId = this.auth.user?.member_id;
    if (!memberId) {
      return;
    }
    this.bookingsLoading = true;
    this.memberService.getBookings(memberId, { when: this.tab, pn: page, ps: 5 }).subscribe({
      next: res => {
        this.bookings = res.data;
        this.pagination = res.pagination;
        this.bookingsLoading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.error = errorMessage(err);
        this.bookingsLoading = false;
      }
    });
  }

  cancel(booking: MemberBooking): void {
    if (!confirm(`Cancel your place on ${booking.class.title}?`)) {
      return;
    }
    this.classService.cancelBooking(booking.class._id, booking._id).subscribe({
      next: () => {
        this.message = `Your booking for ${booking.class.title} has been cancelled.`;
        this.loadBookings(this.pagination?.page ?? 1);
        setTimeout(() => this.message = '', 4000);
      },
      error: (err: HttpErrorResponse) => this.error = errorMessage(err)
    });
  }

  // label shown for each booking - ngSwitch in the template picks the badge colour
  bookingState(booking: MemberBooking): string {
    if (booking.status === 'cancelled' || booking.class.status === 'cancelled') {
      return 'cancelled';
    }
    if (this.tab === 'upcoming') {
      return 'booked';
    }
    if (booking.attended === true) {
      return 'attended';
    }
    return booking.attended === false ? 'missed' : 'unrecorded';
  }
}
