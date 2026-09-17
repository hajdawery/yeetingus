// All Adobe calls live here. The transport (main.js) never evaluates code the
// service sends; it only dispatches the two named methods below.
//
// Placement follows Sherlock's panel (premiere/panel/host.js there), trimmed
// to what YEETingus needs: import one whole file and overwrite it onto the
// active sequence at the playhead or at the start, on the lowest free tracks.
const { fail, normalizePath, chooseTrack } = require("./placement.js");

function createAdapter(ppro, version = "") {
  const CLIP = ppro.Constants.TrackItemType.CLIP;
  const TRANSITION = ppro.Constants.TrackItemType.TRANSITION;
  const seconds = time => time.seconds;
  const guid = item => item ? item.guid.toString() : null;
  const at = (frame, fps) => ppro.TickTime.createWithFrameAndFrameRate(frame, ppro.FrameRate.createWithValue(fps));

  function transact(project, title, actions) {
    let ok = false;
    project.lockedAccess(() => {
      ok = project.executeTransaction(compound => actions(compound), title);
    });
    if (!ok) fail("PremiereError", "Premiere refused the transaction: " + title);
  }

  async function context() {
    const project = await ppro.Project.getActiveProject();
    if (!project) fail("NoProject", "Open a project in Premiere first.");
    const sequence = await project.getActiveSequence();
    if (!sequence) fail("NoSequence", "Open a sequence in Premiere first.");
    return { project, sequence };
  }

  async function status() {
    const project = await ppro.Project.getActiveProject();
    const sequence = project && await project.getActiveSequence();
    let fps = null;
    if (sequence) {
      try { fps = (await sequence.getSettings()).getVideoFrameRate().value; } catch (_) { /* older host */ }
    }
    return { version, project: project ? project.name : "", sequence: sequence ? sequence.name : "",
      projectId: guid(project), sequenceId: guid(sequence), fps };
  }

  async function walk(folder) {
    const found = [];
    for (const item of await folder.getItems()) {
      if (item.type === ppro.ProjectItem.TYPE_BIN || item.type === ppro.ProjectItem.TYPE_ROOT)
        found.push(...await walk(ppro.FolderItem.cast(item)));
      else found.push(item);
    }
    return found;
  }

  // Whether a project item carries no video — the shape Premiere gives a file
  // it couldn't decode the picture of (an AV1 MP4, say). Premiere keeps that
  // item even after the file on disk has been replaced by one it can play.
  // Premiere's ContentType enum is only MEDIA / SEQUENCE / ANY (26.3), so
  // the project panel's own columns are the source: "Video Info" is filled
  // for anything with a picture and empty for an audio-only item.
  async function lacksVideo(item) {
    try {
      const cols = JSON.parse(await ppro.Metadata.getProjectColumnsMetadata(item));
      const video = cols.find(c => /VideoInfo/i.test(c.ColumnID));
      if (video) return !String(video.ColumnValue || "").trim();
    } catch (_) { /* older host, or no metadata: assume it's fine */ }
    return false;
  }

  // The project item for a media file: an existing one if the file is already
  // in the project, else imported into the root bin. An existing item that is
  // audio-only while the file has video is stale (see lacksVideo) and is not
  // reused: the file is imported again and the new item taken.
  async function itemFor(project, path, hasVideo) {
    const wanted = normalizePath(path);
    const findAll = async () => {
      const found = [];
      for (const item of await walk(await project.getRootItem())) {
        let clip;
        try { clip = ppro.ClipProjectItem.cast(item); } catch (_) { continue; }
        if (!clip || await clip.isSequence()) continue;
        if (normalizePath(await clip.getMediaFilePath()) === wanted) found.push({ item, clip });
      }
      return found;
    };
    const before = await findAll();
    for (const { item, clip } of before) {
      if (hasVideo && await lacksVideo(item)) continue;
      return item;
    }
    if (!await project.importFiles([path], true, await project.getRootItem(), false))
      fail("MissingMedia", "Premiere could not import: " + path);
    const seen = new Set(before.map(b => b.item.getId ? b.item.getId() : b.item.name));
    const after = await findAll();
    const fresh = after.find(a => !seen.has(a.item.getId ? a.item.getId() : a.item.name)) || after[after.length - 1];
    if (!fresh) fail("PremiereError", "The imported clip could not be found in the project.");
    if (hasVideo && await lacksVideo(fresh.item))
      fail("MissingMedia", "Premiere imported the clip without video — it can't decode this file.");
    return fresh.item;
  }

  async function tracks(sequence, audio) {
    const count = await (audio ? sequence.getAudioTrackCount() : sequence.getVideoTrackCount());
    const result = [];
    for (let i = 0; i < count; i++) {
      const track = await (audio ? sequence.getAudioTrack(i) : sequence.getVideoTrack(i));
      const spans = [];
      // Transitions occupy space too. Never treat their area as a free gap.
      for (const kind of [CLIP, TRANSITION]) {
        for (const item of await track.getTrackItems(kind, false))
          spans.push([seconds(await item.getStartTime()), seconds(await item.getEndTime())]);
      }
      result.push({ index: i, spans,
        locked: typeof track.isLocked === "function" ? await track.isLocked() : false });
    }
    return result;
  }

  // insert({path, at}) — at: "playhead" | "start"
  async function insert(params) {
    if (typeof params.path !== "string" || !params.path.trim()) fail("InvalidRange", "No file to insert.");
    if (!["playhead", "start"].includes(params.at)) fail("InvalidRange", "Unknown destination position.");
    const { project, sequence } = await context();
    const item = await itemFor(project, params.path, params.hasVideo !== false);
    const clip = ppro.ClipProjectItem.cast(item);
    if (await clip.isOffline()) fail("MissingMedia", "The clip is offline in Premiere: " + params.path);

    let fps = (await sequence.getSettings()).getVideoFrameRate().value;
    if (!(fps > 0)) fps = 25;
    const media = await clip.getMedia();
    const duration = seconds(typeof media.getDuration === "function" ? await media.getDuration() : await media.duration);
    const startSeconds = params.at === "start" ? 0 : seconds(await sequence.getPlayerPosition());
    const recordFrame = Math.round(startSeconds * fps);
    const wanted = [[recordFrame / fps, recordFrame / fps + duration]];

    // Lowest free tracks; a new one if everything at that spot is taken.
    const video = await tracks(sequence, false), audio = await tracks(sequence, true);
    const videoIndex = chooseTrack(video, wanted, true);
    const audioIndex = chooseTrack(audio, wanted, true, null, true);
    const usedNewTrack = videoIndex >= video.length || audioIndex >= audio.length;

    // Fit the picture to the sequence (4K into 1080p and the like), then place.
    const editor = ppro.SequenceEditor.getEditor(sequence);
    transact(project, "YEETingus: insert clip", c => {
      c.addAction(clip.createSetScaleToFrameSizeAction());
      c.addAction(editor.createOverwriteItemAction(item, at(recordFrame, fps), videoIndex, audioIndex));
    });

    return { clipName: item.name, sequence: sequence.name, insertedFrame: recordFrame,
      trackIndex: videoIndex + 1, audioTrackIndex: audioIndex + 1, usedNewTrack, fps };
  }

  // probe({path}) — what Premiere holds for a file; for diagnosing imports.
  async function probe(params) {
    const { project } = await context();
    const wanted = normalizePath(params.path || "");
    const out = { contentTypeEnum: ppro.Constants.ContentType ? Object.entries(ppro.Constants.ContentType) : null,
      mediaTypeEnum: ppro.Constants.MediaType ? Object.entries(ppro.Constants.MediaType) : null, items: [] };
    for (const item of await walk(await project.getRootItem())) {
      let clip;
      try { clip = ppro.ClipProjectItem.cast(item); } catch (_) { continue; }
      if (!clip || await clip.isSequence()) continue;
      if (normalizePath(await clip.getMediaFilePath()) !== wanted) continue;
      const rec = { name: item.name, id: item.getId ? item.getId() : null, offline: await clip.isOffline() };
      try { rec.contentType = await clip.getContentType(); } catch (e) { rec.contentType = "ERR " + e.message; }
      try { rec.hasVideoFn = typeof clip.hasVideo; } catch (_) {}
      for (const t of ["VIDEO", "AUDIO"]) {
        try { rec["in_" + t] = (await clip.getInPoint(ppro.Constants.MediaType[t])).seconds; } catch (e) { rec["in_" + t] = "ERR " + e.message; }
      }
      try { const m = await clip.getMedia(); rec.duration = (typeof m.getDuration === "function" ? await m.getDuration() : m.duration).seconds; } catch (e) { rec.duration = "ERR " + e.message; }
      try { rec.footageFps = (await clip.getFootageInterpretation()).getFrameRate(); } catch (e) { rec.footageFps = "ERR " + e.message; }
      try {
        const cols = JSON.parse(await ppro.Metadata.getProjectColumnsMetadata(item));
        rec.columns = cols.filter(c => /Video|Audio|Media|Frame|Type/i.test(c.ColumnID)).map(c => [c.ColumnID, String(c.ColumnValue).slice(0, 40)]);
      } catch (e) { rec.columns = "ERR " + e.message; }
      out.items.push(rec);
    }
    return out;
  }

  return { status, dispatch: async (method, params) => {
    if (method === "status") return await status();
    if (method === "insert") return await insert(params || {});
    if (method === "probe") return await probe(params || {});
    fail("UnknownMethod", "Unsupported command: " + method);
  } };
}
module.exports = { createAdapter };
