export interface GymClass {
  _id: string;
  title: string;
  category: string;
  description?: string;
  branch_id: string;
  branch_name: string;
  trainer_id: string;
  trainer_name: string;
  start_time: string;
  duration_min: number;
  level: string;
  capacity: number;
  booked_count: number;
  status: 'scheduled' | 'completed' | 'cancelled';
  spaces_left: number;
}

// one row of GET /members/<id>/bookings
export interface MemberBooking {
  _id: string;
  status: 'booked' | 'cancelled';
  booked_at: string;
  attended: boolean | null;      // null until the trainer records attendance
  class: {
    _id: string;
    title: string;
    category: string;
    branch_id: string;
    branch_name: string;
    trainer_name: string;
    start_time: string;
    duration_min: number;
    status: string;
  };
}
