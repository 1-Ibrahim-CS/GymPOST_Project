import { ComponentFixture, TestBed } from '@angular/core/testing';

import { StarRatingComponent } from './star-rating.component';

describe('StarRatingComponent', () => {
  let fixture: ComponentFixture<StarRatingComponent>;
  let component: StarRatingComponent;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [StarRatingComponent] });
    fixture = TestBed.createComponent(StarRatingComponent);
    component = fixture.componentInstance;
  });

  it('shows full, half and empty stars', () => {
    component.rating = 3.5;
    fixture.detectChanges();
    const icons = Array.from(fixture.nativeElement.querySelectorAll('i') as NodeListOf<HTMLElement>);
    expect(icons.filter(i => i.classList.contains('bi-star-fill')).length).toBe(3);
    expect(icons.filter(i => i.classList.contains('bi-star-half')).length).toBe(1);
    expect(icons.filter(i => i.classList.contains('bi-star')).length).toBe(1);
  });

  it('emits the clicked star when editable', () => {
    component.editable = true;
    fixture.detectChanges();
    let picked = 0;
    component.ratingChange.subscribe(star => picked = star);
    (fixture.nativeElement.querySelectorAll('i')[3] as HTMLElement).click();
    expect(picked).toBe(4);
  });

  it('ignores clicks when read-only', () => {
    component.rating = 2;
    fixture.detectChanges();
    (fixture.nativeElement.querySelectorAll('i')[4] as HTMLElement).click();
    expect(component.rating).toBe(2);
  });
});
