/**
 * Testimonial media intake for Coach Andre.
 *
 * POST /upload   multipart form ("file") -> stores bytes in KV, returns a URL
 * GET  /f/<key>  streams the stored file back
 * GET  /         health probe
 *
 * Free tier: KV gives 25 MiB per value, 1k writes/day, 100k reads/day.
 */

const MAX_BYTES = 25 * 1024 * 1024; // KV hard ceiling is 25 MiB per value
const ALLOWED = /^(image|audio|video)\//i;

const ALLOWED_ORIGINS = [
  "https://louisbohan.github.io",
  "https://louisbohan.com",
  "https://www.louisbohan.com",
];

function corsHeaders(req) {
  const origin = req.headers.get("Origin") || "";
  const ok =
    ALLOWED_ORIGINS.includes(origin) ||
    /^https?:\/\/localhost(:\d+)?$/.test(origin) ||
    /^https:\/\/[a-z0-9-]+\.workers\.dev$/.test(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : ALLOWED_ORIGINS[0],
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(body, cors, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...cors },
  });
}

function extFor(type, name) {
  const byType = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
  };
  // MIME wins over the filename: Safari records audio/mp4 even when the page
  // hands us a "recording.webm" filename, and a wrong extension makes iOS
  // refuse to play the file.
  if (byType[type]) return byType[type];
  const m = /\.([a-z0-9]{2,5})$/i.exec(name || "");
  return m ? "." + m[1].toLowerCase() : ".bin";
}

/** Strip codec parameters: "audio/mp4;codecs=mp4a.40.2" -> "audio/mp4". */
function normalizeType(t) {
  return (t || "").split(";")[0].trim().toLowerCase();
}

const TYPE_EXT = {
  "image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic", "image/webp": ".webp",
  "image/gif": ".gif", "audio/webm": ".webm", "audio/mp4": ".m4a", "audio/m4a": ".m4a",
  "audio/aac": ".m4a", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
  "audio/ogg": ".ogg", "video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm",
};

/** Repair a filename whose extension disagrees with its real content type. */
function fixFilename(name, type) {
  const want = TYPE_EXT[type];
  if (!want) return name;
  const cur = (/\.([a-z0-9]{2,5})$/i.exec(name || "") || [])[1];
  if (cur && ("." + cur.toLowerCase()) === want) return name;
  return (name || "upload").replace(/\.[a-z0-9]{2,5}$/i, "") + want;
}

async function handleUpload(request, env, cors) {
  const declared = Number(request.headers.get("Content-Length") || 0);
  if (declared > MAX_BYTES) {
    return json({ ok: false, error: `File too large (max ${MAX_BYTES / 1048576} MB).` }, cors, 413);
  }

  let form;
  try {
    form = await request.formData();
  } catch {
    return json({ ok: false, error: "Expected multipart/form-data." }, cors, 400);
  }

  const file = form.get("file");
  if (!file || typeof file === "string") {
    return json({ ok: false, error: "No file field." }, cors, 400);
  }

  const type = normalizeType(file.type) || "application/octet-stream";
  if (!ALLOWED.test(type)) {
    return json({ ok: false, error: `Unsupported type: ${type}` }, cors, 415);
  }

  const buf = await file.arrayBuffer();
  if (buf.byteLength === 0) return json({ ok: false, error: "Empty file." }, cors, 400);
  if (buf.byteLength > MAX_BYTES) {
    return json({ ok: false, error: `File too large (max ${MAX_BYTES / 1048576} MB).` }, cors, 413);
  }

  const day = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(6)))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const key = `${day}-${rand}${extFor(type, file.name)}`;

  await env.testimonial_media.put(key, buf, {
    metadata: {
      contentType: type,
      filename: fixFilename(file.name || "upload", type).slice(0, 200),
      bytes: buf.byteLength,
      received: new Date().toISOString(),
    },
  });

  const origin = new URL(request.url).origin;
  return json(
    {
      ok: true,
      key,
      bytes: buf.byteLength,
      type,
      url: `${origin}/f/${key}`,
    },
    cors
  );
}

async function handleServe(url, env, cors) {
  const key = decodeURIComponent(url.pathname.slice(3));
  if (!key || key.includes("/")) return json({ ok: false, error: "bad key" }, cors, 400);

  const { value, metadata } = await env.testimonial_media.getWithMetadata(key, "arrayBuffer");
  if (!value) return json({ ok: false, error: "not found" }, cors, 404);

  const ct = normalizeType((metadata && metadata.contentType) || "application/octet-stream");
  // Repair the name at serve time too, so files stored before this fix
  // (e.g. AAC audio saved as .webm) still open on iOS.
  const name = fixFilename((metadata && metadata.filename) || key, ct).replace(/"/g, "");

  return new Response(value, {
    headers: {
      "Content-Type": ct,
      "Content-Disposition": 'inline; filename="' + name + '"',
      "Cache-Control": "private, max-age=86400",
      ...cors,
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (url.pathname === "/" || url.pathname === "/healthz") {
      return json({ ok: true, service: "testimonial-upload", max_mb: MAX_BYTES / 1048576 }, cors);
    }
    if (url.pathname === "/upload" && request.method === "POST") {
      return handleUpload(request, env, cors);
    }
    if (url.pathname.startsWith("/f/") && request.method === "GET") {
      return handleServe(url, env, cors);
    }
    return json({ ok: false, error: "not found" }, cors, 404);
  },
};
