// Password rules, the same ones the backend enforces (password_problem in backend/app/main.py).
export const PASSWORD_RULES: { label: string; test: (pw: string) => boolean; problem: string }[] = [
  { label: "8+ characters", test: (pw) => pw.length >= 8, problem: "Use at least 8 characters for your password." },
  { label: "A number", test: (pw) => /[0-9]/.test(pw), problem: "Add a number to your password." },
  { label: "Upper + lower case", test: (pw) => /[A-Z]/.test(pw) && /[a-z]/.test(pw),
    problem: "Use both upper and lower case letters in your password." },
  { label: "A special character, like ! @ # $ or ?", test: (pw) => /[^A-Za-z0-9]/.test(pw), problem: "Add a special character (like ! @ # $ or ?) to your password." },
];

/** the first rule the password misses, as a message, or null if it passes them all */
export function passwordProblem(pw: string): string | null {
  return PASSWORD_RULES.find((r) => !r.test(pw))?.problem ?? null;
}
