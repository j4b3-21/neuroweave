const WELCOME_KEY = "neuroweave.tour.welcome";
const COMPLETED_KEY = "neuroweave.tour.completed";

export function welcomeDismissed(): boolean {
  try {
    return window.localStorage.getItem(WELCOME_KEY) === "1";
  } catch {
    return false;
  }
}

export function dismissWelcome(): void {
  try {
    window.localStorage.setItem(WELCOME_KEY, "1");
  } catch {
    /* ignore quota / private mode */
  }
}

export function tourCompleted(): boolean {
  try {
    return window.localStorage.getItem(COMPLETED_KEY) === "1";
  } catch {
    return false;
  }
}

export function markTourCompleted(): void {
  try {
    window.localStorage.setItem(COMPLETED_KEY, "1");
    window.localStorage.setItem(WELCOME_KEY, "1");
  } catch {
    /* ignore */
  }
}
