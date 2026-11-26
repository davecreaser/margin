// Margin's web page (spec 0004): a client of the same local API as the CLI.
// Manuscript and model text is only ever inserted as text (textContent), never as HTML.
"use strict";

// --- Small helpers -------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const fmt = (n) => Number(n).toLocaleString("en-GB");
const money = (n) => (n === null || n === undefined ? "" : `≈ $${n < 0.1 ? n.toFixed(3) : n.toFixed(2)}`);

class ApiError extends Error {}

async function api(method, path, body) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Margin isn't running: start it with docker compose up -d");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.error || data.detail || `Request failed (${response.status})`);
  return data;
}

// POST that answers with server-sent events; calls onEvent(name, data) for each one.
async function stream(path, body, onEvent) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Margin isn't running: start it with docker compose up -d");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(data.error || `Request failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let name = null;
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (name) onEvent(name, data ? JSON.parse(data) : null);
    }
  }
}

function showError(error) {
  const banner = $("banner");
  banner.replaceChildren(error instanceof Error ? error.message : String(error));
  banner.hidden = false;
  banner.scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function clearError() {
  $("banner").hidden = true;
}

function thinking(text) {
  return el("div", { class: "thinking" }, el("span", { class: "dot" }), text);
}

// --- Views ---------------------------------------------------------------------------

const VIEWS = ["ask", "check", "timeline", "bible", "habits", "progress", "manuscript"];

function setView(name) {
  for (const v of VIEWS) {
    $(`tab-${v}`).setAttribute("aria-selected", String(v === name));
    $(`view-${v}`).hidden = v !== name;
  }
  clearError();
  if (name === "check") loadCheckTabs();
  if (name === "manuscript") loadManuscriptView();
  if (name === "progress") loadProgress();
  if (name === "timeline") loadTimeline();
  if (name === "bible") loadBible();
  if (name === "habits") loadHabits();
  if (name === "ask") $("question").focus();
}

// --- Status --------------------------------------------------------------------------

const state = { status: null, google: null, checkTabsFor: null };

async function refreshStatus() {
  const box = $("status");
  try {
    const [status, google] = await Promise.all([api("GET", "/status"), api("GET", "/google/status")]);
    state.status = status;
    state.google = google;
    const parts = [];
    if (status.passages > 0) {
      parts.push(el("strong", {}, status.manuscript || "Manuscript"));
      parts.push(` · ${fmt(status.chapters)} chapters · ${fmt(status.passages)} passages`);
    } else {
      parts.push("Nothing indexed yet");
    }
    if (!status.api_key) parts.push(" · ", el("span", { class: "warn" }, "No API key"));
    box.replaceChildren(...parts);
    return status;
  } catch (error) {
    box.replaceChildren(el("span", { class: "warn" }, "Not connected"));
    showError(error);
    return null;
  }
}

// --- Passage panel -------------------------------------------------------------------

let panelOpener = null;

function normalise(text) {
  // Mirrors the server's quote matching closely enough to find what to highlight.
  // Returns the normalised string and, for each of its characters, the index in `text`.
  const out = [];
  const map = [];
  let lastSpace = true;
  for (let i = 0; i < text.length; i++) {
    let c = text[i];
    if (c === "_" || c === "*") continue;
    if ("‘’‛′".includes(c)) c = "'";
    else if ("“”„″".includes(c)) c = '"';
    else if ("‐‑‒–—―".includes(c)) c = "-";
    if (/\s/.test(c)) {
      if (lastSpace) continue;
      c = " ";
      lastSpace = true;
    } else {
      lastSpace = false;
    }
    out.push(c.toLowerCase());
    map.push(i);
  }
  return { text: out.join(""), map };
}

function highlightRanges(text, quote) {
  const hay = normalise(text);
  const ranges = [];
  for (const part of quote.split(/\.\.\.|…/)) {
    const needle = normalise(part).text.trim();
    if (needle.split(" ").length < 3) continue;
    const at = hay.text.indexOf(needle);
    if (at >= 0) ranges.push([hay.map[at], hay.map[at + needle.length - 1] + 1]);
  }
  return ranges.sort((a, b) => a[0] - b[0]);
}

function renderPassage(text, quote, exact) {
  const ranges = exact || (quote ? highlightRanges(text, quote) : []);
  const nodes = [];
  const paragraph = /[^\n]+(?:\n(?!\s*\n)[^\n]*)*/g; // runs of lines between blank lines
  let match;
  let first = null;
  while ((match = paragraph.exec(text))) {
    const start = match.index;
    const end = start + match[0].length;
    const p = el("p");
    let cursor = start;
    for (const [a, b] of ranges) {
      const from = Math.max(a, start);
      const to = Math.min(b, end);
      if (from >= to) continue;
      if (from > cursor) p.append(text.slice(cursor, from));
      const mark = el("mark", {}, text.slice(from, to));
      first = first || mark;
      p.append(mark);
      cursor = to;
    }
    if (cursor < end) p.append(text.slice(cursor, end));
    nodes.push(p);
  }
  return { nodes, first };
}

async function openPassage(passageId, quote, opener) {
  panelOpener = opener || document.activeElement;
  const panel = $("panel");
  $("panel-kicker").textContent = "Passage";
  $("panel-title").textContent = "Loading…";
  $("panel-body").replaceChildren();
  panel.hidden = false;
  $("panel-close").focus();
  try {
    const p = await api("POST", "/passage", { id: passageId });
    $("panel-kicker").textContent = p.chapter_title;
    $("panel-title").textContent = p.location;
    const { nodes, first } = renderPassage(p.text, quote);
    $("panel-body").replaceChildren(...nodes);
    if (first) first.scrollIntoView({ block: "center" });
  } catch (error) {
    $("panel-title").textContent = "Couldn't load the passage";
    $("panel-body").replaceChildren(el("p", {}, error.message));
  }
}

function closePanel() {
  $("panel").hidden = true;
  if (panelOpener && panelOpener.focus) panelOpener.focus();
}

// --- Ask -----------------------------------------------------------------------------

async function ask(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question) return;
  clearError();
  const answer = $("answer");
  const button = $("ask-button");
  button.disabled = true;
  answer.replaceChildren(thinking("Reading the manuscript…"));

  const body = el("div", { class: "prose" });
  const citations = el("ol", { class: "citations", "aria-label": "Citations" });
  const byNumber = new Map();
  let started = false;

  const start = () => {
    if (!started) {
      answer.replaceChildren(body);
      started = true;
    }
  };

  try {
    await stream("/ask", { question }, (name, data) => {
      if (name === "answer_delta") {
        start();
        const p = el("p", { class: "statement" }, data.text);
        for (const n of data.citations) {
          p.append(
            el(
              "button",
              {
                class: "cite",
                "aria-label": `Citation ${n}`,
                onclick: (e) => {
                  const c = byNumber.get(n);
                  if (c) openPassage(c.passage_id, c.quote, e.currentTarget);
                },
              },
              String(n),
            ),
          );
        }
        body.append(p);
      } else if (name === "citation") {
        byNumber.set(data.n, data);
        citations.append(
          el(
            "li",
            {},
            el(
              "button",
              { onclick: (e) => openPassage(data.passage_id, data.quote, e.currentTarget) },
              el("span", { class: "n" }, `[${data.n}]`),
              el("span", { class: "loc" }, data.location),
              el("span", { class: "quote" }, data.quote),
            ),
          ),
        );
      } else if (name === "done") {
        start();
        if (data.outcome !== "answer") {
          for (const p of body.querySelectorAll(".statement")) p.classList.add("plain-answer");
        }
        if (citations.childElementCount) answer.append(citations);
        if (data.closest && data.closest.length) {
          const list = el("ol", { class: "citations" });
          for (const c of data.closest) {
            list.append(
              el(
                "li",
                {},
                el(
                  "button",
                  { onclick: (e) => openPassage(c.passage_id, null, e.currentTarget) },
                  el("span", { class: "n" }, "·"),
                  el("span", { class: "loc" }, c.location),
                  el("span", { class: "quote" }, c.snippet),
                ),
              ),
            );
          }
          answer.append(el("div", { class: "closest" }, el("h3", {}, "Closest passages"), list));
        }
        answer.append(
          el(
            "div",
            { class: "meta" },
            `${data.model} · ${fmt(data.input_tokens)} in / ${fmt(data.output_tokens)} out ${money(data.cost)}`,
          ),
        );
      }
    });
  } catch (error) {
    answer.replaceChildren();
    showError(error);
  } finally {
    button.disabled = false;
  }
}

