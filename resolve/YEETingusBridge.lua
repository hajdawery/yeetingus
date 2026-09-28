--[[
  YEETingusBridge.lua - the Resolve Free insert bridge.

  Resolve Free has no external scripting (since 19.1), so the app cannot reach
  the timeline from outside. Instead this file runs INSIDE Resolve, started by
  the YEETingus entry in Workspace > Scripts, and stays running until Resolve
  quits. The app talks to it through a file mailbox:

    app  -> writes <dir>/request.lua (a Lua table literal, renamed into place)
    here -> sees it (bmd.fileexists), loads it in an empty environment,
            sets Global.YEETingus.Ack = id, runs the handler, then sets
            Global.YEETingus.Response = id .. ":" .. hex(json) and SavePrefs()
    app  <- reads Fusion.prefs from disk and matches the id

  Why this shape: the Free 21.1 sandbox removes io, os.execute, os.remove,
  require, ffi and print. What is left is loadfile, setfenv, bmd.fileexists,
  bmd.wait, fusion:SetPrefs/SavePrefs and the full resolve object. So reading
  is loadfile, writing is Fusion's own prefs file, and the request file is
  deleted by the app, never here. Same channel as AutoSubs; see
  RESOLVE-FREE-INSERT.md for the traps this avoids.

  Rules this file keeps (each one is a crash or a glitch someone else hit):
    * No prefs writes while idle. SetPrefs fires a UI event in Resolve; a write
      a second broke Inspector drags. Owner is written once at start, then
      only Ack and Response, once per request.
    * One loop only. Owner is set in memory on start; a loop that sees another
      Owner exits, so a second menu click takes over the first.
    * A fixed handler table. Requests carry data, never code.
    * ASCII out. The response is hex, so Fusion.prefs stays ASCII whatever the
      clip is called.
    * Whole frames only: Resolve 21 rejects a non-integer frame.

  Loaded by the launcher with loadfile, so it can be updated without touching
  the menu entry. The app writes the current copy on start. ASCII only.
]]--

local BRIDGE_VERSION = 1
local PREFS = "Global.YEETingus."
local POLL_S = 0.1             -- request check
local OWNER_EVERY = 5          -- polls between Owner checks (0.5 s)
local STALE_S = 120            -- ignore a request older than this

-- ------------------------------------------------------------------ JSON --

local function json_string(s)
  s = s:gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' end
    if c == "\\" then return "\\\\" end
    if c == "\n" then return "\\n" end
    if c == "\r" then return "\\r" end
    if c == "\t" then return "\\t" end
    return string.format("\\u%04x", c:byte())
  end)
  return '"' .. s .. '"'
end

local json

local function json_number(n)
  if n ~= n or n == math.huge or n == -math.huge then return "null" end
  if n == math.floor(n) and math.abs(n) < 1e15 then
    return string.format("%d", n)
  end
  return string.format("%.17g", n)
end

json = function(v)
  local t = type(v)
  if t == "nil" then return "null" end
  if t == "boolean" then return tostring(v) end
  if t == "number" then return json_number(v) end
  if t == "string" then return json_string(v) end
  if t == "table" then
    local parts = {}
    if v[1] ~= nil then
      for i = 1, #v do parts[#parts + 1] = json(v[i]) end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    for k, x in pairs(v) do
      parts[#parts + 1] = json_string(tostring(k)) .. ":" .. json(x)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return "null"
end

local function hex(s)
  return (s:gsub(".", function(c) return string.format("%02x", c:byte()) end))
end

-- --------------------------------------------------------------- helpers --

-- Errors meant for the user are tables; anything else is a bug in here.
local function fail(msg) error({ msg = msg }, 0) end

local function whole(x) return math.floor(x + 0.5) end

-- "29.97 DF" -> 29.97
local function fps_of(value, default)
  local n = tonumber((tostring(value or ""):match("^%s*([%d%.]+)")))
  if n and n > 0 then return n end
  return default
end

-- 'HH:MM:SS:FF' (or drop-frame 'HH:MM:SS;FF') -> frame index, as
-- resolve_bridge._timecode_to_frames does it.
local function timecode_to_frames(tc, fps)
  if type(tc) ~= "string" or tc == "" then return nil end
  local drop = tc:find(";", 1, true) ~= nil
  local hh, mm, ss, ff = tc:gsub(";", ":"):match("^(%d+):(%d+):(%d+):(%d+)$")
  if not hh then return nil end
  hh, mm, ss, ff = tonumber(hh), tonumber(mm), tonumber(ss), tonumber(ff)
  local nominal = whole(fps)
  local frames = (hh * 3600 + mm * 60 + ss) * nominal + ff
  if drop and (nominal == 30 or nominal == 60) then
    local dropped = nominal / 15
    local minutes = hh * 60 + mm
    frames = frames - dropped * (minutes - math.floor(minutes / 10))
  end
  return frames
end

local function list(t)
  if type(t) ~= "table" then return {} end
  return t
end

-- A timeline item's start, or nil for a dead handle (AppendToTimeline onto a
-- busy spot returns items whose methods return nil).
local function start_of(x)
  local ok, s = pcall(function() return x:GetStart() end)
  if ok then return s end
  return nil
