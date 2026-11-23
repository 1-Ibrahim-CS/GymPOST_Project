import { Pipe, PipeTransform } from '@angular/core';

// {{ cls.start_time | timeUntil }} -> "in 45 min", "in 3 h", "in 2 days", "started"
@Pipe({ name: 'timeUntil' })
export class TimeUntilPipe implements PipeTransform {
  transform(value: string | Date | null | undefined, now: Date = new Date()): string {
    if (!value) {
      return '';
    }
    const minutes = Math.round((new Date(value).getTime() - now.getTime()) / 60000);
    if (minutes <= 0) {
      return 'started';
    }
    if (minutes < 60) {
      return `in ${minutes} min`;
    }
    const hours = Math.round(minutes / 60);
    if (hours < 24) {
      return `in ${hours} h`;
    }
    const days = Math.round(hours / 24);
    return days === 1 ? 'in 1 day' : `in ${days} days`;
  }
}