// --- Check ---------------------------------------------------------------------------

function checkSource() {
  return document.querySelector('input[name="check-source"]:checked').value;
}

function syncCheckSource() {
  const tab = checkSource() === "tab";
  $("check-tab-fields").hidden = !tab;
  $("check-paste-fields").hidden = tab;
  $("check-plan").hidden = true;
}

async function loadCheckTabs() {
  const google = state.google || (await api("GET", "/google/status").catch(() => null));
  const select = $("check-tab");
  const hint = $("check-tab-hint");
  const current = google && google.current;
  if (!current || !google.signed_in) {
    select.replaceChildren(el("option", { value: "" }, "No Google Doc indexed"));
    select.disabled = true;
    hint.textContent = current
      ? "Sign in to Google on the Manuscript page to check a tab, or paste the text."
      : "Index a Google Doc on the Manuscript page to check one of its tabs, or paste the text.";
    if (checkSource() === "tab") {
      document.querySelector('input[name="check-source"][value="paste"]').checked = true;
      syncCheckSource();
    }
    return;
  }
  if (state.checkTabsFor === current.doc && select.options.length > 1) return;
  select.disabled = true;
  select.replaceChildren(el("option", { value: "" }, "Loading tabs…"));
  try {
    const listing = await api("POST", "/google/tabs", { doc: current.doc });
    const tabs = listing.tabs.filter((t) => t.words > 0 && !t.excluded);
    const options = tabs.map((t) => el("option", { value: t.title }, `${t.title}  (${fmt(t.words)} words)`));
    select.replaceChildren(...options);
    select.disabled = false;
    // Default to the newest chapter with real text, not a placeholder tab at the end.
    let pick = -1;
    tabs.forEach((t, i) => {
      if (t.words >= 200) pick = i;
    });
    if (options.length) select.selectedIndex = pick >= 0 ? pick : options.length - 1;
    hint.textContent = `From “${listing.title}”. The tab is read fresh from Google Docs.`;
    state.checkTabsFor = current.doc;
  } catch (error) {
    select.replaceChildren(el("option", { value: "" }, "Couldn't load tabs"));
    hint.textContent = error.message;
  }
}

async function estimate(event) {
  event.preventDefault();
  clearError();
  const plan = $("check-plan");
  const results = $("check-results");
  results.replaceChildren();
  const body =
    checkSource() === "tab"
      ? { tab: $("check-tab").value }
      : { title: $("check-title").value, text: $("check-text").value };
  if (checkSource() === "tab" && !body.tab) return showError("Choose a tab to check.");
  if (checkSource() === "paste" && !body.text.trim()) return showError("Paste the chapter's text first.");
  const button = $("estimate-button");
  button.disabled = true;
  try {
    const e = await api("POST", "/check/estimate", body);
    const status = state.status || (await refreshStatus());
    const replaces = Array.isArray(e.replaces) ? e.replaces : e.replaces ? [e.replaces] : [];
    const titles = new Map((status.chapter_list || []).map((c) => [c.number, c.title]));
    const named = replaces.map((n) => titles.get(n) || `chapter ${n}`).join(", ");
    const against = replaces.length
      ? `the rest of ${status.manuscript}, leaving out its indexed version (${named})`
      : `${status.manuscript}: ${fmt(status.chapters)} chapters, ${fmt(status.passages)} passages`;
    const run = el("button", { class: "primary" }, `Check (${money(e.worst_case)} at most)`);
    run.addEventListener("click", () => runCheck(e, replaces, run));
    plan.replaceChildren(
      el("p", {}, `Checking “${e.title}” (${fmt(e.words)} words) against ${against}.`),
      el(
        "p",
        { class: "hint" },
        `Worst case ${money(e.worst_case)}: up to ${e.claim_cap} claims, each judged by ${e.models.join(" and ")}. A typical chapter costs much less.`,
      ),
      run,
    );
    plan.hidden = false;
    run.focus();
  } catch (error) {
    plan.hidden = true;
    showError(error);
  } finally {
    button.disabled = false;
  }
}

function side(label, quote, onOpen) {
  return el(
    "div",
    { class: "side" },
    onOpen
      ? el("button", { class: "loc", onclick: onOpen }, label)
      : el("span", { class: "loc" }, label),
    el("span", { class: "quote" }, quote),
  );
}

function findingCard(f, kind) {
  const sides = [side(`This chapter, ¶ ${f.paragraph}`, f.quote)];
  for (const c of f.citations) {
    sides.push(side(c.location, c.quote, (e) => openPassage(c.passage_id, c.quote, e.currentTarget)));
  }
  return el(
    "article",
    { class: `finding ${kind}` },
    el("p", { class: "explain" }, f.explanation || f.claim),
    el("div", { class: "sides" }, sides),
  );
}

