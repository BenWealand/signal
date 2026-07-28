import assert from "node:assert/strict";
import handler from "../api/article-image.js";

const previousFetch = globalThis.fetch;
const previousApiUrl = process.env.SIGNAL_API_URL;
const previousSupabaseUrl = process.env.VITE_SUPABASE_URL;
const previousSupabaseKey = process.env.VITE_SUPABASE_ANON_KEY;

process.env.SIGNAL_API_URL = "https://signal-api.example";
delete process.env.VITE_SUPABASE_URL;
delete process.env.VITE_SUPABASE_ANON_KEY;

try {
  globalThis.fetch = async (url) => {
    const target = String(url);
    if (target.includes("/generated-articles/write-image-1")) {
      return new Response(JSON.stringify({
        image: { url: "https://images.example.com/article.jpg" },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (target === "https://images.example.com/article.jpg") {
      return new Response(new Uint8Array([255, 216, 255, 217]), {
        status: 200,
        headers: { "content-type": "image/jpeg" },
      });
    }
    return new Response("not found", { status: 404 });
  };

  const response = await handler(new Request(
    "https://signal-mocha-three.vercel.app/api/article-image?id=write-image-1",
  ));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("content-type"), "image/jpeg");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [255, 216, 255, 217]);

  const missing = await handler(new Request(
    "https://signal-mocha-three.vercel.app/api/article-image",
  ));
  assert.equal(missing.status, 400);
} finally {
  globalThis.fetch = previousFetch;
  if (previousApiUrl === undefined) delete process.env.SIGNAL_API_URL;
  else process.env.SIGNAL_API_URL = previousApiUrl;
  if (previousSupabaseUrl === undefined) delete process.env.VITE_SUPABASE_URL;
  else process.env.VITE_SUPABASE_URL = previousSupabaseUrl;
  if (previousSupabaseKey === undefined) delete process.env.VITE_SUPABASE_ANON_KEY;
  else process.env.VITE_SUPABASE_ANON_KEY = previousSupabaseKey;
}

console.log("article image proxy checks passed");