end

local function media_id(x)
  local ok, id = pcall(function()
    local mpi = x:GetMediaPoolItem()
    return mpi and mpi:GetMediaId()
  end)
  if ok then return id end
  return nil
end

-- ------------------------------------------------------------- Resolve --

local R                       -- the resolve object, set by run()

local function current()
  local pm = R:GetProjectManager()
  local project = pm and pm:GetCurrentProject()
  if not project then fail("No project is open in Resolve.") end
  local tl = project:GetCurrentTimeline()
  if not tl then fail("No timeline is open. Create or open one first.") end
  return project, tl
end

local function timeline_length(item, tl, start_frame, end_frame)
  local frames = tonumber(item:GetClipProperty("Frames") or "") or 0
  local clip_fps = tonumber(item:GetClipProperty("FPS") or "") or 0
  local tl_fps = fps_of(tl:GetSetting("timelineFrameRate"), 0)
  if end_frame then frames = end_frame end
  frames = frames - (start_frame or 0)
  if frames <= 0 or clip_fps == 0 or tl_fps == 0 then return nil end
  return math.max(1, math.ceil(frames * tl_fps / clip_fps))
end

-- The lowest track index whose video AND audio track are unlocked and empty
-- over [start, start + length); adds a track pair when all are taken.
-- Port of resolve_bridge._free_track.
local function free_track(tl, start, length)
  local finish = start + length

  local function free(kind, index)
    if index > tl:GetTrackCount(kind) then return true end
    local ok, locked = pcall(function() return tl:GetIsTrackLocked(kind, index) end)
    if ok and locked then return false end
    local items = list(tl:GetItemListInTrack(kind, index))
    for i = 1, #items do
      local x = items[i]
      local s = start_of(x)
      local e = s and x:GetEnd()
      if s and e and s < finish and e > start then return false end
    end
    return true
  end

  local top = math.max(tl:GetTrackCount("video"), tl:GetTrackCount("audio")) + 1
  local index = top
  for i = 1, top do
    if free("video", i) and free("audio", i) then index = i; break end
  end
  local created = false
  while tl:GetTrackCount("video") < index do
    if not tl:AddTrack("video") then fail("Couldn't add a video track for the clip.") end
    created = true
  end
  while tl:GetTrackCount("audio") < index do
    if not tl:AddTrack("audio", "stereo") then fail("Couldn't add an audio track for the clip.") end
    created = true
  end
  return index, created
end

local function pool_bin(pool, name)
  local root = pool:GetRootFolder()
  if not root then return nil end
  local subs = list(root:GetSubFolderList())
  for i = 1, #subs do
    if subs[i]:GetName() == name then return subs[i] end
  end
  return pool:AddSubFolder(root, name)
end

-- The clip for `path` in `folder`, fetched again. Taperat found that the item
-- AddItemListToMediaPool returns can append nothing where this one works.
local function refetch(folder, path)
  if not folder then return nil end
  local want = path:gsub("\\", "/"):lower()
  local clips = list(folder:GetClipList())
  for i = #clips, 1, -1 do
    local p = clips[i]:GetClipProperty("File Path")
    if type(p) == "string" and p:gsub("\\", "/"):lower() == want then
      return clips[i]
    end
  end
  return nil