async function runCheck(plan, replaces, button) {
  clearError();
  button.disabled = true;
  const results = $("check-results");
  const progressText = el("span", {}, "Finding claims…");
  const fill = el("span");
  const progress = el("div", { class: "progress" }, progressText, el("div", { class: "bar" }, fill));
  results.replaceChildren(progress);

  let contradictionsBox = null;
  const listed = { consistent: [], new: [], not_checked: [] };
  let total = 0;
  let judged = 0;

  try {
    await stream(
      "/check",
      {
        title: plan.title,
        paragraphs: plan.paragraphs,
        replaces: replaces.length ? replaces : null,
      },
      (name, data) => {
        if (name === "claim_count") {
          total = data.claims;
          progressText.textContent = `Checking ${total} claims${data.capped ? ` (the cap of ${data.cap})` : ""}…`;
        } else if (name === "finding") {
          judged += 1;
          fill.style.width = `${total ? Math.round((judged / total) * 100) : 100}%`;
          progressText.textContent = `Checked ${judged} of ${total} claims…`;
          if (data.verdict === "contradicts") {
            if (!contradictionsBox) {
              contradictionsBox = el("div");
              results.append(
                el("div", { class: "section-title" }, el("h3", {}, "Contradicts")),
                contradictionsBox,
              );
            }
            contradictionsBox.append(findingCard(data, ""));
          } else {
            listed[data.verdict].push(data);
          }
        } else if (name === "error") {
          showError(data.message);
        } else if (name === "done") {
          progress.remove();
          const c = data.counts;
          if (!contradictionsBox) results.append(el("div", { class: "clean" }, "No contradictions found."));
          results.append(
            el(
              "p",
              { class: "counts" },
              el("strong", {}, `${c.contradicts} contradictions`),
              ` · ${c.consistent} consistent · ${c.new} new`,
            ),
          );
          const byN = (a, b) => a.n - b.n;
          if (listed.consistent.length) {
            results.append(
              el(
                "details",
                {},
                el("summary", {}, `Consistent with the manuscript (${listed.consistent.length})`),
                listed.consistent.sort(byN).map((f) => findingCard(f, "ok")),
              ),
            );
          }
          if (listed.new.length) {
            results.append(
              el(
                "details",
                {},
                el("summary", {}, `New: the manuscript doesn't settle these (${listed.new.length})`),
                listed.new.sort(byN).map((f) => findingCard(f, "new")),
              ),
            );
          }
          if (listed.not_checked.length) {
            results.append(
              el(
                "details",
                { open: true },
                el("summary", {}, `Not checked: the model's reply failed twice (${listed.not_checked.length})`),
                listed.not_checked.sort(byN).map((f) => findingCard(f, "new")),
              ),
            );
          }
          results.append(
            el(
              "div",
              { class: "meta" },
              `${data.models.join(", ")} · ${data.calls} calls · ${fmt(data.input_tokens)} in / ${fmt(data.output_tokens)} out ${money(data.cost)}`,
            ),
          );
        }
      },
    );
  } catch (error) {
    progress.remove();
    showError(error);
  } finally {
    button.disabled = false;
  }
}

// --- Story notes: Timeline and Bible --------------------------------------------------

// Both views show one saved set of story notes, made by one regenerate (spec 0008).
const notesState = { data: null };
const BANDS = { before: "Before the story", story: "", after: "After" };

async function loadNotes() {
  try {
    notesState.data = await api("GET", "/timeline");
    for (const view of ["timeline", "bible"]) renderNotesHead(view);
    renderTimeline();
    renderBible();
  } catch (error) {
    showError(error);
  }
}

const loadTimeline = loadNotes;
const loadBible = loadNotes;

function renderNotesHead(view) {
  const g = notesState.data;
  const t = g.timeline;
  $(`${view}-name`).textContent = g.manuscript;
  $(`${view}-tools`).hidden = !t;
  $(`${view}-regenerate`).textContent = t ? "Regenerate…" : "Make the timeline and bible…";
  if (!t) {
    $(`${view}-meta`).textContent =
      "Margin reads every chapter once and makes two things: the story's scenes in story order, and a bible of its characters and places. Everything is quoted from your text. It runs only when you ask, after showing the cost.";
  } else if (view === "timeline") {
    const cards = t.periods.reduce((n, p) => n + p.cards.length, 0);
    $("timeline-meta").textContent =
      `${fmt(cards)} moments in ${t.periods.length} periods · ${fmt(t.unplaced.length)} not placed · made ${day(t.made_at)} · ${t.models.join(" + ")} · ${money(t.cost)}`;
  } else {
    $("bible-meta").textContent =
      `${fmt(t.bible.characters.length)} characters · ${fmt(t.bible.places.length)} places · made ${day(t.made_at)} · ${t.models.join(" + ")} · ${money(t.cost)}`;
  }
  const stale = $(`${view}-stale`);
  stale.hidden = !g.changed;
  if (g.changed) {
    stale.textContent = `${g.changed} chapter${g.changed > 1 ? "s" : ""} changed since this was made. Regenerate re-reads only those.`;
  }
}

function quoteButton(passageId, quote) {
  return passageId
    ? el("button", { class: "tl-quote quote", onclick: (ev) => openPassage(passageId, quote, ev.currentTarget) }, quote)
    : el("span", { class: "tl-quote quote" }, quote);
}

function cardMatches(card, q) {
  return !q || card.tellings.some((e) => `${e.text} ${e.quote} ${e.chapter_label}`.toLowerCase().includes(q));
}

function timelineCard(card, chip) {
  const [first, ...more] = card.tellings;
  const node = el(
    "article",
    { class: `tl-card${card.uncertain ? " uncertain" : ""}` },
    el(
      "div",
      { class: "tl-top" },
      el("span", { class: "chip" }, chip),
      more.length ? el("span", { class: "hint" }, `also told in ${more.map((e) => e.chapter_label).join(", ")}`) : null,
      card.uncertain ? el("span", { class: "hint" }, "uncertain") : null,
    ),
    el("p", { class: "tl-text" }, first.text),
    quoteButton(first.passage_id, first.quote),
  );
  for (const e of more) {
    node.append(el("p", { class: "tl-telling" }, el("span", { class: "loc" }, e.chapter_label), quoteButton(e.passage_id, e.quote)));
  }
  if (card.basis && card.basis.length) {
    node.append(
      el(
        "p",
        { class: "tl-basis" },
        "placed by ",
        card.basis.flatMap((b, i) => [i ? " · " : "", el("q", {}, b.time), ` (${b.chapter_label})`]),
      ),
    );
  }
  return node;
}

