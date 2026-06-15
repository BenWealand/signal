import { useEffect, useState } from "react";

export function useStoredState(key, initialValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored ? JSON.parse(stored) : initialValue;
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Local persistence is best-effort for reader preferences.
    }
  }, [key, value]);

  return [value, setValue];
}
