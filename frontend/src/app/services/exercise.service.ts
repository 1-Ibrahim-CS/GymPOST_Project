import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Exercise, ExerciseFilters, Review, ReviewData } from '../models/exercise.model';
import { Page } from '../models/page.model';
import { toParams } from './api-helpers';

export interface ExerciseQuery {
  q?: string;
  body_part?: string;
  equipment?: string;
  level?: string;
  type?: string;
  sort?: string;
  order?: string;
  pn?: number;
  ps?: number;
}

@Injectable({ providedIn: 'root' })
export class ExerciseService {
  private http = inject(HttpClient);
  private api = environment.apiUrl;

  getExercises(query: ExerciseQuery): Observable<Page<Exercise>> {
    return this.http.get<Page<Exercise>>(`${this.api}/exercises`, { params: toParams(query) });
  }

  getFilters(): Observable<ExerciseFilters> {
    return this.http.get<ExerciseFilters>(`${this.api}/exercises/filters`);
  }

  getTopRated(limit: number, minReviews = 2): Observable<{ data: Exercise[]; count: number }> {
    return this.http.get<{ data: Exercise[]; count: number }>(`${this.api}/exercises/top-rated`,
      { params: toParams({ limit, min_reviews: minReviews }) });
  }

  getExercise(id: string): Observable<Exercise> {
    return this.http.get<Exercise>(`${this.api}/exercises/${id}`);
  }

  addReview(exerciseId: string, review: ReviewData): Observable<{ message: string; id: string }> {
    return this.http.post<{ message: string; id: string }>(`${this.api}/exercises/${exerciseId}/reviews`, review);
  }

  updateReview(exerciseId: string, reviewId: string, review: ReviewData): Observable<{ message: string; review: Review }> {
    return this.http.put<{ message: string; review: Review }>(
      `${this.api}/exercises/${exerciseId}/reviews/${reviewId}`, review);
  }

  deleteReview(exerciseId: string, reviewId: string): Observable<unknown> {
    return this.http.delete(`${this.api}/exercises/${exerciseId}/reviews/${reviewId}`);
  }
}