function renderTimeline() {
  const g = notesState.data;
  const body = $("timeline-body");
  if (!g || !g.timeline) {
    body.replaceChildren();
    return;
  }
  const t = g.timeline;
  const q = $("timeline-filter").value.trim().toLowerCase();
  const order = document.querySelector('input[name="timeline-order"]:checked').value;
  const loose = t.unplaced.map((e) => ({ tellings: [e], basis: [], uncertain: false }));
  const nodes = [];
  if (order === "story") {
    let band = null;
    for (const period of t.periods) {
      const cards = period.cards.filter((c) => cardMatches(c, q)).map((c) => timelineCard(c, c.tellings[0].chapter_label));
      if (!cards.length) continue;
      if (period.band !== band && BANDS[period.band]) nodes.push(el("h2", { class: "tl-band" }, BANDS[period.band]));
      band = period.band;
      nodes.push(el("section", { class: `tl-period ${period.band}` }, el("h3", {}, period.label), cards));
    }
    const shown = loose.filter((c) => cardMatches(c, q));
    if (shown.length) {
      nodes.push(
        el(
          "section",
          { class: "tl-period unplaced" },
          el("h3", {}, "Not placed"),
          el("p", { class: "hint" }, "The text gives no time for these, so Margin doesn't guess."),
          shown.map((c) => timelineCard(c, c.tellings[0].chapter_label)),
        ),
      );
    }
  } else {
    // Reading order: every telling under its own chapter, chipped with its story period.
    const periodOf = new Map();
    t.periods.forEach((p) => p.cards.forEach((c) => c.tellings.forEach((e) => periodOf.set(e.id, p.label))));
    const all = [...t.periods.flatMap((p) => p.cards), ...loose]
      .flatMap((c) => c.tellings.map((e) => ({ ...c, tellings: [e] })))
      .sort((a, b) => a.tellings[0].chapter - b.tellings[0].chapter || a.tellings[0].paragraph - b.tellings[0].paragraph);
    const byChapter = new Map();
    for (const c of all.filter((x) => cardMatches(x, q))) {
      const n = c.tellings[0].chapter;
      if (!byChapter.has(n)) byChapter.set(n, []);
      byChapter.get(n).push(c);
    }
    for (const cards of byChapter.values()) {
      nodes.push(
        el(
          "section",
          { class: "tl-period reading" },
          el("h3", {}, cards[0].tellings[0].chapter_label),
          cards.map((c) => timelineCard(c, periodOf.get(c.tellings[0].id) || "Not placed")),
        ),
      );
    }
  }
  body.replaceChildren(
    nodes.length ? el("div", { class: `tl ${order}` }, nodes) : el("p", { class: "hint" }, "No scenes match the filter."),
  );
}

const FACTS_SHOWN = 6;

// "Chapters 1–4, 7" when the chapters are numbered plainly; their own names otherwise.
function chapterList(chapters) {
  if (!chapters.length) return "Named in no chapter's text";
  const nums = chapters.map((c) => /^Chapter (\d+)$/.exec(c.label)?.[1]).map(Number);
  if (nums.some((n) => !n)) return `In ${chapters.map((c) => c.label).join(", ")}`;
  const runs = [];
  for (const n of nums) {
    const last = runs[runs.length - 1];
    if (last && n === last[1] + 1) last[1] = n;
    else runs.push([n, n]);
  }
  const text = runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ");
  return `${nums.length > 1 ? "Chapters" : "Chapter"} ${text}`;
}

function renderBible() {
  const g = notesState.data;
  const body = $("bible-body");
  if (!g || !g.timeline) {
    body.replaceChildren();
    return;
  }
  const b = g.timeline.bible;
  const failed = b.error
    ? el("p", { class: "stale" }, "Grouping the names failed, so each name is shown on its own. Regenerate tries again; chapters already read cost nothing.")
    : null;
  const kind = document.querySelector('input[name="bible-kind"]:checked').value;
  const q = $("bible-filter").value.trim().toLowerCase();
  const entries = (kind === "characters" ? b.characters : b.places).filter(
    (e) => !q || [...e.names, ...e.facts.map((f) => `${f.text} ${f.quote}`)].join(" ").toLowerCase().includes(q),
  );
  const cards = entries.map((e) => {
    const others = e.names.filter((n) => n !== e.name);
    const list = el("ul", { class: "facts" });
    const showFacts = (n) =>
      list.replaceChildren(
        ...e.facts.slice(0, n).map((f) =>
          el("li", {}, el("span", { class: "fact" }, f.text), el("span", { class: "chip" }, f.chapter_label), quoteButton(f.passage_id, f.quote)),
        ),
      );
    showFacts(q ? e.facts.length : FACTS_SHOWN);
    const more =
      !q && e.facts.length > FACTS_SHOWN
        ? el("button", { class: "linkish", onclick: (ev) => { showFacts(e.facts.length); ev.currentTarget.remove(); } }, `Show all ${e.facts.length} facts`)
        : null;
    return el(
      "article",
      { class: "bible-entry" },
      el("h3", {}, e.name),
      el("p", { class: "hint" }, [others.length ? `Also ${others.join(", ")} · ` : "", chapterList(e.chapters)].join("")),
      e.facts.length ? list : el("p", { class: "hint" }, "Named, but the text states no facts about them yet."),
      more,
    );
  });
  body.replaceChildren(
    ...(failed ? [failed] : []),
    ...(cards.length ? cards : [el("p", { class: "hint" }, q ? "Nothing matches the filter." : "None found.")]),
  );
}

async function planNotes(view) {
  clearError();
  const plan = $(`${view}-plan`);
  try {
    const e = await api("POST", "/timeline/estimate");
    const made = notesState.data?.timeline;
    const n = e.changed.length;
    const what = !made
      ? `Reading all ${fmt(e.chapters)} chapters`
      : n
        ? `Re-reading ${n} changed chapter${n > 1 ? "s" : ""} (${e.changed.map((c) => c.title).join(", ")})`
        : "No chapter changed: only placing and grouping again";
    const run = el("button", { class: "primary" }, `${made ? "Regenerate" : "Make them"} (${money(e.worst_case)} at most)`);
    const cancel = el("button", { class: "secondary", onclick: () => (plan.hidden = true) }, "Cancel");
    run.addEventListener("click", () => regenerateNotes(view, run, e.chapters));
    plan.replaceChildren(
      el("p", {}, `${what}, then placing up to ${fmt(e.events_max)} scenes in story order and grouping the names into the bible.`),
      el("p", { class: "hint" }, `Worst case ${money(e.worst_case)} with ${e.models.join(", ")}. Unchanged chapters are never read again.`),
      el("div", { class: "row" }, run, cancel),
    );
    plan.hidden = false;
    run.focus();
  } catch (error) {
    showError(error);
  }
}

async function regenerateNotes(view, button, total) {
  button.disabled = true;
  for (const v of ["timeline", "bible"]) $(`${v}-regenerate`).disabled = true;
  const plan = $(`${view}-plan`);
  const text = el("span", {}, "Reading chapters…");
  const fill = el("span");
  plan.replaceChildren(el("div", { class: "progress" }, text, el("div", { class: "bar" }, fill)));
  let read = 0;
  try {
    await stream("/timeline/regenerate", {}, (name, data) => {
      if (name === "chapter_done") {
        read += 1;
        text.textContent = `Read ${data.title}${data.cached ? " (unchanged)" : ` · ${data.events} scenes`}`;
        if (total) fill.style.width = `${Math.min(90, (90 * read) / total)}%`;
      } else if (name === "placing") {
        text.textContent = `Placing ${fmt(data.events)} scenes in story order…`;
        fill.style.width = "93%";
      } else if (name === "bible") {
        text.textContent = `Grouping ${fmt(data.names)} names into the bible…`;
        fill.style.width = "97%";
      } else if (name === "error") {
        throw new ApiError(data.message);
      }
    });
    plan.hidden = true;
    await loadNotes();
  } catch (error) {
    plan.hidden = true;
    showError(error);
  } finally {
    for (const v of ["timeline", "bible"]) $(`${v}-regenerate`).disabled = false;
  }
}

// --- Progress ------------------------------------------------------------------------

const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

