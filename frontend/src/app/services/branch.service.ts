import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { Branch } from '../models/branch.model';
import { Page } from '../models/page.model';
import { toParams } from './api-helpers';

export interface BranchQuery {
  q?: string;
  city?: string;
  facility?: string;
  pn?: number;
  ps?: number;
}

@Injectable({ providedIn: 'root' })
export class BranchService {
  private http = inject(HttpClient);
  private api = environment.apiUrl;

  getBranches(query: BranchQuery = {}): Observable<Page<Branch>> {
    return this.http.get<Page<Branch>>(`${this.api}/branches`, { params: toParams(query) });
  }

  getBranch(id: string): Observable<Branch> {
    return this.http.get<Branch>(`${this.api}/branches/${id}`);
  }

  // nearest branches first, each with distance_km
  getNear(lat: number, lng: number, km = 50): Observable<{ data: Branch[] }> {
    return this.http.get<{ data: Branch[] }>(`${this.api}/branches/near`,
      { params: toParams({ lat, lng, km }) });
  }
}
