/**
 * Notifications adapter (PLAN.md §7.5, §19.2). Web Push subscription arrives with the access
 * request flow (phase 8); a desktop wrapper can use native notifications instead.
 */
export function notificationsSupported(): boolean {
  return "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
}

export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (!notificationsSupported()) return "denied";
  return Notification.requestPermission();
}
