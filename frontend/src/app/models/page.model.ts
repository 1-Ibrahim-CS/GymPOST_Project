// every paged list in the API returns { data: [...], pagination: {...} }
export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface Page<T> {
  data: T[];
  pagination: Pagination;
}
