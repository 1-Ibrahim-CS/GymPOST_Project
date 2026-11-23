import { CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { Exercise } from '../../models/exercise.model';
import { GymClass } from '../../models/gym-class.model';
import { AuthService } from '../../services/auth.service';
import { ClassService } from '../../services/class.service';
import { ExerciseService } from '../../services/exercise.service';
import { StarRatingComponent } from '../../shared/star-rating.component';
import { TimeUntilPipe } from '../../pipes/time-until.pipe';

@Component({
  selector: 'app-home',
  imports: [CommonModule, RouterLink, StarRatingComponent, TimeUntilPipe],
  templateUrl: './home.component.html'
})
export class HomeComponent implements OnInit {
  auth = inject(AuthService);
  private exerciseService = inject(ExerciseService);
  private classService = inject(ClassService);

  topExercises: Exercise[] = [];
  nextClasses: GymClass[] = [];
  loading = true;
  apiDown = false;

  features = [
    { icon: 'bi-calendar-check', title: 'Book classes', text: 'Reserve your place in HIIT, Yoga, Strength and Cardio classes at any branch.' },
    { icon: 'bi-lightning-charge', title: '300 exercises', text: 'Search the exercise library by body part, equipment and level, and read member reviews.' },
    { icon: 'bi-geo-alt', title: 'Find a branch', text: 'See opening hours and facilities, or find the branch nearest to you.' }
  ];

  ngOnInit(): void {
    this.exerciseService.getTopRated(4).subscribe({
      next: res => this.topExercises = res.data,
      error: () => this.apiDown = true
    });
    this.classService.getClasses({ ps: 4 }).subscribe({
      next: res => {
        this.nextClasses = res.data;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.apiDown = true;
      }
    });
  }
}
