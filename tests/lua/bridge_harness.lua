--[[
  Test harness for the Resolve Free insert bridge. Run by
  tests/test_resolve_mailbox.py under Resolve's own fuscript (LuaJIT), not
  inside Resolve:

    fuscript -l lua bridge_harness.lua

  It runs the rendered launcher (YEET_HARNESS_LAUNCHER) against a mock Resolve
  and a mock Fusion whose SavePrefs writes a Fusion.prefs-shaped file
  (YEET_HARNESS_PREFS), so the Python side talks to it exactly as it would
  to Resolve.

  YEET_HARNESS_MODE:
    free    the launcher runs in a copy of the Free 21.1 sandbox: io, package,
            require, ffi, debug, os.execute/remove/rename are gone. Anything
            that touches them throws, as it would in Resolve. The bridge it
            starts inherits the same environment.
    studio  full library and a Studio product name: the launcher must not
            start the bridge (and the paths it would launch don't exist).
]]--

local MODE = os.getenv("YEET_HARNESS_MODE") or "free"
-- The item AddItemListToMediaPool returns appends nothing; the same clip
-- fetched again from the bin works (what Taperat saw).
local STALE_ITEM = os.getenv("YEET_HARNESS_STALE_ITEM") == "1"
-- What Resolve reports as the clip's File Path, if not the path imported (a
-- file imported by its 8.3 short path comes back under its long one). Read
-- from a UTF-8 file: an environment variable would arrive in the ANSI code page.
local REPORTED_PATH
do
  local f = os.getenv("YEET_HARNESS_REPORTED_FILE")
  local fh = f and io.open(f, "rb")
  if fh then REPORTED_PATH = fh:read("*a"); fh:close() end
end
local LAUNCHER = assert(os.getenv("YEET_HARNESS_LAUNCHER"), "YEET_HARNESS_LAUNCHER")
local PREFS_FILE = assert(os.getenv("YEET_HARNESS_PREFS"), "YEET_HARNESS_PREFS")

-- ------------------------------------------------------------- bmd ----

local real_bmd = type(bmd) == "table" and bmd or {}

local function sleep(s)
  if type(real_bmd.wait) == "function" then return real_bmd.wait(s) end
  local t = os.clock() + s
  while os.clock() < t do end
end

local uuid_n = 0
local mock_bmd = {
  fileexists = function(p)
    local fh = io.open(p, "rb")
    if fh then fh:close(); return true end
    return false
  end,
  direxists = function() return false end,
  wait = sleep,
  createuuid = function()
    uuid_n = uuid_n + 1
    return string.format("tok-%d-%d", os.time(), uuid_n)
  end,
}

-- ------------------------------------------------------------ fusion ---

local prefs = {}
local PREFIX = "Global.YEETingus."
local saves = 0

