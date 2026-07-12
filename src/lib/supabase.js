import { createClient } from "@supabase/supabase-js";

function env(name) {
  try {
    return import.meta.env?.[name] || "";
  } catch {
    return "";
  }
}

const supabaseUrl = env("VITE_SUPABASE_URL");
const supabaseAnonKey = env("VITE_SUPABASE_ANON_KEY");

// Supabase auth is optional. Without configuration the app still runs; auth
// calls resolve to a signed-out state instead of crashing the whole UI.
function createStubClient() {
  const notConfigured = async () => ({
    data: { user: null, session: null },
    error: new Error("Sign-in is not configured for this preview."),
  });
  return {
    auth: {
      getSession: async () => ({ data: { session: null }, error: null }),
      getUser: async () => ({ data: { user: null }, error: null }),
      onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
      signUp: notConfigured,
      signInWithPassword: notConfigured,
      signOut: async () => ({ error: null }),
      resetPasswordForEmail: notConfigured,
      updateUser: notConfigured,
      resend: notConfigured,
    },
  };
}

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: "pkce",
      },
    })
  : createStubClient();
