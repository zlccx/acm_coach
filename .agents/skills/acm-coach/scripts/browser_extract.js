function extractACMResources(mode = "research") {
  // Run with Chrome DevTools evaluate_script on an already opened public page.
  // No cookies, storage, lastCode, user records, CSRF values or full context export.
  const host = location.hostname;
  const origin = location.href;
  const stamp = new Date().toISOString();
  const record = (title, url, kind, extra = {}) => ({
    title, url, source: host, resource_type: kind, topics: [],
    retrieved_at: stamp, verification: "browser_dom_verified",
    raw_source: {url: origin, method: "browser_public_dom"}, ...extra
  });
  const fail = message => ({ok: false, error: message, fallback: "Reload the exact resource URL, inspect the public page, or use web search."});
  if (mode !== "research" && mode !== "strict") return fail("Unknown mode");
  if (mode === "strict" && !(host === "www.luogu.com.cn" && /^\/problem\/[A-Za-z0-9_]+\/?$/.test(location.pathname))) {
    return fail("Strict mode permits only the supported problem statement page");
  }
  if (host === "www.luogu.com.cn") {
    const element = document.querySelector("#lentille-context");
    let data = {};
    try { data = element ? JSON.parse(element.textContent).data : {}; }
    catch { return fail("Luogu context is unavailable"); }
    const path = location.pathname;
    const ident = path.replace(/\/$/, "").split("/").pop();
    if (path.startsWith("/problem/") && ident !== "list") {
      const p = data?.problem;
      if (!p || p.pid !== ident || !p.content) return fail("Problem context missing or stale; reload this URL");
      return {ok: true, resource: record(p.name, location.origin + "/problem/" + p.pid, "problem", {
        problem_id: p.pid, content: p.content, samples: p.samples, limits: p.limits
      })};
    }
    if (mode === "strict") return fail("No supported problem statement");
    if (/^\/training\/\d+\/?$/.test(path)) {
      const t = data?.training;
      if (!t || String(t.id) !== ident || !Array.isArray(t.problems)) return fail("Training context missing or stale");
      return {ok: true, resource: record(t.name, origin, "playlist", {
        id: "luogu-" + t.id, source_url: origin, ordering: "original",
        items: t.problems.map((p, i) => record(p.name, location.origin + "/problem/" + p.pid, "problem", {problem_id: p.pid, position: i + 1}))
      })};
    }
    if (/^\/article\/[A-Za-z0-9]+\/?$/.test(path) && !["mine", "list"].includes(ident)) {
      const a = data?.article;
      if (!a || a.lid !== ident || typeof a.content !== "string") return fail("Article context missing, restricted or stale");
      return {ok: true, resource: record(a.title, origin, "article", {content: a.content, content_complete: a.contentFull === true})};
    }
    const selector = path.startsWith("/problem/") ? 'main a[href*="/problem/"]' : path.startsWith("/training/") ? 'main a[href*="/training/"]' : 'main a[href*="/article/"]';
    const seen = new Set();
    const resources = [];
    for (const a of document.querySelectorAll(selector)) {
      const u = new URL(a.href);
      if (u.hostname !== host || !/^\/(problem|training|article)\/[A-Za-z0-9_]+\/?$/.test(u.pathname) || ["list", "mine", "_new"].includes(u.pathname.split("/").pop()) || !a.innerText.trim() || seen.has(a.href)) continue;
      seen.add(a.href);
      resources.push(record(a.innerText.trim(), a.href, u.pathname.startsWith("/problem/") ? "problem" : u.pathname.startsWith("/training/") ? "playlist" : "article"));
    }
    return resources.length ? {ok: true, resources: resources.slice(0, 100), scope: "visible_page_links_only"} : fail("No public resource links found");
  }
  if (host === "oi-wiki.org") {
    const article = document.querySelector("article");
    if (!article?.querySelector("h1")) return fail("Public OI Wiki article unavailable");
    const resource = record(article.querySelector("h1").innerText.trim(), origin, "tutorial", {content: article.innerText});
    return {ok: true, resource};
  }
  if (host === "www.acwing.com") {
    if (!/^\/activity\/content\/introduction\/\d+\/$/.test(location.pathname) && location.pathname !== "/activity/") {
      return fail("Only /activity/ public catalogue or /activity/content/introduction/ID/ public introduction is supported");
    }
    const title = document.querySelector(".activity_title");
    const preview = document.querySelector(".martor-preview");
    if (title && preview && /^\/activity\/content\/introduction\/\d+\/$/.test(location.pathname)) return {ok: true, resource: record(title.innerText.trim(), origin, "course", {content: preview.innerText, scope: "public_course_introduction"})};
    const links = [...document.querySelectorAll('a[href*="/activity/content/"]')].filter(a => /^\/activity\/content\/\d+\/$/.test(new URL(a.href).pathname));
    const seen = new Set();
    const resources = links.filter(a => a.innerText.trim() && !seen.has(a.href) && seen.add(a.href)).map(a => record(a.innerText.trim(), a.href, "course"));
    return resources.length ? {ok: true, resources, scope: "visible_public_courses"} : fail("No public course metadata; inspect browser search results manually");
  }
  return fail("Unsupported resource host");
}
