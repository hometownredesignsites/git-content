---
name: wix-image-retrieval-diagnostics
description: Diagnose Wix image URL failures in the active Python or Playwright session by separating DNS, transport, HTTP, image-byte, and browser-decode results. Use for retrieval troubleshooting only; it does not build or change website candidates.
---

# Wix Image Retrieval Diagnostics

Determine which retrieval paths in the **active target session** can see, retrieve, or decode a small set of Wix-hosted images. This is a diagnostic skill, not website generation or full visual QA. Keep it independent of `website-poc-generator`; do not edit candidate HTML or its skill.

When ChatGPT Web/search or a signed-in browser is available, it may be used as a separate comparison path to open the source page or display an exact image URL. Record visual/web access separately from Python retrieval. Seeing a photograph in a web result or browser does not prove its raw bytes are available to Python or can be saved for embedding. Claim byte retrieval only when a tool actually returns the bytes to the same session and they pass image validation.

## Inputs and boundaries

- Use the exact image URLs supplied by the user or observed on the named source website. If none are supplied, discover source images using available read-only page tools and choose at most three representative URLs.
- Run diagnostics in the same ChatGPT session and Python environment that reported the failure. Results from Codex, another chat, a local browser, or a downloaded bundle do not establish target-session capability.
- Test HTTPS URLs only. Keep requests limited to the observed Wix image host(s); do not crawl the site's entire media library.
- Use an isolated request context without user cookies or authorization headers. Do not submit forms, change the source site, alter system DNS, install packages, or bypass an environment's network policy.
- Do not use hardcoded CDN IP addresses. Do not disable TLS verification (`ignore_https_errors`, `curl -k`, `--insecure`, or `http.sslVerify=false`).

## Diagnostic sequence

1. Record the current runtime and available methods: Python, Playwright `APIRequestContext`, optional Pillow/browser image decoding, and optional `curl`. Do not infer availability from a different session.
2. For each exact URL, record its sanitized URL and hostname. Probe name resolution once with Python `socket.getaddrinfo` for the default family and IPv4 (`AF_INET`); probe IPv6 (`AF_INET6`) when available. Bound each lookup to a few seconds when the runtime permits, and do not repeat a timed-out lookup. Record returned addresses or the precise exception/timeout. These probes distinguish resolver failure from a later connection failure; they do not prove an HTTP connection works.
3. If Playwright is available, create the request context with supported context options only (for example, `timeout` and `ignore_https_errors=False`); `max_retries` is a request option, not a `new_context` option. Make one bounded GET per selected image with redirects disabled (`max_redirects=0`) and, if the installed version supports it, `max_retries=0`. If `max_retries` is unsupported, omit it because the API default is no network retries; record the version. A `TypeError` during context or request setup means no HTTP request was made and must not be reported as DNS failure. Record status, content type, `Location`, error type/message, and response byte count when present. Follow redirects manually only when each hop is HTTPS and remains on an observed or explicitly approved image host; cap the chain at three hops. If this version cannot stop automatic redirects, do not treat its final response as redirect-validated. Do not repeatedly retry the same failed host.
4. If Playwright is unavailable or its request fails, optionally make one `urllib` request as a separate client comparison, then use curl only under the current-IPv4 condition below. Label every client separately; a result from one client does not imply another client works. If Python Run is a notebook with an active event loop, call the async probe with `await probe()`; do not call `asyncio.run()` inside that loop. Use `asyncio.run()` only in a standalone Python process with no running loop. A runtime/setup exception is not a DNS result.
5. If ordinary DNS returns a current IPv4 address but Playwright's request fails at name resolution, and `curl` is available in this same Python environment, make one comparison request with curl's `--resolve <host>:443:<that-current-ip>`. Keep the original `https://<host>/...` URL so hostname and certificate checks remain active. Do not use a raw-IP URL or a guessed/stale address. If the current runtime has no resolved IP, stop this fallback; report DNS as blocked. Use a DoH resolver only if the target environment explicitly permits it, and report it as a separate resolver path rather than silently overriding DNS.
6. Validate retrieved bytes independently of HTTP status or `Content-Type`: require a successful response, nonempty bounded bytes, a recognized image signature consistent with the MIME type, SHA-256, and decoded nonzero width and height. Prefer Pillow when installed; otherwise use a browser image decode only if a browser actually launches in this session. Record unavailable validation separately; never infer image validity from a URL or page screenshot.
7. Save a compact JSON report and temporary image bytes only when the current session has a writable temporary location. Include timestamp, runtime/tool, exact or safely redacted URL, each DNS family result, request method, redirect chain, HTTP status, MIME/signature result, byte count, SHA-256, decoded dimensions, and the outcome/reason for every step. Do not persist cookies, credentials, or sensitive query values. If file output is unavailable, return the same report inline.

## Interpret results

Use `PASS` only when every selected image was retrieved through Playwright `APIRequestContext` and its image signature, MIME, hash, and decoded dimensions were verified. Use `PASS_FALLBACK` when those checks pass only through an approved same-session alternate transport; this does not establish that a downstream Playwright-only runner can retrieve the images. Use `PARTIAL` when only some selected images pass, `BLOCKED` when DNS or network policy prevents retrieval, and `FAIL` when a response is received but is invalid or cannot be decoded as an image. Keep the per-URL outcomes visible; an overall label never replaces them.

- **DNS blocked:** no usable address from the permitted resolver path. Do not label the URL invalid and do not invent an address.
- **Resolver-path difference:** ordinary/APIRequestContext DNS fails but a current IPv4 answer plus `curl --resolve` succeeds with TLS verification. Report that narrowly as a client/resolver-path difference; it is not proof that Playwright itself can retrieve the image.
- **Connection/TLS blocked:** DNS returned an address, but connection or certificate validation failed. Keep this distinct from DNS failure.
- **HTTP blocked or rejected:** a response arrived but its status or redirect host is unacceptable. Do not treat it as valid image bytes.
- **Image validation failed:** the response was not a valid decodable image or its MIME/signature disagreed.
- **Retrieval verified:** exact bytes were retrieved and their signature, MIME, digest, and decoded dimensions were checked. This establishes asset availability only; it does not establish visual relevance, licensing, crop suitability, or responsive layout quality.

Do not create website candidates, embedded HTML, screenshots, or changes to `website-poc-generator` as part of this diagnostic. Report the evidence and stop. A successful alternate-client fetch may justify a later, separately authorized change to a consumer workflow; it does not silently change that workflow's pass criteria.