local fusion_mock = {}
function fusion_mock:SetPrefs(key, value)
  assert(key:sub(1, #PREFIX) == PREFIX, "unexpected prefs key " .. key)
  prefs[key:sub(#PREFIX + 1)] = value
end
function fusion_mock:GetPrefs(key)
  return prefs[key:sub(#PREFIX + 1)]
end
function fusion_mock:SavePrefs()
  saves = saves + 1
  local lines = { "{", "\tComp = {", "\t\tAutoSave = {", "\t\t\tEnabled = true", "\t\t},", "\t},",
                  "\tGlobal = {", "\t\tYEETingus = {" }
  for k, v in pairs(prefs) do
    lines[#lines + 1] = string.format('\t\t\t%s = "%s",', k, v)
  end
  lines[#lines + 1] = "\t\t},"
  lines[#lines + 1] = "\t},"
  lines[#lines + 1] = "}"
  -- Written in place, as Fusion does; the reader must cope with that.
  local fh = assert(io.open(PREFS_FILE, "wb"))
  fh:write(table.concat(lines, "\r\n"))
  fh:close()
  return true
end

-- ------------------------------------------------------------ resolve --

local FPS_TL, FPS_CLIP, CLIP_FRAMES = 24, 60, 600
local START = 86400                       -- 01:00:00:00 at 24 fps

local function tl_item(mpi, s, e)
  local x = {}
  function x:GetStart() return s end
  function x:GetEnd() return e end
  function x:GetMediaPoolItem() return mpi end
  function x:SetProperty(k, v) return k == "RetimeProcess" and v == 2 end
  return x
end

local function folder(name)
  local f = { subs = {}, clips = {} }
  function f:GetName() return name end
  function f:GetSubFolderList() return f.subs end
  function f:GetClipList() return f.clips end
  return f
end

local other = { GetMediaId = function() return "mid-other" end }
local tracks = {
  video = { { tl_item(other, START, START + 1000) } },    -- V1 is busy at the playhead
  audio = { { tl_item(other, START, START + 1000) } },
}

local root = folder("Master")
local current = root
local media_n = 0

local pool = {}
function pool:GetRootFolder() return root end
function pool:GetCurrentFolder() return current end
function pool:SetCurrentFolder(f) current = f; return true end
function pool:AddSubFolder(parent, name)
  local f = folder(name)
  parent.subs[#parent.subs + 1] = f
  return f
end
function pool:AppendToTimeline(infos)
  local out = {}
  for i = 1, #infos do
    local info = infos[i]
    for _, k in ipairs({ "startFrame", "endFrame", "recordFrame", "trackIndex" }) do
      local v = info[k]
      if v ~= nil and v ~= math.floor(v) then return nil end   -- Resolve 21: whole frames
    end
    local t = info.trackIndex or 1
    if not tracks.video[t] or info.mediaPoolItem.stale then return {} end
    local first = info.startFrame or 0
    local last = info.endFrame or CLIP_FRAMES
    local len = math.ceil((last - first) * FPS_TL / FPS_CLIP)
    local s = info.recordFrame or START
    local x = tl_item(info.mediaPoolItem, s, s + len)
    table.insert(tracks.video[t], x)
    table.insert(tracks.audio[t], tl_item(info.mediaPoolItem, s, s + len))
    out[#out + 1] = x
  end
  return out
end

local storage = {}
function storage:AddItemListToMediaPool(paths)
  local p = paths[1]
  if not mock_bmd.fileexists(p) then return {} end
  media_n = media_n + 1
  local mid = "mid-" .. media_n
  local item = {}
  function item:GetName() return (p:match("[^/\\]+$")) end
  function item:GetMediaId() return mid end
  function item:GetClipProperty(k)
    if k == "FPS" then return FPS_CLIP end
    if k == "Frames" then return tostring(CLIP_FRAMES) end
    if k == "File Path" then return REPORTED_PATH or p end
    return ""
  end
  current.clips[#current.clips + 1] = item
  if STALE_ITEM then
    local stale = { stale = true }
    function stale:GetName() return item:GetName() end
    function stale:GetMediaId() return "mid-stale" end
    function stale:GetClipProperty(k) return item:GetClipProperty(k) end
    return { stale }
  end
  return { item }
end

local timeline = {}
function timeline:GetName() return "Timeline 1" end
function timeline:GetSetting(k)
  if k == "timelineFrameRate" or k == "timelinePlaybackFrameRate" then return tostring(FPS_TL) end
  return ""
end
function timeline:GetCurrentTimecode() return "01:00:10:00" end
function timeline:GetStartFrame() return START end
function timeline:GetTrackCount(kind) return #tracks[kind] end
function timeline:GetIsTrackLocked() return false end
function timeline:GetItemListInTrack(kind, i)
  local copy = {}
  for n, x in ipairs(tracks[kind][i] or {}) do copy[n] = x end
  return copy
end
function timeline:AddTrack(kind)
  tracks[kind][#tracks[kind] + 1] = {}
  return true
end

local project = {}
function project:GetName() return "Friday video" end
function project:GetCurrentTimeline() return timeline end
function project:GetMediaPool() return pool end
function project:GetSetting() return "" end

local resolve_mock = {}
function resolve_mock:GetProjectManager()
  return { GetCurrentProject = function() return project end }
end
function resolve_mock:GetMediaStorage() return storage end
function resolve_mock:GetProductName()
  return MODE == "studio" and "DaVinci Resolve Studio" or "DaVinci Resolve"
end
function resolve_mock:GetVersionString() return "21.1.0.17" end
function resolve_mock:GetCurrentPage() return "edit" end
function resolve_mock:Fusion() return fusion_mock end

-- ------------------------------------------------------------ sandbox --

local env
if MODE == "free" then
  local gone = { io = true, package = true, require = true, ffi = true, debug = true,
                 module = true, dofile = true }
  local sandbox_os = { time = os.time, clock = os.clock, getenv = os.getenv, date = os.date }
  env = setmetatable({
    os = sandbox_os,
    bmd = mock_bmd,
    resolve = resolve_mock,
    fusion = fusion_mock,
    print = print,
  }, {
    __index = function(_, k)
      if gone[k] then return nil end
      return _G[k]
    end,
  })
  -- Chunks loaded from inside get the same sandbox, as in Resolve.
  env.loadfile = function(path)
    local chunk, err = loadfile(path)
    if chunk then setfenv(chunk, env) end
    return chunk, err
  end
  env._G = env
else
  env = setmetatable({ resolve = resolve_mock, fusion = fusion_mock,
                       bmd = setmetatable({}, { __index = function(_, k)
                         return mock_bmd[k] or real_bmd[k] end }) },
                     { __index = _G })
end

local chunk = assert(loadfile(LAUNCHER))
setfenv(chunk, env)
local ok, err = pcall(chunk)
if not ok then
  print("HARNESS FAILED: " .. tostring(err))
  os.exit(3)
end
print(string.format("HARNESS DONE saves=%d owner=%s", saves, tostring(prefs.Owner)))
