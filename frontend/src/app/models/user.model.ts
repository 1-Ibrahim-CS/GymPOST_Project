export type Role = 'admin' | 'trainer' | 'member';

// the user part of the login response (also inside the JWT)
export interface SessionUser {
  user_id: string;
  username: string;
  role: Role;
  member_id: string | null;
}

// what GET /auth/login returns, kept in localStorage
export interface Session {
  token: string;
  expires_at: string;
  user: SessionUser;
}

export interface Membership {
  plan: string;
  start_date: string;
  end_date: string;
  status: string;
}

// GET /auth/me
export interface CurrentUser {
  _id: string;
  username: string;
  email: string;
  name: string;
  role: Role;
  member_id?: string;
  created_at: string;
  member?: {
    _id: string;
    name: string;
    home_branch_id: string;
    membership: Membership;
    preferred_workout?: string;
    experience_level?: string;
  };
}

// POST /auth/register body
export interface RegisterData {
  username: string;
  email: string;
  password: string;
  name: string;
  gender: string;
  age: number;
  home_branch_id: string;
  plan?: string;
  preferred_workout?: string;
  experience_level?: string;
}
