import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

import { Pagination } from '../models/page.model';

// works with the { page, pages, total } object every API list returns
@Component({
  selector: 'app-pagination',
  imports: [CommonModule],
  template: `
    <nav *ngIf="pagination && pagination.pages > 1" class="d-flex flex-wrap align-items-center justify-content-between gap-2 mt-4">
      <small class="text-body-secondary">
        Page {{ pagination.page }} of {{ pagination.pages }} · {{ pagination.total }} results
      </small>
      <ul class="pagination mb-0">
        <li class="page-item" [class.disabled]="pagination.page === 1">
          <button class="page-link" (click)="go(pagination.page - 1)" aria-label="Previous page">
            <i class="bi bi-chevron-left"></i>
          </button>
        </li>
        <li *ngFor="let p of pageNumbers()" class="page-item" [class.active]="p === pagination.page">
          <button class="page-link" (click)="go(p)">{{ p }}</button>
        </li>
        <li class="page-item" [class.disabled]="pagination.page === pagination.pages">
          <button class="page-link" (click)="go(pagination.page + 1)" aria-label="Next page">
            <i class="bi bi-chevron-right"></i>
          </button>
        </li>
      </ul>
    </nav>
  `
})
export class PaginationComponent {
  @Input() pagination: Pagination | null = null;
  @Output() pageChange = new EventEmitter<number>();

  // up to 5 page numbers around the current page
  pageNumbers(): number[] {
    if (!this.pagination) {
      return [];
    }
    const { page, pages } = this.pagination;
    const first = Math.max(1, Math.min(page - 2, pages - 4));
    const last = Math.min(pages, first + 4);
    const numbers: number[] = [];
    for (let p = first; p <= last; p++) {
      numbers.push(p);
    }
    return numbers;
  }

  go(page: number): void {
    if (this.pagination && page >= 1 && page <= this.pagination.pages && page !== this.pagination.page) {
      this.pageChange.emit(page);
    }
  }
}