const day = (iso) => new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const signed = (n) => `${n >= 0 ? "+" : "−"}${fmt(Math.abs(n))}`;

async function loadProgress() {
  try {
    renderProgress(await api("GET", "/progress"));
  } catch (error) {
    showError(error);
  }
}

function renderProgress(p) {
  $("progress-name").textContent = p.manuscript;
  $("progress-total").textContent = fmt(p.total);
  $("progress-of").textContent = p.target ? ` of ${fmt(p.target)} words · ${Math.round(p.percent)}%` : " words";
  const bar = $("target-bar");
  bar.hidden = !p.target;
  if (p.target) bar.firstElementChild.style.width = `${Math.min(100, p.percent)}%`;
  if (document.activeElement !== $("target-input")) $("target-input").value = p.target || "";

  const stats = [
    el("div", {}, el("strong", {}, `${p.drafted} of ${p.chapters.length}`), el("span", {}, "chapters drafted")),
    el("div", {}, el("strong", {}, String(p.stubs)), el("span", {}, `stubs, under ${fmt(p.stub_words)} words`)),
  ];
  if (p.since_last) {
    stats.push(el("div", {}, el("strong", {}, signed(p.since_last.words)), el("span", {}, `words since ${day(p.since_last.since)}`)));
  }
  if (p.last_7_days !== null) {
    stats.push(el("div", {}, el("strong", {}, signed(p.last_7_days)), el("span", {}, "in the last 7 days")));
  }
  $("progress-stats").replaceChildren(...stats);
  renderGrowth(p.history);
  renderLengths(p);
}

function renderGrowth(history) {
  const box = $("growth");
  if (history.length < 2) {
    box.replaceChildren(el("p", { class: "hint" }, "Progress over time appears once you've ingested on two different days."));
    return;
  }
  const W = 720, H = 180, L = 52, R = 12, T = 12, B = 28;
  const times = history.map((h) => new Date(h.at).getTime());
  const t0 = times[0], t1 = Math.max(times[times.length - 1], t0 + 1);
  // Fit the axis to the numbers, not to zero: a week's words on a whole book's scale is flat.
  const totals = history.map((h) => h.total);
  const span = Math.max(Math.max(...totals) - Math.min(...totals), 1000);
  const step = 10 ** Math.floor(Math.log10(span)) / 2;
  const lo = Math.max(0, Math.floor((Math.min(...totals) - span * 0.15) / step) * step);
  const hi = Math.ceil((Math.max(...totals) + span * 0.15) / step) * step;
  const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const pts = history.map((h, i) => [x(times[i]), y(h.total)]);
  const line = pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
  const area = `${line}L${pts[pts.length - 1][0].toFixed(1)},${H - B}L${pts[0][0].toFixed(1)},${H - B}Z`;
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "growth", role: "img", "aria-label": "Total words over time" });
  for (const f of [0, 0.5, 1]) {
    const v = Math.round(lo + (hi - lo) * f);
    chart.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
    chart.append(svg("text", { x: L - 8, y: y(v) + 4, class: "axis", "text-anchor": "end" }, fmt(v)));
  }
  chart.append(svg("path", { d: area, class: "area" }), svg("path", { d: line, class: "line" }));
  chart.append(svg("text", { x: L, y: H - 8, class: "axis" }, day(history[0].at)));
  chart.append(svg("text", { x: W - R, y: H - 8, class: "axis", "text-anchor": "end" }, day(history[history.length - 1].at)));
  history.forEach((h, i) => {
    chart.append(
      svg("circle", { cx: pts[i][0], cy: pts[i][1], r: 4, class: "pt" }, svg("title", {}, `${day(h.at)}: ${fmt(h.total)} words`)),
    );
  });
  box.replaceChildren(chart);
}

function renderLengths(p) {
  const box = $("lengths");
  const max = Math.max(1, ...p.chapters.map((c) => c.words));
  $("lengths-hint").textContent = p.median
    ? `In reading order. The dashed line marks the median drafted chapter, ${fmt(Math.round(p.median))} words. Stubs are greyed.`
    : "In reading order. Stubs are greyed.";
  const rows = p.chapters.map((c) => {
    const tip = c.of_median !== null && c.status === "drafted" ? `${fmt(c.words)} words · ${c.of_median}% of the median` : `${fmt(c.words)} words · stub`;
    return el(
      "div",
      { class: `len-row ${c.status}`, title: tip },
      el("span", { class: "len-title" }, c.title),
      el(
        "span",
        { class: "len-track" },
        el("span", { class: "len-fill", style: `width:${Math.max(0.5, (100 * c.words) / max)}%` }),
      ),
      el("span", { class: "len-words" }, fmt(c.words)),
    );
  });
  const chart = el("div", { class: "len-chart" }, rows);
  if (p.median) {
    chart.style.setProperty("--median", `${(100 * p.median) / max}%`);
    chart.classList.add("has-median");
  }
  box.replaceChildren(chart);
}

async function saveTarget(event) {
  event.preventDefault();
  clearError();
  const value = parseInt($("target-input").value, 10);
  try {
    renderProgress(await api("POST", "/progress/target", { target: Number.isFinite(value) && value > 0 ? value : null }));
  } catch (error) {
    showError(error);
  }
}

// --- Manuscript ----------------------------------------------------------------------

function globEscape(name) {
  return name.replace(/[[\]*?]/g, (c) => `[${c}]`);
}

async function loadManuscriptView() {
  const status = await refreshStatus();
  renderIndexed(status);
  renderGoogleState();
  loadFiles();
}

function renderIndexed(status) {
  const box = $("indexed");
  if (!status || status.passages === 0) {
    box.replaceChildren(
      el("h3", {}, "Nothing is indexed yet"),
      el("p", { class: "hint" }, "Index a Google Doc, a folder of chapters, or the demo novel below to start asking."),
    );
    return;
  }
  box.replaceChildren(
    el("div", { class: "panel-kicker" }, "Indexed now"),
    el("div", { class: "indexed-title" }, status.manuscript),
    el("div", { class: "hint" }, `${fmt(status.chapters)} chapters · ${fmt(status.passages)} passages`),
    el(
      "ul",
      { class: "chapters" },
      (status.chapter_list || []).map((c) =>
        el("li", {}, el("span", {}, `${c.number}. ${c.title}`), el("span", { class: "w" }, fmt(c.words))),
      ),
    ),
  );
}

function renderGoogleState() {
  const g = state.google;
  const box = $("google-state");
  const form = $("gdoc-form");
  if (!g || !g.configured) {
    box.replaceChildren(
      "Not set up. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to .env, then run docker compose up -d --force-recreate margin. The README's Google Docs section walks through it.",
    );
    form.hidden = true;
    return;
  }
  form.hidden = !g.signed_in;
  if (!g.signed_in) {
    box.replaceChildren(
      "Margin needs read-only access to your Google Docs. ",
      el("button", { class: "primary", onclick: signIn }, "Sign in to Google"),
    );
    return;
  }
  box.replaceChildren(
    "Signed in to Google, read-only. ",
    el("button", { class: "linkish", onclick: signOut }, "Sign out"),
  );
  if (g.current && !$("gdoc-link").value) {
    $("gdoc-link").value = `https://docs.google.com/document/d/${g.current.doc}/edit`;
  }
}

