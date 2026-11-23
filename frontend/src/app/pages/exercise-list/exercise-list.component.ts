import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { Exercise, ExerciseFilters } from '../../models/exercise.model';
import { Pagination } from '../../models/page.model';
import { errorMessage } from '../../services/api-helpers';
import { ExerciseQuery, ExerciseService } from '../../services/exercise.service';
import { PaginationComponent } from '../../shared/pagination.component';
import { StarRatingComponent } from '../../shared/star-rating.component';

@Component({
  selector: 'app-exercise-list',
  imports: [CommonModule, FormsModule, RouterLink, PaginationComponent, StarRatingComponent],
  templateUrl: './exercise-list.component.html'
})
export class ExerciseListComponent implements OnInit, OnDestroy {
  private exerciseService = inject(ExerciseService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private sub?: Subscription;

  exercises: Exercise[] = [];
  pagination: Pagination | null = null;
  filterOptions: ExerciseFilters | null = null;
  loading = false;
  error = '';

  // the filters live in the URL so the back button and shared links keep them
  query: ExerciseQuery = {};
  sortOptions = [
    { value: '', label: 'Relevance' },
    { value: 'rating', label: 'Highest rated' },
    { value: 'reviews', label: 'Most reviewed' },
    { value: 'title', label: 'Title A–Z' }
  ];

  ngOnInit(): void {
    this.exerciseService.getFilters().subscribe(filters => this.filterOptions = filters);

    this.sub = this.route.queryParamMap.subscribe(params => {
      this.query = {
        q: params.get('q') ?? '',
        body_part: params.get('body_part') ?? '',
        equipment: params.get('equipment') ?? '',
        level: params.get('level') ?? '',
        type: params.get('type') ?? '',
        sort: params.get('sort') ?? '',
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
    // rating and reviews make most sense highest first, titles A-Z
    const order = this.query.sort === 'title' ? 'asc' : this.query.sort ? 'desc' : '';
    this.exerciseService.getExercises({ ...this.query, order, ps: 12 }).subscribe({
      next: page => {
        this.exercises = page.data;
        this.pagination = page.pagination;
        this.loading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.error = errorMessage(err);
        this.loading = false;
      }
    });
  }

  // any filter change goes back to page 1
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

  hasFilters(): boolean {
    const q = this.query;
    return !!(q.q || q.body_part || q.equipment || q.level || q.type || q.sort);
  }

  levelClass(level: string): string {
    switch (level) {
      case 'Beginner': return 'text-bg-success';
      case 'Intermediate': return 'text-bg-warning';
      default: return 'text-bg-danger';
    }
  }

  private updateUrl(query: ExerciseQuery): void {
    const queryParams: Record<string, string | number> = {};
    for (const [key, value] of Object.entries(query)) {
      if (value && !(key === 'pn' && value === 1)) {
        queryParams[key] = value;
      }
    }
    this.router.navigate([], { relativeTo: this.route, queryParams });
  }
}
