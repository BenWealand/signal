export const SESSION_ID = (() => {
  try {
    let id = sessionStorage.getItem("signal-session");
    if (!id) {
      id = `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      sessionStorage.setItem("signal-session", id);
    }
    return id;
  } catch {
    return `s-${Date.now()}`;
  }
})();