async function signIn() {
  clearError();
  try {
    const before = state.google ? state.google.signed_in_at : null;
    const { url } = await api("GET", "/google/login");
    window.open(url, "_blank", "noopener");
    $("google-state").replaceChildren(thinking("Waiting for you to allow access in the new tab…"));
    for (let i = 0; i < 200; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const g = await api("GET", "/google/status");
      if (g.signed_in_at && g.signed_in_at !== before) {
        state.google = g;
        renderGoogleState();
        return;
      }
    }
    showError("Timed out waiting for Google: try signing in again.");
    renderGoogleState();
  } catch (error) {
    showError(error);
  }
}

async function signOut() {
  try {
    const r = await api("POST", "/google/logout");
    if (!r.revoked) {
      showError("Signed out here, but Google didn't confirm: remove Margin at myaccount.google.com/permissions.");
    }
    state.google = await api("GET", "/google/status");
    renderGoogleState();
    $("gdoc-tabs").hidden = true;
  } catch (error) {
    showError(error);
  }
}

async function showTabs(event) {
  event.preventDefault();
  clearError();
  const link = $("gdoc-link").value.trim();
  if (!link) return;
  const list = $("tab-list");
  list.replaceChildren(el("li", { class: "loading" }, thinking("Reading the document's tabs…")));
  $("gdoc-tabs").hidden = false;
  try {
    const listing = await api("POST", "/google/tabs", { doc: link });
    const names = new Set(listing.tabs.map((t) => globEscape(t.title)));
    $("gdoc-patterns").value = listing.exclude.filter((p) => !names.has(p)).join(", ");
    list.replaceChildren(
      ...listing.tabs.map((t) => {
        const empty = t.words === 0;
        const box = el("input", { type: "checkbox", checked: !t.excluded && !empty, disabled: empty });
        const item = el(
          "li",
          { class: box.checked ? "" : "off" },
          el(
            "label",
            {},
            box,
            el("span", { class: "t" }, t.title),
            el("span", { class: "w" }, empty ? "empty" : `${fmt(t.words)} words`),
          ),
        );
        item.dataset.title = t.title;
        box.addEventListener("change", () => {
          item.className = box.checked ? "" : "off";
          countTabs();
        });
        return item;
      }),
    );
    countTabs();
  } catch (error) {
    $("gdoc-tabs").hidden = true;
    showError(error);
  }
}

function countTabs() {
  const ticked = [...$("tab-list").querySelectorAll("input:checked")].length;
  $("gdoc-ingest").textContent = `Index ${ticked} tab${ticked === 1 ? "" : "s"}`;
  $("gdoc-ingest").disabled = ticked === 0;
}

async function ingest(body, button) {
  clearError();
  const result = $("ingest-result");
  const buttons = document.querySelectorAll("#view-manuscript button");
  buttons.forEach((b) => (b.disabled = true));
  result.replaceChildren(thinking("Reading and indexing… a whole book takes a minute the first time."));
  try {
    const r = await api("POST", "/ingest", body);
    const parts = [];
    if (r.unchanged) {
      parts.push(el("strong", {}, "No changes"), ` since the last ingest of “${r.manuscript}”.`);
    } else {
      const embedded = r.passages_embedded === null || r.passages_embedded === undefined ? "" : ` (${fmt(r.passages_embedded)} newly embedded)`;
      parts.push(
        el("strong", {}, "Indexed"),
        ` ${r.label}: ${fmt(r.chapters.length)} chapters, ${fmt(r.words)} words, ${fmt(r.passages)} passages${embedded}, in ${Math.max(1, Math.round(r.seconds))}s.`,
      );
    }
    if (r.tabs_excluded && r.tabs_excluded.length) parts.push(` Left out: ${r.tabs_excluded.join(", ")}.`);
    result.replaceChildren(el("div", { class: "done-note" }, parts));
    state.checkTabsFor = null;
    state.google = await api("GET", "/google/status").catch(() => state.google);
    renderIndexed(await refreshStatus());
  } catch (error) {
    result.replaceChildren();
    showError(error);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
    if (!$("gdoc-tabs").hidden) countTabs();
  }
}

function ingestGoogle() {
  const unticked = [...$("tab-list").querySelectorAll("li")]
    .filter((li) => {
      const box = li.querySelector("input");
      return box && !box.checked && !box.disabled;
    })
    .map((li) => globEscape(li.dataset.title));
  const typed = $("gdoc-patterns").value.split(",").map((p) => p.trim()).filter(Boolean);
  ingest({ google_doc: $("gdoc-link").value.trim(), exclude: [...unticked, ...typed] }, $("gdoc-ingest"));
}

async function loadFiles() {
  const select = $("file-pick");
  try {
    const { folder, items } = await api("GET", "/manuscripts");
    if (!items.length) {
      select.replaceChildren(el("option", { value: "" }, "Nothing in manuscripts/ yet"));
      select.disabled = true;
      $("file-ingest").disabled = true;
      $("files-hint").textContent =
        "Put a folder with one .md or .txt file per chapter, or one .md, .txt or .docx file with chapter headings, in the manuscripts folder next to docker-compose.yml.";
      return;
    }
    select.replaceChildren(
      ...items.map((i) => el("option", { value: i.path }, i.kind === "folder" ? `${i.name}/` : i.name)),
    );
    select.disabled = false;
    $("file-ingest").disabled = false;
    $("files-hint").textContent = `From the ${folder} folder: a folder of chapter files, or one file with chapter headings.`;
  } catch (error) {
    $("files-hint").textContent = error.message;
  }
}

// --- Habits and house style (spec 0007): free, no model calls ------------------------

const habitsState = { report: null, open: null, chapter: null, style: null };
const PAGE = 50;

// The range of `match` (offsets in `sentence`) inside the passage text, found by locating the
// sentence there first, so the highlight is the exact span the server verified.
function exactRange(text, sentence, match) {
  let s = sentence;
  let [a, b] = match;
  if (s.startsWith("… ")) {
    s = s.slice(2);
    a -= 2;
    b -= 2;
  }
  if (s.endsWith(" …")) s = s.slice(0, -2);
  const hay = normalise(text);
  const pieces = [[0, s.length]];
  for (const [from, to] of pieces) {
    const ctx = normalise(s.slice(from, to));
    const at = hay.text.indexOf(ctx.text.trimEnd());
    if (at < 0) continue;
    const k1 = ctx.map.findIndex((i) => i + from >= a);
    let k2 = -1;
    ctx.map.forEach((i, k) => { if (i + from < b) k2 = k; });
    if (k1 < 0 || k2 < k1) continue;
    return [[hay.map[at + k1], hay.map[at + k2] + 1]];
  }
  return [];
}