end

local handlers = {}

function handlers.Ping()
  local product, version = "", ""
  pcall(function() product = R:GetProductName() end)
  pcall(function() version = R:GetVersionString() end)
  local page
  pcall(function() page = R:GetCurrentPage() end)
  return { bridge = BRIDGE_VERSION, product = product, version = version, page = page }
end

function handlers.GetTimelineInfo()
  local project, tl = current()
  local fps = fps_of(tl:GetSetting("timelineFrameRate"), 24)
  local playback = tonumber(tl:GetSetting("timelinePlaybackFrameRate") or "")
                or tonumber(project:GetSetting("timelinePlaybackFrameRate") or "")
  local tc = tl:GetCurrentTimecode()
  return {
    project = project:GetName(),
    timeline = tl:GetName(),
    fps = fps,
    playbackFps = playback,
    currentTimecode = tc,
    currentFrame = timecode_to_frames(tc, fps),
    startFrame = tl:GetStartFrame(),
  }
end

-- Port of resolve_bridge.import_and_insert. args: path, insertAt, trackIndex,
-- startFrame, endFrame, retime (Resolve's RetimeProcess number, 0 = leave),
-- retimeName, bin.
function handlers.ImportAndInsert(a)
  local path = a.path
  if type(path) ~= "string" or path == "" then fail("No file given.") end
  if not bmd.fileexists(path) then fail("File not found: " .. path) end

  local project, tl = current()
  local pool = project:GetMediaPool()

  local record_frame
  if a.insertAt == "playhead" then
    local fps = fps_of(tl:GetSetting("timelineFrameRate"), 24)
    record_frame = timecode_to_frames(tl:GetCurrentTimecode(), fps)
    if not record_frame then
      fail("Can't read the playhead position. Switch Resolve to the Edit or Cut page and try again.")
    end
  elseif a.insertAt == "start" then
    record_frame = tl:GetStartFrame()
  end

  local bin_name = a.bin or ""
  local previous = bin_name ~= "" and pool:GetCurrentFolder() or nil
  local target = bin_name ~= "" and pool_bin(pool, bin_name) or nil
  local switched = target ~= nil and pool:SetCurrentFolder(target) and true or false
  local folder = pool:GetCurrentFolder()
  local ok_import, items = pcall(function()
    return R:GetMediaStorage():AddItemListToMediaPool({ path })
  end)
  if previous then pool:SetCurrentFolder(previous) end
  items = ok_import and list(items) or {}
  local item = items[1]
  if not item then fail("Resolve refused to import: " .. path) end

  local start_frame = a.startFrame and whole(a.startFrame) or 0
  local end_frame = a.endFrame and whole(a.endFrame) or nil
  local track_index = a.trackIndex
  local created = false
  if not track_index and record_frame then
    local length = timeline_length(item, tl, start_frame, end_frame)
    if length then track_index, created = free_track(tl, whole(record_frame), length) end
  end

  local function info_for(mpi)
    local info = { mediaPoolItem = mpi }
    if start_frame ~= 0 then info.startFrame = start_frame end
    if end_frame then info.endFrame = end_frame end
    if record_frame then info.recordFrame = whole(record_frame) end
    if track_index then info.trackIndex = track_index end
    return info
  end

  local function placed_ok(result, mpi)
    if type(result) ~= "table" or #result == 0 then
      if result ~= true then return false end
    end
    if not record_frame then return true end
    local want = mpi:GetMediaId()
    local on_track = list(tl:GetItemListInTrack("video", track_index or 1))
    for i = 1, #on_track do
      local x = on_track[i]
      if start_of(x) == whole(record_frame) and media_id(x) == want then return true end
    end
    return false
  end

  local result = pool:AppendToTimeline({ info_for(item) })
  local ok = placed_ok(result, item)
  if not ok and (type(result) ~= "table" or #result == 0) then
    -- Nothing was placed at all: try once more with the clip fetched again.
    local again = refetch(target or folder, path)
    if again then
      item = again
      result = pool:AppendToTimeline({ info_for(item) })
      ok = placed_ok(result, item)
    end
  end
  if not ok then
    fail("Imported to the media pool, but Resolve didn't place it on the timeline. "
         .. "Is the track locked, or the clip longer than the timeline allows?")
  end

  local out = {
    clipName = item:GetName(),
    insertedFrame = record_frame and whole(record_frame) or nil,
    trackIndex = track_index or 1,
    newTrack = created,
    bin = switched and bin_name or nil,
  }

  -- Frame-rate mismatch: set the retime process on the placed item.
  pcall(function()
    local mode = tonumber(a.retime) or 0
    local tl_fps = fps_of(tl:GetSetting("timelineFrameRate"), 0)
    local clip_fps = tonumber(item:GetClipProperty("FPS") or "") or 0
    if mode == 0 or tl_fps == 0 or clip_fps == 0 or math.abs(tl_fps - clip_fps) <= 0.01 then
      return
    end
    local placed = {}
    for _, x in ipairs(list(result)) do
      if type(x) ~= "boolean" and start_of(x) then placed[#placed + 1] = x end
    end
    if #placed == 0 then
      local want = item:GetMediaId()
      local best
      for t = 1, tl:GetTrackCount("video") do
        local xs = list(tl:GetItemListInTrack("video", t))
        for i = 1, #xs do
          local x = xs[i]
          local s = start_of(x)
          if s and media_id(x) == want then
            if record_frame then
              if s == whole(record_frame) then placed[#placed + 1] = x end
            elseif not best or s > start_of(best) then
              best = x
            end
          end
        end
      end
      if best then placed[#placed + 1] = best end
    end
    for i = 1, #placed do
      if placed[i]:SetProperty("RetimeProcess", mode) then
        out.retimed = { mode = a.retimeName, clipFps = clip_fps, timelineFps = tl_fps }
      end
    end
  end)

  return out
end

-- ---------------------------------------------------------------- loop --

-- ctx: dir (the mailbox folder, forward slashes), version, fusion, resolve.
return function(ctx)
  local fu = ctx.fusion
  R = ctx.resolve
  if not (fu and R and ctx.dir) then return false end
  local request = ctx.dir .. "/request.lua"

  local function set(key, value) fu:SetPrefs(PREFS .. key, value) end
  local function get(key) return fu:GetPrefs(PREFS .. key) end
  local function respond(id, body)
    set("Response", id .. ":" .. hex(json(body)))
    fu:SavePrefs()
  end

  -- Takeover: the newest loop owns the mailbox. Saved once, here, so the app
  -- can tell "never started" (no Owner on disk: fail fast) from "started"
  -- (wait for an ack). The only write that isn't an answer.
  local token = tostring(bmd.createuuid and bmd.createuuid() or os.time())
  set("Owner", token)
  fu:SavePrefs()

  local handled, n = {}, 0
  while true do
    if bmd.fileexists(request) then
      local chunk = loadfile(request)
      local ok, req = false, nil
      if chunk then
        setfenv(chunk, {})
        ok, req = pcall(chunk)
      end
      if ok and type(req) == "table" and type(req.id) == "string" and not handled[req.id] then
        handled[req.id] = true
        local fresh = type(req.created) ~= "number" or os.time() - req.created <= STALE_S
        if fresh then
          set("Ack", req.id)
          fu:SavePrefs()
          local body
          if req.cmd == "Stop" then
            body = { ok = true, result = { stopped = true } }
          else
            local handler = handlers[req.cmd]
            if not handler then
              body = { ok = false, error = "Unknown request: " .. tostring(req.cmd) }
            else
              local good, res = pcall(handler, type(req.args) == "table" and req.args or {})
              if good then
                body = { ok = true, result = res }
              elseif type(res) == "table" and res.msg then
                body = { ok = false, error = res.msg }
              else
                body = { ok = false, error = "Resolve bridge error: " .. tostring(res) }
              end
            end
          end
          if req.cmd == "Stop" then set("Owner", "") end
          respond(req.id, body)
          if req.cmd == "Stop" then return true end
        end
      end
    end

    n = n + 1
    if n % OWNER_EVERY == 0 and get("Owner") ~= token then
      return true                -- a newer click took over
    end
    bmd.wait(POLL_S)
  end
end
