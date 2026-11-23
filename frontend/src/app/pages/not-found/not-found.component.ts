import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-not-found',
  imports: [RouterLink],
  template: `
    <div class="container py-5 text-center">
      <i class="bi bi-signpost-split display-1 text-primary"></i>
      <h1 class="h2 mt-3">Page not found</h1>
      <p class="text-body-secondary">The page you're looking for doesn't exist.</p>
      <a class="btn btn-primary" routerLink="/">Back to home</a>
    </div>
  `
})
export class NotFoundComponent {}
