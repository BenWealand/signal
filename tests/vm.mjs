import assert from "node:assert/strict";
import handler from "../api/vm.js";

function mockResponse() {
  return {
    statusCode: 200,
    headers: {},
    payload: null,
    setHeader(name, value) {
      this.headers[name.toLowerCase()] = value;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(value) {
      this.payload = value;
      return this;
    },
    send(value) {
      this.payload = value;
      return this;
    },
  };
}

const previousApiUrl = process.env.SIGNAL_API_URL;
const previousFetch = globalThis.fetch;
process.env.SIGNAL_API_URL = "https://signal-api.example";

try {
  let received = null;
  globalThis.fetch = async (url, options) => {
    received = { url, options };
    return new Response(JSON.stringify({ url: "https://x.com/intent/tweet?text=Draft" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const response = mockResponse();
  await handler({
    method: "POST",
    headers: {},
    body: [{ url: "https://x.com/example/status/1", text: "News update" }],
  }, response);

  assert.equal(response.statusCode, 200);
  assert.equal(received.url, "https://signal-api.example/vm");
  assert.deepEqual(JSON.parse(received.options.body), [
    { url: "https://x.com/example/status/1", text: "News update" },
  ]);
  assert.deepEqual(JSON.parse(response.payload), {
    url: "https://x.com/intent/tweet?text=Draft",
  });

  const invalidResponse = mockResponse();
  await handler({ method: "POST", headers: {}, body: { text: "not an array" } }, invalidResponse);
  assert.equal(invalidResponse.statusCode, 422);
} finally {
  globalThis.fetch = previousFetch;
  if (previousApiUrl === undefined) delete process.env.SIGNAL_API_URL;
  else process.env.SIGNAL_API_URL = previousApiUrl;
}

console.log("VM route checks passed.");