async function openExact(passageId, sentence, match, opener) {
  panelOpener = opener || document.activeElement;
  const panel = $("panel");
  $("panel-kicker").textContent = "Passage";
  $("panel-title").textContent = "Loading…";
  $("panel-body").replaceChildren();
  panel.hidden = false;
  $("panel-close").focus();
  try {
    const p = await api("POST", "/passage", { id: passageId });
    $("panel-kicker").textContent = p.chapter_title;
    $("panel-title").textContent = p.location;
    const { nodes, first } = renderPassage(p.text, null, exactRange(p.text, sentence, match));
    $("panel-body").replaceChildren(...nodes);
    if (first) first.scrollIntoView({ block: "center" });
  } catch (error) {
    $("panel-title").textContent = "Couldn't load the passage";
    $("panel-body").replaceChildren(el("p", {}, error.message));
  }
}

function marked(sentence, match) {
  const [a, b] = match;
  return [sentence.slice(0, a), el("mark", {}, sentence.slice(a, b)), sentence.slice(b)];
}

function instanceButton(i, where) {
  return el(
    "button",
    {
      class: "instance",
      type: "button",
      onclick: (ev) => i.passage_id && openExact(i.passage_id, i.sentence, i.match, ev.currentTarget),
    },
    el("span", { class: "where" }, where),
    el("span", {}, ...marked(i.sentence, i.match)),
  );
}

async function loadHabits() {
  const narration = $("habits-narration").checked;
  try {
    habitsState.report = await api("GET", `/habits?narration=${narration}&all=true`);
    renderHabits();
    loadStyle();
  } catch (error) {
    showError(error);
  }
}

function renderHabits() {
  const r = habitsState.report;
  $("habits-name").textContent = r.manuscript;
  $("habits-meta").textContent = `${fmt(r.words)} words · ${r.chapters.length} chapters · Free: no model calls`;
  const body = $("habits-body");
  if (!r.found) {
    body.replaceChildren(
      el("p", { class: "hint" }, `No repeated constructions found in ${r.chapters.length} chapters (${fmt(r.words)} words).`),
    );
    return;
  }
  const max = Math.max(
    ...r.kinds.flatMap((k) => k.habits.flatMap((h) => r.chapters.map((c) => (c.words ? (h.chapters[c.number] || 0) / c.words : 0)))),
  );
  body.replaceChildren(
    ...r.kinds.flatMap((k) => [
      el("h3", { class: "habit-kind" }, k.label),
      el(
        "div",
        { class: "habit-table" },
        ...(k.habits.length ? k.habits.map((h) => habitRow(h, k.kind, max)) : [el("div", { class: "habit-none" }, "None found")]),
      ),
    ]),
  );
}

function habitRow(h, kind, max) {
  const r = habitsState.report;
  const label = kind === "phrases" ? `“${h.label}”` : h.label;
  const strip = el(
    "div",
    { class: "strip", role: "group", "aria-label": `${h.label} by chapter` },
    ...r.chapters.map((c) => {
      const n = h.chapters[c.number] || 0;
      const rate = c.words ? (n / c.words) * 1000 : 0;
      const shade = max ? Math.round(((n / (c.words || 1)) / max) * 85) : 0;
      const title = `${c.label} · ${n} · ${rate.toFixed(1)} per 1,000 words`;
      const pressed = habitsState.open === h.id && habitsState.chapter === c.number;
      return el("button", {
        type: "button",
        title,
        "aria-label": title,
        "aria-pressed": String(pressed),
        style: `--shade: ${shade}%`,
        onclick: () => toggleHabit(h.id, habitsState.open === h.id && habitsState.chapter === c.number ? null : c.number),
      });
    }),
  );
  const variants = h.variants.length ? ` · also: ${h.variants.slice(0, 3).map((v) => `${v.form} (${v.count})`).join(", ")}` : "";
  const row = el(
    "div",
    { class: "habit-row", id: `habit-${CSS.escape(h.id)}` },
    el("button", { class: "name", type: "button", "aria-expanded": String(habitsState.open === h.id), onclick: () => toggleHabit(h.id, null, true) }, label),
    el("span", { class: "num" }, fmt(h.total)),
    el("span", { class: "sub" }, habitsState.report.narration ? "narration only" : `${fmt(h.narration)} in narration`),
    el("span", { class: "num sub" }, `${h.rate.toFixed(2)} per 1,000`),
    strip,
  );
  if (kind === "phrases") row.append(el("span", { class: "sub", style: "grid-column: 1 / -1" }, `in ${h.in_chapters} chapters${variants}`));
  if (habitsState.open === h.id) {
    const list = el("div", { class: "instances" });
    row.append(list);
    showInstances(h, list, 0);
  }
  return row;
}

function toggleHabit(id, chapter, fromName) {
  if (fromName && habitsState.open === id) {
    habitsState.open = null;
    habitsState.chapter = null;
  } else {
    habitsState.open = id;
    habitsState.chapter = chapter;
  }
  renderHabits();
  const row = document.getElementById(`habit-${CSS.escape(id)}`);
  if (row && habitsState.open) row.scrollIntoView({ block: "nearest" });
}

async function showInstances(h, list, offset) {
  const narration = $("habits-narration").checked;
  const chapter = habitsState.chapter;
  const q = new URLSearchParams({ habit: h.id, offset, limit: PAGE, narration });
  if (chapter) q.set("chapter", chapter);
  try {
    const page = await api("GET", `/habits/instances?${q}`);
    if (offset === 0) {
      const label = chapter ? habitsState.report.chapters.find((c) => c.number === chapter).label : null;
      list.replaceChildren(
        el("p", { class: "hint" }, `${fmt(page.total)} ${page.total === 1 ? "instance" : "instances"}${label ? ` in ${label}` : ""}`),
      );
    }
    list.querySelector(".linkish")?.remove();
    for (const i of page.instances) {
      list.append(instanceButton(i, `${i.label} ¶ ${i.paragraph}${i.dialogue ? " · dialogue" : ""}`));
    }
    const shown = offset + page.instances.length;
    if (shown < page.total) {
      list.append(el("button", { class: "linkish", type: "button", onclick: () => showInstances(h, list, shown) }, "Show more"));
    }
  } catch (error) {
    list.replaceChildren(el("p", { class: "hint" }, error.message));
  }
}

const STYLE_LABELS = {
  spelling: "Spelling",
  quotes: "Quotation marks",
  numbers: "Numbers",
  dash: "Dashes",
  ellipsis: "Ellipsis",
  scene_break: "Scene break line",
  chapter_heading: "Chapter heading",
  heading_exempt: "Headings left out",
  watch: "Watched words (one per line)",
};

async function loadStyle() {
  try {
    habitsState.style = await api("GET", "/style");
    renderStyleForm(habitsState.style.rules, null);
    renderMismatches(await api("GET", "/style/mismatches"));
  } catch (error) {
    showError(error);
  }
}

