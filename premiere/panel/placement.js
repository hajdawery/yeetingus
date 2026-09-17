// Pure placement rules, no Adobe objects — so they can be unit-tested in Node.
// From Sherlock's panel (same author), unchanged where it matters.
function fail(kind, message) { const error = new Error(message); error.kind = kind; throw error; }

function normalizePath(path) {
  const result = String(path).replace(/\\/g, "/");
  return /^[a-z]:\//i.test(result) || result.startsWith("//") ? result.toLowerCase() : result;
}

function overlaps(spans, wanted) {
  return spans.some(a => wanted.some(b => a[0] < b[1] && b[0] < a[1]));
}

// The lowest track that is unlocked and free over every wanted span. With
// `reserveFollowing` (audio) the whole suffix of tracks from there on must be
// free too, because Premiere may spread a source's channels over several
// tracks. `allowNew` returns tracks.length — "add one" — when none is free.
function chooseTrack(tracks, wanted, allowNew, explicit, reserveFollowing = false) {
  const free = index => !tracks[index].locked && !overlaps(tracks[index].spans, wanted);
  if (explicit != null) {
    if (!Number.isInteger(explicit) || explicit < 0 || explicit >= tracks.length || !free(explicit))
      fail("Occupied", "The requested track is occupied or unavailable.");
    return explicit;
  }
  for (let i = 0; i < tracks.length; i++) {
    if (free(i) && (!reserveFollowing || tracks.slice(i).every((_, j) => free(i + j)))) return i;
  }
  if (allowNew) return tracks.length;
  fail("Occupied", "The destination tracks are occupied. A new track is needed.");
}

module.exports = { fail, normalizePath, overlaps, chooseTrack };
