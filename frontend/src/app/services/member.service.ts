import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { MemberBooking } from '../models/gym-class.model';
import { Page } from '../models/page.model';
import { toParams } from './api-helpers';

export interface BookingQuery {
  when?: 'upcoming' | 'past' | 'all';
  status?: 'booked' | 'cancelled';
  pn?: number;
  ps?: number;
}

@Injectable({ providedIn: 'root' })
export class MemberService {
  private http = inject(HttpClient);
  private api = environment.apiUrl;

  getBookings(memberId: string, query: BookingQuery): Observable<Page<MemberBooking>> {
    return this.http.get<Page<MemberBooking>>(`${this.api}/members/${memberId}/bookings`,
      { params: toParams(query) });
  }
}
