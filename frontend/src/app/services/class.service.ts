import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { GymClass } from '../models/gym-class.model';
import { Page } from '../models/page.model';
import { toParams } from './api-helpers';

export interface ClassQuery {
  q?: string;
  branch?: string;
  trainer?: string;
  category?: string;
  level?: string;
  when?: string;
  available?: boolean | '';
  pn?: number;
  ps?: number;
}

@Injectable({ providedIn: 'root' })
export class ClassService {
  private http = inject(HttpClient);
  private api = environment.apiUrl;

  getClasses(query: ClassQuery): Observable<Page<GymClass>> {
    return this.http.get<Page<GymClass>>(`${this.api}/classes`, { params: toParams(query) });
  }

  getClass(id: string): Observable<GymClass> {
    return this.http.get<GymClass>(`${this.api}/classes/${id}`);
  }

  // members only - the API checks the membership and that there is a free place
  book(classId: string): Observable<{ message: string; id: string; spaces_left: number }> {
    return this.http.post<{ message: string; id: string; spaces_left: number }>(
      `${this.api}/classes/${classId}/bookings`, {});
  }

  cancelBooking(classId: string, bookingId: string): Observable<unknown> {
    return this.http.delete(`${this.api}/classes/${classId}/bookings/${bookingId}`);
  }
}
