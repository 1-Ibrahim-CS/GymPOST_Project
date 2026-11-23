import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { Branch } from '../../models/branch.model';
import { GymClass } from '../../models/gym-class.model';
import { Pagination } from '../../models/page.model';
import { TimeUntilPipe } from '../../pipes/time-until.pipe';
import { errorMessage } from '../../services/api-helpers';
import { AuthService } from '../../services/auth.service';
import { BranchService } from '../../services/branch.service';
import { ClassQuery, ClassService } from '../../services/class.service';
import { MemberService } from '../../services/member.service';
import { PaginationComponent } from '../../shared/pagination.component';

@Component({
  selector: 'app-class-list',
  imports: [CommonModule, FormsModule, RouterLink, PaginationComponent, TimeUntilPipe],
  templateUrl: './class-list.component.html'
})
export class ClassListComponent implements OnInit, OnDestroy {
  auth = inject(AuthService);
  private classService = inject(ClassService);
  private branchService = inject(BranchService);
  private memberService = inject(MemberService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private sub?: Subscription;

  classes: GymClass[] = [];
  branches: Branch[] = [];
  pagination: Pagination | null = null;
  loading = false;
  error = '';

  categories = ['Cardio', 'HIIT', 'Strength', 'Yoga'];
  levels = ['Beginner', 'All levels', 'Intermediate', 'Advanced'];
  query: ClassQuery = {};

  // class id -> booking id, for the classes the logged-in member has booked
  myBookings = new Map<string, string>();
  bookingNow: string | null = null;
  toast: { type: 'success' | 'danger'; text: string } | null = null;

  ngOnInit(): void {
    this.branchService.getBranches({ ps: 100 }).subscribe(res => this.branches = res.data);
    this.loadMyBookings();

    this.sub = this.route.queryParamMap.subscribe(params => {
      this.query = {
        q: params.get('q') ?? '',
        branch: params.get('branch') ?? '',
        category: params.get('category') ?? '',
        level: params.get('level') ?? '',
        available: params.get('available') === 'true' ? true : '',
        pn: Number(params.get('pn')) || 1
      };
      this.load();
    });
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  load(): void {
    this.loading = true;
    this.error = '';
    this.classService.getClasses({ ...this.query, ps: 10 }).subscribe({
      next: page => {
        this.classes = page.data;
        this.pagination = page.pagination;
        this.loading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.error = errorMessage(err);
        this.loading = false;
      }
    });
  }

  loadMyBookings(): void {
    const memberId = this.auth.user?.member_id;
    if (!this.auth.hasRole('member') || !memberId) {
      return;
    }
    this.memberService.getBookings(memberId, { when: 'upcoming', status: 'booked', ps: 100 }).subscribe(page => {
      this.myBookings = new Map(page.data.map(booking => [booking.class._id, booking._id]));
    });
  }

  applyFilters(): void {
    this.updateUrl({ ...this.query, pn: 1 });
  }

  goToPage(page: number): void {
    this.updateUrl({ ...this.query, pn: page });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  clearFilters(): void {
    this.updateUrl({});
  }

  book(cls: GymClass): void {
    this.bookingNow = cls._id;
    this.classService.book(cls._id).subscribe({
      next: res => {
        this.myBookings.set(cls._id, res.id);
        cls.booked_count++;
        cls.spaces_left = res.spaces_left ?? cls.spaces_left - 1;
        this.bookingNow = null;
        this.showToast('success', `You're booked on ${cls.title}. See you there!`);
      },
      error: (err: HttpErrorResponse) => {
        this.bookingNow = null;
        this.showToast('danger', errorMessage(err));
      }
    });
  }

  cancel(cls: GymClass): void {
    const bookingId = this.myBookings.get(cls._id);
    if (!bookingId || !confirm(`Cancel your place on ${cls.title}?`)) {
      return;
    }
    this.bookingNow = cls._id;
    this.classService.cancelBooking(cls._id, bookingId).subscribe({
      next: () => {
        this.myBookings.delete(cls._id);
        cls.booked_count--;
        cls.spaces_left++;
        this.bookingNow = null;
        this.showToast('success', 'Your booking has been cancelled.');
      },
      error: (err: HttpErrorResponse) => {
        this.bookingNow = null;
        this.showToast('danger', errorMessage(err));
      }
    });
  }

  fillPercent(cls: GymClass): number {
    return Math.min(100, Math.round(cls.booked_count / cls.capacity * 100));
  }

  // green, amber when nearly full, red when full
  fillClass(cls: GymClass): string {
    if (cls.spaces_left === 0) {
      return 'bg-danger';
    }
    return cls.spaces_left <= 3 ? 'bg-warning' : 'bg-success';
  }

  categoryIcon(category: string): string {
    switch (category) {
      case 'Cardio': return 'bi-heart-pulse';
      case 'HIIT': return 'bi-lightning-charge';
      case 'Strength': return 'bi-trophy';
      default: return 'bi-flower1';
    }
  }

  private showToast(type: 'success' | 'danger', text: string): void {
    this.toast = { type, text };
    setTimeout(() => this.toast = null, 4000);
  }

  private updateUrl(query: ClassQuery): void {
    const queryParams: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(query)) {
      if (value && !(key === 'pn' && value === 1)) {
        queryParams[key] = value;
      }
    }
    this.router.navigate([], { relativeTo: this.route, queryParams });
  }
}
