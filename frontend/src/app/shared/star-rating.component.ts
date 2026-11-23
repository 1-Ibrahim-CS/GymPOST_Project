import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

// shows 1-5 stars; with [editable]="true" the user can click to pick a rating
@Component({
  selector: 'app-star-rating',
  imports: [CommonModule],
  template: `
    <span class="stars" [class.editable]="editable" [attr.aria-label]="(rating ?? 0) + ' out of 5 stars'">
      <i *ngFor="let star of starNumbers"
         class="bi"
         [ngClass]="iconFor(star)"
         (click)="pick(star)"
         (mouseenter)="hover = editable ? star : 0"
         (mouseleave)="hover = 0"></i>
    </span>
  `,
  styles: [`
    .stars { color: #f5b301; white-space: nowrap; }
    .stars i { margin-right: 2px; }
    .editable i { cursor: pointer; font-size: 1.4rem; }
  `]
})
export class StarRatingComponent {
  @Input() rating: number | null = 0;
  @Input() editable = false;
  @Output() ratingChange = new EventEmitter<number>();

  starNumbers = [1, 2, 3, 4, 5];
  hover = 0;

  iconFor(star: number): string {
    const value = this.hover || this.rating || 0;
    if (value >= star) {
      return 'bi-star-fill';
    }
    if (value >= star - 0.5) {
      return 'bi-star-half';
    }
    return 'bi-star';
  }

  pick(star: number): void {
    if (this.editable) {
      this.rating = star;
      this.ratingChange.emit(star);
    }
  }
}