function renderStyleForm(rules, detected) {
  const s = habitsState.style;
  const found = (k) => (detected && detected[k] ? el("span", { class: "found" }, `Manuscript: ${detected[k].value}, ${detected[k].share}% of ${detected[k].of}`) : null);
  const fields = [];
  for (const [k, values] of Object.entries(s.choices)) {
    fields.push(
      el(
        "label",
        {},
        STYLE_LABELS[k],
        el("select", { name: k }, el("option", { value: "" }, "Not set"), ...values.map((v) => el("option", { value: v, ...(rules[k] === v ? { selected: "" } : {}) }, v))),
        found(k),
      ),
    );
  }
  fields.push(
    el("label", {}, STYLE_LABELS.scene_break, el("input", { name: "scene_break", value: rules.scene_break || "", placeholder: "* * *" }), found("scene_break"),
      s.breaks_recorded ? null : el("span", { class: "found" }, "Re-ingest to check scene breaks.")),
    el("label", {}, STYLE_LABELS.chapter_heading, el("input", { name: "chapter_heading", value: rules.chapter_heading || "", placeholder: "Chapter {n}: {title}" })),
    el("label", {}, STYLE_LABELS.heading_exempt, el("input", { name: "heading_exempt", value: (rules.heading_exempt || []).join(", "), placeholder: s.default_exempt.join(", ") })),
    el("label", { class: "wide" }, STYLE_LABELS.watch, el("textarea", { name: "watch", rows: "3" }, (rules.watch || []).join("\n"))),
  );
  $("style-fields").replaceChildren(...fields);
}

function formRules() {
  const f = $("style-form");
  const rules = {};
  for (const k of Object.keys(habitsState.style.choices)) if (f.elements[k].value) rules[k] = f.elements[k].value;
  for (const k of ["scene_break", "chapter_heading"]) if (f.elements[k].value.trim()) rules[k] = f.elements[k].value.trim();
  const exempt = f.elements.heading_exempt.value.split(",").map((x) => x.trim()).filter(Boolean);
  if (exempt.length) rules.heading_exempt = exempt;
  const watch = f.elements.watch.value.split("\n").map((x) => x.trim()).filter(Boolean);
  if (watch.length) rules.watch = watch;
  return rules;
}

async function saveStyle(event) {
  event.preventDefault();
  $("style-saved").textContent = "";
  try {
    const r = await api("PUT", "/style", { rules: formRules() });
    habitsState.style.rules = r.rules;
    $("style-saved").textContent = "Saved.";
    renderMismatches(await api("GET", "/style/mismatches"));
  } catch (error) {
    $("style-saved").textContent = error.message;
  }
}

async function detectStyle() {
  try {
    const d = await api("GET", "/style/detect");
    const merged = { ...formRules() };
    for (const [k, v] of Object.entries(d.detected)) merged[k] = v.value;
    renderStyleForm(merged, d.detected);
    $("style-saved").textContent = "Filled in from the manuscript. Nothing is saved until you press Save.";
  } catch (error) {
    showError(error);
  }
}

function renderMismatches(r) {
  const body = $("style-body");
  const set = Object.keys(r.rules).filter((k) => k !== "heading_exempt");
  if (!set.length) {
    body.replaceChildren(el("p", { class: "hint" }, "No house style set. Start from my manuscript fills the form with what your text mostly uses."));
    return;
  }
  const blocks = [];
  if (!r.mismatches) blocks.push(el("p", { class: "hint" }, `Matches your house style: ${r.checked} rules checked.`));
  for (const rule of r.by_rule) {
    const head = el("h3", {}, `${rule.rule}: ${rule.value}`,
      el("span", { class: "hint" }, rule.unchecked || (rule.total ? `${fmt(rule.total)} ${rule.total === 1 ? "mismatch" : "mismatches"}` : "matches")));
    const rows = rule.rows.map((row) => {
      if (row.after || row.paragraph === 0) {
        const where = row.after
          ? `${row.label} ${row.paragraph ? `after ¶ ${row.paragraph}` : "at the start"}`
          : `${row.label} heading`;
        return el("div", { class: "instance" }, el("span", { class: "where" }, where), el("span", {}, el("mark", {}, row.text)));
      }
      return instanceButton(row, `${row.label} ¶ ${row.paragraph} · ${row.what}`);
    });
    const labels = Object.fromEntries(rule.rows.map((row) => [String(row.chapter), row.label]));
    const per = Object.keys(rule.chapters).length > 1
      ? el("p", { class: "hint" }, "By chapter: " + Object.entries(rule.chapters).map(([n, k]) => `${labels[n] || n} ${k}`).join(" · "))
      : null;
    blocks.push(el("div", { class: "style-rule card" }, head, per, ...rows));
  }
  for (const w of r.watch) {
    const n = Object.keys(w.chapters).length;
    const head = el("h3", {}, `watch: “${w.word}”`,
      el("span", { class: "hint" }, w.total ? `${fmt(w.total)} uses in ${n} chapter${n === 1 ? "" : "s"}` : "not in the manuscript"));
    blocks.push(el("div", { class: "style-rule card" }, head, ...w.rows.slice(0, PAGE).map((row) => instanceButton(row, `${row.label} ¶ ${row.paragraph}`)),
      w.rows.length > PAGE ? el("p", { class: "hint" }, `+ ${w.rows.length - PAGE} more paragraphs: ./margin style lists them all`) : null));
  }
  body.replaceChildren(...blocks);
}

// --- Wiring --------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  for (const v of VIEWS) $(`tab-${v}`).addEventListener("click", () => setView(v));
  $("ask-form").addEventListener("submit", ask);
  $("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("ask-form").requestSubmit();
    }
  });
  for (const r of document.querySelectorAll('input[name="check-source"]')) r.addEventListener("change", syncCheckSource);
  $("check-tab").addEventListener("change", () => ($("check-plan").hidden = true));
  $("check-form").addEventListener("submit", estimate);
  $("gdoc-form").addEventListener("submit", showTabs);
  $("gdoc-ingest").addEventListener("click", ingestGoogle);
  $("file-ingest").addEventListener("click", (e) => ingest({ path: $("file-pick").value }, e.currentTarget));
  $("demo-ingest").addEventListener("click", (e) => ingest({ demo: true }, e.currentTarget));
  $("panel-close").addEventListener("click", closePanel);
  $("target-form").addEventListener("submit", saveTarget);
  $("timeline-regenerate").addEventListener("click", () => planNotes("timeline"));
  $("bible-regenerate").addEventListener("click", () => planNotes("bible"));
  $("bible-filter").addEventListener("input", renderBible);
  for (const r of document.querySelectorAll('input[name="bible-kind"]')) r.addEventListener("change", renderBible);
  $("timeline-filter").addEventListener("input", renderTimeline);
  $("habits-narration").addEventListener("change", () => {
    habitsState.open = null;
    habitsState.chapter = null;
    loadHabits();
  });
  $("style-form").addEventListener("submit", saveStyle);
  $("style-detect").addEventListener("click", detectStyle);
  for (const r of document.querySelectorAll('input[name="timeline-order"]')) r.addEventListener("change", renderTimeline);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("panel").hidden) closePanel();
  });

  const status = await refreshStatus();
  setView(status && status.passages === 0 ? "manuscript" : "ask");
});
