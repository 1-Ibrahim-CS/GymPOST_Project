export interface Branch {
  _id: string;
  name: string;
  address: { area: string; city: string; postcode: string };
  location: { type: 'Point'; coordinates: [number, number] };   // [lng, lat]
  opening_hours: { weekdays: string; weekends: string };
  facilities: string[];
  capacity: number;
  phone: string;
  distance_km?: number;      // only from GET /branches/near
}
