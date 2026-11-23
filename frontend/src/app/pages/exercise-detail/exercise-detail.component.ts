import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { Exercise, Review } from '../../models/exercise.model';
import { errorMessage } from '../../services/api-helpers';
import { AuthService } from '../../services/auth.service';
import { ExerciseService } from '../../services/exercise.service';
import { StarRatingComponent } from '../../shared/star-rating.component';

@Component({
  selector: 'app-exercise-detail',
  imports: [CommonModule, FormsModule, RouterLink, StarRatingComponent],
  templateUrl: './exercise-detail.component.html'
})
export class ExerciseDetailComponent implements OnInit {
  auth = inject(AuthService);
  private exerciseService = inject(ExerciseService);
  private route = inject(ActivatedRoute);

  exercise: Exercise | null = null;
  reviews: Review[] = [];
  loading = true;
  error = '';
  message = '';

  // the "add review" form and the inline edit form
  newReview = { stars: 0, comment: '' };
  editingId: string | null = null;
  editReview = { stars: 0, comment: '' };
  formError = '';
  saving = false;

  private id = this.route.snapshot.paramMap.get('id')!;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.exerciseService.getExercise(this.id).subscribe({
      next: exercise => {
        this.exercise = exercise;
        // newest reviews first
        this.reviews = [...(exercise.reviews ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
        this.loading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.error = errorMessage(err);
        this.loading = false;
      }
    });
  }

  isMine(review: Review): boolean {
    return review.member_id === this.auth.user?.member_id;
  }

  // members can review each exercise once
  canReview(): boolean {
    return this.auth.hasRole('member') && !this.reviews.some(review => this.isMine(review));
  }

  // star counts for the rating breakdown bars
  starCount(stars: number): number {
    return this.reviews.filter(review => review.stars === stars).length;
  }

  starPercent(stars: number): number {
    return this.reviews.length ? Math.round(this.starCount(stars) / this.reviews.length * 100) : 0;
  }

  addReview(): void {
    if (!this.validReview(this.newReview)) {
      return;
    }
    this.saving = true;
    this.exerciseService.addReview(this.id, { stars: this.newReview.stars, comment: this.newReview.comment.trim() }).subscribe({
      next: () => {
        this.newReview = { stars: 0, comment: '' };
        this.done('Thanks! Your review has been added.');
      },
      error: (err: HttpErrorResponse) => this.failed(err)
    });
  }

  startEdit(review: Review): void {
    this.editingId = review._id;
    this.editReview = { stars: review.stars, comment: review.comment };
    this.formError = '';
  }

  saveEdit(): void {
    if (!this.editingId || !this.validReview(this.editReview)) {
      return;
    }
    this.saving = true;
    this.exerciseService.updateReview(this.id, this.editingId,
      { stars: this.editReview.stars, comment: this.editReview.comment.trim() }).subscribe({
      next: () => {
        this.editingId = null;
        this.done('Your review has been updated.');
      },
      error: (err: HttpErrorResponse) => this.failed(err)
    });
  }

  deleteReview(review: Review): void {
    const who = this.isMine(review) ? 'your review' : `the review by ${review.member_name}`;
    if (!confirm(`Delete ${who}? This cannot be undone.`)) {
      return;
    }
    this.exerciseService.deleteReview(this.id, review._id).subscribe({
      next: () => this.done('The review has been deleted.'),
      error: (err: HttpErrorResponse) => this.failed(err)
    });
  }

  private validReview(review: { stars: number; comment: string }): boolean {
    if (review.stars < 1) {
      this.formError = 'Pick a star rating.';
      return false;
    }
    if (review.comment.trim().length < 2) {
      this.formError = 'Write a short comment (at least 2 characters).';
      return false;
    }
    this.formError = '';
    return true;
  }

  private done(message: string): void {
    this.saving = false;
    this.message = message;
    this.formError = '';
    this.load();
    setTimeout(() => this.message = '', 4000);
  }

  private failed(err: HttpErrorResponse): void {
    this.saving = false;
    this.formError = errorMessage(err);
  }
}
