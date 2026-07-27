const MAX_POSTS = 5;
const BACKEND_TIMEOUT_MS = 290_000;

function env(name) {
  return String(process.env[name] || "").trim();
}

function suppliedToken(request) {
  const authorization = String(request.headers.authorization || "");
  if (authorization.startsWith("Bearer ")) return authorization.slice(7).trim();
  return String(request.headers["x-vm-token"] || "").trim();
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    response.setHeader("Allow", "POST");
    return response.status(405).json({ detail: "Method not allowed" });
  }

  const expectedToken = env("VM_API_TOKEN");
  if (expectedToken && suppliedToken(request) !== expectedToken) {
    return response.status(401).json({ detail: "Invalid VM API token" });
  }

  if (!Array.isArray(request.body)) {
    return response.status(422).json({ detail: "Body must be a JSON array of {url, text} posts" });
  }
  if (request.body.length < 1 || request.body.length > MAX_POSTS) {
    return response.status(422).json({ detail: `Provide between 1 and ${MAX_POSTS} posts` });
  }
  const valid = request.body.every((post) => (
    post
    && typeof post === "object"
    && !Array.isArray(post)
    && typeof post.url === "string"
    && typeof post.text === "string"
    && ["reason", "angle", "source_assessment"].every(
      (field) => post[field] === undefined || typeof post[field] === "string",
    )
  ));
  if (!valid) {
    return response.status(422).json({
      detail: "Each post must contain string url and text fields; editorial fields must also be strings",
    });
  }

  const apiBase = (env("SIGNAL_API_URL") || env("VITE_SIGNAL_API_URL")).replace(/\/$/, "");
  if (!apiBase) {
    return response.status(503).json({ detail: "Signal backend URL is not configured" });
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), BACKEND_TIMEOUT_MS);
  try {
    const upstream = await fetch(`${apiBase}/vm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request.body),
      signal: controller.signal,
    });
    const contentType = upstream.headers.get("content-type") || "application/json; charset=utf-8";
    const body = await upstream.text();
    response.setHeader("Content-Type", contentType);
    return response.status(upstream.status).send(body);
  } catch (error) {
    const timedOut = error?.name === "AbortError";
    return response.status(timedOut ? 504 : 502).json({
      detail: timedOut ? "Signal backend timed out" : "Could not reach Signal backend",
    });
  } finally {
    clearTimeout(timeout);
  }
}

export const config = {
  maxDuration: 300,
};
