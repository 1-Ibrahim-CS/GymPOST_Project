export interface Review {
  _id: string;
  member_id: string;
  member_name: string;
  stars: number;
  comment: string;
  created_at: string;
  updated_at?: string;
}

export interface Exercise {
  _id: string;
  title: string;
  description: string | null;
  type: string;
  body_part: string;
  equipment: string;
  level: string;
  review_count: number;
  avg_stars: number | null;
  reviews?: Review[];        // only on GET /exercises/<id>
}

// GET /exercises/filters - each value with how many exercises have it
export interface FilterValue {
  value: string;
  count: number;
}

export interface ExerciseFilters {
  body_part: FilterValue[];
  equipment: FilterValue[];
  level: FilterValue[];
  type: FilterValue[];
}

export interface ReviewData {
  stars: number;
  comment: string;
}
