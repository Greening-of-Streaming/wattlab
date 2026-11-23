// Open WattLab → GoS website bridge (CR-087).
//
// Copies the OWL findings feed into the Wix collection "OwlFindings" once an
// hour (see jobs.config). The findings page reads only that collection, so it
// keeps showing the last good copy whenever OWL is offline.
//
// Safety rules:
//   - Nothing is changed unless the feed downloads and passes checks.
//   - A finding that has left the feed is removed only after a good download.
//   - If the feed suddenly empties while the collection has findings, nothing
//     is removed: that looks like a fault, not a decision.

import { fetch } from 'wix-fetch';
import wixData from 'wix-data';

const FEED_URL = 'https://wattlab.greeningofstreaming.org/findings.json';
const COLLECTION = 'OwlFindings';
const OPTS = { suppressAuth: true };

function toItem(f, syncedAt) {
  return {
    _id: f.slug,
    title: f.headline,
    slug: f.slug,
    whyItMatters: f.why_it_matters || '',
    summary: f.summary || '',
    keyNumber: f.key_number || '',
    earlySignal: !!f.early_signal,
    repeats: typeof f.repeats === 'number' ? f.repeats : null,
    confidence: f.confidence || '',
    confidenceLabel: f.confidence_label || '',
    reviewLabel: f.review_label || '',
    question: f.question || '',
    questionLabel: f.question_label || '',
    stages: (f.stages || []).join(', '),
    firstMeasured: f.first_measured || '',
    lastRefined: f.last_refined || '',
    owlUrl: f.url || '',
    sortOrder: f.sort_order || 0,
    syncedAt,
  };
}

async function loadFeed() {
  const res = await fetch(FEED_URL, { method: 'get' });
  if (!res.ok) throw new Error(`OWL feed answered ${res.status}`);
  const feed = await res.json();
  if (feed.schema_version !== 1 || !Array.isArray(feed.findings) || feed.count !== feed.findings.length) {
    throw new Error('OWL feed failed its checks');
  }
  for (const f of feed.findings) {
    if (!f.slug || !f.headline) throw new Error('OWL feed has a finding without slug or headline');
  }
  return feed;
}

export async function syncOwlFindings() {
  let feed;
  try {
    feed = await loadFeed();
  } catch (err) {
    console.warn('OWL sync skipped, keeping the last good copy:', err.message);
    return { ok: false, reason: err.message };
  }
  const syncedAt = new Date();
  const existing = await wixData.query(COLLECTION).limit(1000).find(OPTS);
  const keep = new Set(feed.findings.map((f) => f.slug));

  for (const f of feed.findings) {
    await wixData.save(COLLECTION, toItem(f, syncedAt), OPTS);
  }

  let removed = 0;
  if (feed.findings.length === 0 && existing.items.length > 0) {
    console.warn('OWL feed is empty but the site has findings: removing nothing.');
  } else {
    for (const item of existing.items) {
      if (!keep.has(item._id)) {
        await wixData.remove(COLLECTION, item._id, OPTS);
        removed += 1;
      }
    }
  }
  console.log(`OWL sync: ${feed.findings.length} saved, ${removed} removed`);
  return { ok: true, saved: feed.findings.length, removed };
}
