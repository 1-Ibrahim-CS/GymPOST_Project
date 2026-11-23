import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { switchMap } from 'rxjs';

import { Branch } from '../../models/branch.model';
import { RegisterData } from '../../models/user.model';
import { errorDetails, errorMessage } from '../../services/api-helpers';
import { AuthService } from '../../services/auth.service';
import { BranchService } from '../../services/branch.service';

@Component({
  selector: 'app-register',
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './register.component.html'
})
export class RegisterComponent implements OnInit {
  private fb = inject(FormBuilder);
  private auth = inject(AuthService);
  private branchService = inject(BranchService);
  private router = inject(Router);

  branches: Branch[] = [];
  plans = ['Monthly', 'Quarterly', 'Annual', 'Student'];
  genders = ['Male', 'Female'];
  workoutTypes = ['Cardio', 'HIIT', 'Strength', 'Yoga'];
  levels = ['Beginner', 'Intermediate', 'Expert'];

  // same rules as the API's register schema
  form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(80)]],
    username: ['', [Validators.required, Validators.minLength(3), Validators.maxLength(30), Validators.pattern(/^[A-Za-z0-9._-]+$/)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8), Validators.maxLength(72)]],
    gender: ['', Validators.required],
    age: [null as number | null, [Validators.required, Validators.min(16), Validators.max(100)]],
    home_branch_id: ['', Validators.required],
    plan: ['Monthly'],
    preferred_workout: [''],
    experience_level: ['']
  });

  error = '';
  serverErrors: Record<string, string> = {};
  submitting = false;

  ngOnInit(): void {
    this.branchService.getBranches({ ps: 100 }).subscribe({
      next: res => this.branches = res.data,
      error: (err: HttpErrorResponse) => this.error = errorMessage(err)
    });
  }

  // true when a field should show its red error state
  invalid(name: string): boolean {
    const control = this.form.get(name);
    return (!!control && control.touched && control.invalid) || !!this.serverErrors[name];
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting = true;
    this.error = '';
    this.serverErrors = {};

    // the API rejects unknown or empty fields, so only send the ones that are filled in
    const value = this.form.getRawValue();
    const data: RegisterData = {
      name: value.name.trim(),
      username: value.username.trim(),
      email: value.email.trim(),
      password: value.password,
      gender: value.gender,
      age: Number(value.age),
      home_branch_id: value.home_branch_id,
      plan: value.plan
    };
    if (value.preferred_workout) {
      data.preferred_workout = value.preferred_workout;
    }
    if (value.experience_level) {
      data.experience_level = value.experience_level;
    }

    // create the account, then log straight in
    this.auth.register(data).pipe(
      switchMap(() => this.auth.login(data.username, data.password))
    ).subscribe({
      next: () => this.router.navigate(['/me'], { queryParams: { welcome: 1 } }),
      error: (err: HttpErrorResponse) => {
        this.error = errorMessage(err);
        this.serverErrors = errorDetails(err);
        this.submitting = false;
      }
    });
  }

  // clear a server error as soon as the user edits that field
  clearServerError(name: string): void {
    delete this.serverErrors[name];
  }
}
