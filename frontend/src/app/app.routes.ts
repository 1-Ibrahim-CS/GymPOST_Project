import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './guards/auth.guard';
import { BranchListComponent } from './pages/branch-list/branch-list.component';
import { ClassListComponent } from './pages/class-list/class-list.component';
import { DashboardComponent } from './pages/dashboard/dashboard.component';
import { ExerciseDetailComponent } from './pages/exercise-detail/exercise-detail.component';
import { ExerciseListComponent } from './pages/exercise-list/exercise-list.component';
import { HomeComponent } from './pages/home/home.component';
import { LoginComponent } from './pages/login/login.component';
import { NotFoundComponent } from './pages/not-found/not-found.component';
import { RegisterComponent } from './pages/register/register.component';

export const routes: Routes = [
  { path: '', component: HomeComponent, title: 'PulseFit' },
  { path: 'classes', component: ClassListComponent, title: 'Classes · PulseFit' },
  { path: 'exercises', component: ExerciseListComponent, title: 'Exercises · PulseFit' },
  { path: 'exercises/:id', component: ExerciseDetailComponent, title: 'Exercise · PulseFit' },
  { path: 'branches', component: BranchListComponent, title: 'Branches · PulseFit' },
  { path: 'login', component: LoginComponent, canActivate: [guestGuard], title: 'Log in · PulseFit' },
  { path: 'register', component: RegisterComponent, canActivate: [guestGuard], title: 'Join · PulseFit' },
  { path: 'me', component: DashboardComponent, canActivate: [authGuard], title: 'My PulseFit' },
  { path: '**', component: NotFoundComponent, title: 'Not found · PulseFit' }
];
