import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { Branch } from '../../models/branch.model';
import { errorMessage } from '../../services/api-helpers';
import { BranchService } from '../../services/branch.service';

@Component({
  selector: 'app-branch-list',
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './branch-list.component.html'
})
export class BranchListComponent implements OnInit {
  private branchService = inject(BranchService);

  branches: Branch[] = [];
  search = '';
  loading = true;
  locating = false;
  nearMode = false;
  error = '';

  ngOnInit(): void {
    this.loadAll();
  }

  loadAll(): void {
    this.loading = true;
    this.nearMode = false;
    this.error = '';
    this.branchService.getBranches({ q: this.search, ps: 100 }).subscribe({
      next: page => {
        this.branches = page.data;
        this.loading = false;
      },
      error: (err: HttpErrorResponse) => {
        this.error = errorMessage(err);
        this.loading = false;
      }
    });
  }

  // ask the browser for the user's location, then get the nearest branches
  findNearMe(): void {
    if (!navigator.geolocation) {
      this.error = 'Your browser cannot share your location.';
      return;
    }
    this.locating = true;
    this.error = '';
    navigator.geolocation.getCurrentPosition(
      position => {
        this.branchService.getNear(position.coords.latitude, position.coords.longitude, 100).subscribe({
          next: res => {
            this.branches = res.data;
            this.nearMode = true;
            this.locating = false;
          },
          error: (err: HttpErrorResponse) => {
            this.error = errorMessage(err);
            this.locating = false;
          }
        });
      },
      () => {
        this.error = 'We could not get your location. Allow location access and try again.';
        this.locating = false;
      }
    );
  }

  mapLink(branch: Branch): string {
    const [lng, lat] = branch.location.coordinates;
    return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=15/${lat}/${lng}`;
  }
}
