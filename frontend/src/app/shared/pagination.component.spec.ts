import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PaginationComponent } from './pagination.component';

describe('PaginationComponent', () => {
  let fixture: ComponentFixture<PaginationComponent>;
  let component: PaginationComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [PaginationComponent] });
    fixture = TestBed.createComponent(PaginationComponent);
    component = fixture.componentInstance;
  });

  it('is hidden when there is only one page', () => {
    component.pagination = { page: 1, page_size: 10, total: 5, pages: 1 };
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('nav')).toBeNull();
  });

  it('shows at most 5 page numbers around the current page', () => {
    component.pagination = { page: 10, page_size: 10, total: 300, pages: 30 };
    expect(component.pageNumbers()).toEqual([8, 9, 10, 11, 12]);
    component.pagination = { page: 1, page_size: 10, total: 300, pages: 30 };
    expect(component.pageNumbers()).toEqual([1, 2, 3, 4, 5]);
  });

  it('emits the page that was clicked', () => {
    component.pagination = { page: 1, page_size: 10, total: 30, pages: 3 };
    fixture.detectChanges();
    const emitted: number[] = [];
    component.pageChange.subscribe(page => emitted.push(page));

    const buttons = fixture.nativeElement.querySelectorAll('button.page-link') as NodeListOf<HTMLButtonElement>;
    buttons[2].click();     // [prev, 1, 2, 3, next] -> page 2
    expect(emitted).toEqual([2]);
  });

  it('does not go past the first or last page', () => {
    component.pagination = { page: 1, page_size: 10, total: 30, pages: 3 };
    const emitted: number[] = [];
    component.pageChange.subscribe(page => emitted.push(page));
    component.go(0);
    component.go(4);
    expect(emitted).toEqual([]);
  });
});
