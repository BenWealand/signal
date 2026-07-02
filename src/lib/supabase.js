import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// Supabase auth is optional. Without configuration the app still runs; auth
// calls resolve to a signed-out state instead of crashing the whole UI.
function createStubClient() {
  const notConfigured = () =>
    Promise.resolve({ data: { user: null, session: null }, error: new Error("Sign-in is not configured for this preview.") });
  return {
    auth: {
      getSession: () => Promise.resolve({ data: { session: null } }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signUp: notConfigured,
      signInWithPassword: notConfigured,
      signOut: () => Promise.resolve({ error: null }),
    },
  };
}

export const supabase = supabaseUrl && supabaseAnonKey
  ? createClient(supabaseUrl, supabaseAnonKey)
  : createStubClient();
