/**
 * Polish. Keys are the English phrases exactly as the code writes them (see
 * i18n.tsx); a missing key just shows the English.
 *
 * Editing jargon stays in English, the way Polish editors say it: timeline
 * (na timeline, timeline’u, na timelinie), playhead, bin (binu), and the
 * Sharp / Blend / Optical Flow modes. log = dziennik. Menu paths inside
 * Resolve and Premiere stay in English too: Resolve has no Polish UI, and
 * most Premiere installs here run in English.
 */

export const PL: Record<string, string> = {
  // ---- main window ----
  "<b>YEETingus {version}</b> is out. You have {current}.": "Jest już <b>YEETingus {version}</b>. Masz {current}.",
  "Download": "Pobierz",
  "What's new": "Co nowego",
  "Hide until the next version": "Ukryj do następnej wersji",
  "Quality": "Jakość",
  "Best available": "Najlepsza dostępna",
  "Insert at": "Wstaw na",
  "Playhead": "Playhead",
  "Start": "Początek",
  "Idle": "Gotowy",
  "Getting tools ready…": "Przygotowuję narzędzia…",
  "Queue": "Kolejka",
  "Queue links and download several at once. Queued clips are downloaded only; YEET them from the clips list.":
    "Dodawaj linki do kolejki i pobieraj kilka naraz. Klipy z kolejki są tylko pobierane; YEETnij je potem z listy klipów.",
  "Stop": "Zatrzymaj",
  "Connect Premiere (open the YEETingus panel) first — or use Download only":
    "Najpierw połącz Premiere (otwórz panel YEETingus) — albo użyj „Tylko pobierz”",
  "Connect Resolve (open a project and timeline) first — or use Download only":
    "Najpierw połącz Resolve (otwórz projekt i timeline) — albo użyj „Tylko pobierz”",
  "YEET into timeline": "YEET na timeline",
  "Download only": "Tylko pobierz",
  "Add to queue": "Dodaj do kolejki",
  "Queued clips download side by side, without inserting. YEET them from the clips list when they're done.":
    "Klipy z kolejki pobierają się równolegle, bez wstawiania. YEETnij je z listy klipów, gdy będą gotowe.",

  // ---- top bar and log ----
  "Service not connected": "Brak połączenia z usługą",
  "Connecting…": "Łączę…",
  "Re-check the connection to {editor}": "Sprawdź ponownie połączenie z {editor}",
  "Hide log": "Ukryj dziennik",
  "Show log": "Pokaż dziennik",
  "Settings": "Ustawienia",
  "Light theme": "Jasny motyw",
  "Dark theme": "Ciemny motyw",
  "LOG": "DZIENNIK",
  "clear": "wyczyść",

  // ---- first run ----
  "Welcome to {app}": "Witaj w {app}",
  "Paste a link, pick a range, press YEET — the clip lands on your timeline. Which timeline?":
    "Wklej link, wybierz fragment, naciśnij YEET — klip ląduje na timelinie. W którym programie?",
  "Studio or Free · straight onto your timeline": "Studio lub Free · prosto na timeline",
  "25+ · through a small panel": "25+ · przez mały panel",
  "You can change this any time in Settings.": "Możesz to zmienić w każdej chwili w Ustawieniach.",
  "Skip": "Pomiń",
  "YEETingus puts clips on Resolve's timeline itself. How depends on your version:":
    "YEETingus sam kładzie klipy na timeline w Resolve. Jak — zależy od wersji:",
  "<b>Studio:</b> turn external scripting on, once: <code>Preferences → System → General → External scripting using → Local</code>.":
    "<b>Studio:</b> włącz zewnętrzne skrypty, jednorazowo: <code>Preferences → System → General → External scripting using → Local</code>.",
  "<b>Free:</b> there's no external scripting, so YEETingus runs a small bridge inside Resolve. Add the menu entry below and restart Resolve. Then, each time you open Resolve, start YEETingus and click <code>Workspace → Scripts → YEETingus</code>.":
    "<b>Free:</b> nie ma zewnętrznych skryptów, więc YEETingus uruchamia mały skrypt-pośrednik wewnątrz Resolve. Dodaj poniżej pozycję w menu i uruchom ponownie Resolve. Potem, za każdym razem gdy otwierasz Resolve, włącz YEETingus i kliknij <code>Workspace → Scripts → YEETingus</code>.",
  "<b>The Scripts menu entry.</b> Free needs it. On Studio it's optional: it opens YEETingus from inside Resolve.":
    "<b>Pozycja w menu Scripts.</b> We Free jest niezbędna. W Studio jest opcjonalna: otwiera YEETingus z wnętrza Resolve.",
  "re-check": "sprawdź ponownie",
  "Back": "Wstecz",
  "Done": "Gotowe",
  "Premiere has no way for another program to reach it, so YEETingus puts a tiny panel inside Premiere and talks to that. One-time setup:":
    "Do Premiere inny program nie ma jak się dostać, więc YEETingus instaluje w nim mały panel i rozmawia z nim. Jednorazowa konfiguracja:",
  "Install the panel.": "Zainstaluj panel.",
  "YEETingus hands it to Adobe's own plugin installer; nothing else to do.":
    "YEETingus przekazuje go instalatorowi wtyczek Adobe; nic więcej nie trzeba robić.",
  "Adobe's plugin installer wasn't found — it comes with Creative Cloud desktop 5.5 or newer.":
    "Nie znaleziono instalatora wtyczek Adobe — jest częścią Creative Cloud Desktop 5.5 lub nowszego.",
  "Installing…": "Instaluję…",
  "Installed ({version}) — reinstall": "Zainstalowany ({version}) — zainstaluj ponownie",
  "Install the Premiere panel": "Zainstaluj panel Premiere",
  "In Premiere: <code>Window → UXP Plugins → YEETingus</code>. <b>Dock it</b> anywhere small and <b>save your workspace</b> — Premiere then brings it back on every launch.":
    "W Premiere: <code>Window → UXP Plugins → YEETingus</code>. <b>Zadokuj go</b> w dowolnym małym miejscu i <b>zapisz obszar roboczy</b> — Premiere przywróci go przy każdym uruchomieniu.",
  "Keep YEETingus running while you edit. The panel finds it by itself and shows a green dot. (Premiere doesn't let a panel start a program — that one's on Adobe.)":
    "Trzymaj YEETingus włączony podczas montażu. Panel sam go znajdzie i pokaże zieloną kropkę. (Premiere nie pozwala panelowi uruchomić programu — to już sprawa Adobe.)",
  "Panel connected · Premiere {version}": "Panel połączony · Premiere {version}",
  "Panel installed, not open in Premiere yet": "Panel zainstalowany, ale jeszcze nie otwarty w Premiere",
  "Panel not installed": "Panel niezainstalowany",

  // ---- Resolve menu entry ----
  "Adding…": "Dodaję…",
  "Update the Resolve menu entry": "Zaktualizuj pozycję w menu Resolve",
  "Re-add to Resolve's Scripts menu": "Dodaj ponownie do menu Scripts w Resolve",
  "Add to Resolve's Scripts menu": "Dodaj do menu Scripts w Resolve",
  "Menu": "Menu",
  "Resolve's Scripts folder not found — is Resolve installed for this user?":
    "Nie znaleziono folderu Scripts Resolve — czy Resolve jest zainstalowany dla tego użytkownika?",
  "entry is out of date — update it": "pozycja jest nieaktualna — zaktualizuj ją",
  "in Workspace → Scripts → Utility": "w Workspace → Scripts → Utility",
  "not in Resolve's menu yet": "jeszcze nie ma go w menu Resolve",
  "Needed on Resolve Free: clicking it starts the bridge that inserts your clips. On Studio it just opens YEETingus. Resolve reads its menu at startup, so restart it afterwards.":
    "Niezbędne w Resolve Free: kliknięcie uruchamia skrypt-pośrednik, który wstawia klipy. W Studio tylko otwiera YEETingus. Resolve wczytuje menu przy starcie, więc uruchom go potem ponownie.",

  // ---- preview, queue, clips ----
  "No thumbnail": "Brak miniatury",
  "Entire video": "Cały film",
  "from {start}": "od {start}",
  "Clip {n}": "Klip {n}",
  "Clip": "Klip",
  "{n} left": "zostało: {n}",
  "all done": "wszystko gotowe",
  "Clear finished": "Wyczyść zakończone",
  "Bin: {bin}": "Bin: {bin}",
  "Stop this download": "Zatrzymaj to pobieranie",
  "Remove from the queue": "Usuń z kolejki",
  "Remove from the list": "Usuń z listy",
  "Looking it up…": "Sprawdzam…",
  "Unknown title": "Nieznany tytuł",
  "Unknown channel": "Nieznany kanał",
  "Age restricted — YouTube needs a signed-in session, so this can't be downloaded.":
    "Ograniczenie wiekowe — YouTube wymaga zalogowania, więc tego filmu nie da się pobrać.",
  "Ready": "Gotowe",
  "Checking…": "Sprawdzam…",
  "Clear link": "Wyczyść link",
  "Clips": "Klipy",
  "Show all clips": "Pokaż wszystkie klipy",
  "Done selecting": "Zakończ zaznaczanie",
  "Select clips to YEET into the timeline": "Zaznacz klipy do YEETnięcia na timeline",
  "Select clips to delete": "Zaznacz klipy do usunięcia",
  "Open the {bin} folder": "Otwórz folder {bin}",
  "Open clips folder": "Otwórz folder klipów",
  "Refresh": "Odśwież",
  "Your downloaded clips will appear here.": "Tu pojawią się pobrane klipy.",
  "Search title, channel, bin…": "Szukaj po tytule, kanale, binie…",
  "No clips match “{q}”": "Żaden klip nie pasuje do „{q}”",
  "Click to copy the title": "Kliknij, aby skopiować tytuł",
  "copied": "skopiowano",
  "Show only the {bin} bin": "Pokaż tylko bin {bin}",
  "Click to copy the channel": "Kliknij, aby skopiować nazwę kanału",
  "YEET into the timeline": "YEET na timeline",
  "Play in your video player": "Odtwórz w odtwarzaczu wideo",
  "Copy the video's link": "Skopiuj link do filmu",
  "Source link unknown for this clip": "Link źródłowy tego klipu jest nieznany",
  "Open folder": "Otwórz folder",
  "Select none": "Odznacz wszystko",
  "Select all": "Zaznacz wszystko",
  "{n} selected": "zaznaczono: {n}",
  "Cancel": "Anuluj",
  "Delete 1 clip from disk?": "Usunąć 1 klip z dysku?",
  "Delete {n} clips from disk?": "Usunąć klipy z dysku? (liczba: {n})",
  "Delete": "Usuń",
  "Keep": "Zostaw",
  "Wait for the queue to finish downloading": "Poczekaj, aż kolejka skończy pobieranie",

  // ---- settings ----
  "Choose where clips are saved": "Wybierz, gdzie zapisywać klipy",
  "Close": "Zamknij",
  "Editor": "Program do montażu",
  "Where YEET pastes the clip.": "Gdzie YEET wkleja klip.",
  "Premiere is driven through a small YEETingus panel inside it. Install it once, open it from <b>Window → UXP Plugins → YEETingus</b>, dock it and save your workspace — Premiere then brings it back every launch. Keep YEETingus running; the panel connects by itself.":
    "Premiere jest sterowany przez mały panel YEETingus w jego wnętrzu. Zainstaluj go raz, otwórz przez <b>Window → UXP Plugins → YEETingus</b>, zadokuj i zapisz obszar roboczy — Premiere przywróci go przy każdym uruchomieniu. Trzymaj YEETingus włączony; panel połączy się sam.",
  "Panel": "Panel",
  "checking…": "sprawdzam…",
  "not installed": "niezainstalowany",
  "installed ({version})": "zainstalowany ({version})",
  "open in Premiere {version}": "otwarty w Premiere {version}",
  "not open in Premiere": "nieotwarty w Premiere",
  "Installer": "Instalator",
  "Adobe's plugin installer found": "znaleziono instalator wtyczek Adobe",
  "Adobe's plugin installer not found (needs Creative Cloud 5.5+)": "nie znaleziono instalatora wtyczek Adobe (wymaga Creative Cloud 5.5+)",
  "Reinstall the Premiere panel": "Zainstaluj ponownie panel Premiere",
  "Default clip length": "Domyślna długość klipu",
  "End point set from the in point when the app opens.": "Koniec ustawiany od początku po uruchomieniu aplikacji.",
  "Clip storage": "Miejsce na klipy",
  "Downloaded clips are saved here.": "Tu zapisywane są pobrane klipy.",
  "Choose the folder": "Wybierz folder",
  "Existing clips are left where they are.": "Istniejące klipy zostają tam, gdzie są.",
  "Language": "Język",
  "Auto follows your system.": "Auto — według języka systemu.",
  "Auto": "Auto",
  "Frame rate": "Liczba klatek",
  "What happens when a clip's frame rate differs from the timeline's.": "Co się dzieje, gdy klip ma inną liczbę klatek na sekundę niż timeline.",
  "Sharp": "Sharp",
  "Blend": "Blend",
  "Optical Flow": "Optical Flow",
  "Off": "Wył.",
  "<b>Sharp</b> and <b>Blend</b> convert the file here, once, to the timeline's rate: Sharp keeps every frame crisp (a 60 fps clip on 24p gets the same 2-3 pulldown any NLE gives it), Blend mixes neighbouring frames, smoother but ghosted on fast footage.":
    "<b>Sharp</b> i <b>Blend</b> przeliczają plik tutaj, raz, na klatkaż timeline’u: Sharp zostawia każdą klatkę wyraźną (klip 60 fps na timelinie 24p dostaje ten sam pulldown 2-3, co w każdym programie do montażu), Blend łączy sąsiednie klatki — płynniej, ale z duchami przy szybkim ruchu.",
  "<b>Optical Flow</b> keeps the file as is and has Resolve retime it, smooth <i>and</i> sharp, but GPU-heavy.":
    "<b>Optical Flow</b> zostawia plik bez zmian i każe Resolve go przeliczyć — płynnie <i>i</i> ostro, ale mocno obciąża GPU.",
  "<b>Off</b> inserts the clip at its own rate and lets the editor cope.":
    "<b>Wył.</b> wstawia klip z jego własnym klatkażem i zostawia resztę programowi do montażu.",
  "Tools": "Narzędzia",
  "What YEETingus found on this machine.": "Co YEETingus znalazł na tym komputerze.",
  "video": "wideo",
  "UNSUPPORTED": "NIEOBSŁUGIWANY",
  "library": "biblioteka",
  "found": "znaleziona",
  "MISSING": "BRAK",
  "Update yt-dlp": "Zaktualizuj yt-dlp",
  "Install JavaScript runtime (Deno)": "Zainstaluj środowisko JavaScript (Deno)",
  "Install ffmpeg (Homebrew)": "Zainstaluj ffmpeg (Homebrew)",
  "{version} is out, download": "jest {version}, pobierz",
  "up to date": "aktualna",
  "Check for updates": "Sprawdzaj aktualizacje",
  "Asks GitHub for the latest release when the app starts and every few hours. Nothing else is sent.":
    "Pyta GitHub o najnowsze wydanie przy starcie aplikacji i co kilka godzin. Nic więcej nie jest wysyłane.",
  "Check now": "Sprawdź teraz",
  "Couldn't save: {error}": "Nie udało się zapisać: {error}",
  "Save": "Zapisz",

  // ---- source ----
  "Source": "Źródło",
  "Paste a video link…": "Wklej link do filmu…",
  "Bin": "Bin",
  "None — straight into the clips folder": "Brak — prosto do folderu klipów",
  "A folder inside the clips folder for one project's clips, e.g. Friday video.\nLeave it empty for no bin. It stays filled in until you change it.":
    "Folder w folderze klipów na klipy z jednego projektu, np. Piątkowy film.\nZostaw puste, jeśli bez binu. Wpis zostaje, dopóki go nie zmienisz.",
  "Use today's date as the bin": "Użyj dzisiejszej daty jako nazwy binu",
  "Today": "Dziś",
  "In point": "Początek",
  "Leave both points at 00:00 to download the entire video.\nOtherwise the end point follows automatically, using the default clip length from Settings.":
    "Zostaw oba punkty na 00:00, żeby pobrać cały film.\nW przeciwnym razie koniec ustawi się sam, według domyślnej długości klipu z Ustawień.",
  "End point": "Koniec",
  "Leave both points at 00:00 to download the entire video.": "Zostaw oba punkty na 00:00, żeby pobrać cały film.",
  "Clip length from in point": "Długość klipu od początku",
  "Reset both points to 00:00 — downloads the whole video.": "Ustaw oba punkty na 00:00 — pobiera cały film.",
  "Whole": "Całość",
  "Pick a length": "Wybierz długość",
  "Any length up to 5 minutes": "Dowolna długość do 5 minut",
  "Use the link's ?t= timestamp as the in point": "Użyj znacznika ?t= z linku jako początku",
  "From link": "Z linku",
  "Clip length": "Długość klipu",
  "mm:ss, hh:mm:ss or seconds · both at 00:00 = entire video": "mm:ss, hh:mm:ss lub sekundy · oba na 00:00 = cały film",
  "Clear": "Wyczyść",
};

/** What the service says, word for word. */
export const SERVER_PL: Record<string, string> = {
  // connection pill
  "checking…": "sprawdzam…",
  "missing tools": "brak narzędzi",
  "ffmpeg missing": "brak ffmpeg",
  "no timeline open": "brak otwartego timeline’u",
  "no project open": "brak otwartego projektu",
  "Resolve not connected": "Resolve niepołączony",
  "Resolve error": "błąd Resolve",
  "Premiere panel not open": "panel Premiere nie jest otwarty",
  "Premiere error": "błąd Premiere",
  // progress and queue steps
  "Stopping…": "Zatrzymuję…",
  "Stopped": "Zatrzymano",
  "Preparing…": "Przygotowuję…",
  "Prepared": "Przygotowano",
  "Reading video info…": "Czytam dane filmu…",
  "Age restricted — can't download": "Ograniczenie wiekowe — nie da się pobrać",
  "Nothing to download — see log": "Nic do pobrania — zobacz dziennik",
  "Failed — see log": "Niepowodzenie — zobacz dziennik",
  "Resolve error — see log": "Błąd Resolve — zobacz dziennik",
  "Premiere error — see log": "Błąd Premiere — zobacz dziennik",
  "Queued": "W kolejce",
  "Starting…": "Uruchamiam…",
  "Retrying…": "Ponawiam…",
  "Done": "Gotowe",
  "Cancelled": "Anulowano",
  "Using existing download…": "Używam wcześniej pobranego pliku…",
  "Preparing download…": "Przygotowuję pobieranie…",
  "Downloading…": "Pobieram…",
  "Merging & trimming…": "Łączę i przycinam…",
  // tools
  "not found": "nie znaleziono",
  "not checked": "nie sprawdzono",
  // install results
  "Added. Restart Resolve, then it's under Workspace → Scripts → Utility → YEETingus.":
    "Dodano. Uruchom ponownie Resolve — pozycja będzie w Workspace → Scripts → Utility → YEETingus.",
  "Panel installed. In Premiere: Window → UXP Plugins → YEETingus, dock it, save the workspace — it's there from then on.":
    "Panel zainstalowany. W Premiere: Window → UXP Plugins → YEETingus, zadokuj go i zapisz obszar roboczy — od tej pory będzie na miejscu.",
  // the app's own connection to the service (useEngine)
  "Lost the connection to the service; reconnecting…": "Utracono połączenie z usługą; łączę ponownie…",
};

/** What the service says with a number or a name in it. */
export const SERVER_PL_PATTERNS: [RegExp, (m: RegExpExecArray) => string][] = [
  [/^Downloading… ([\d.]+)%$/, (m) => `Pobieram… ${m[1]}%`],
  [/^Preparing… (\d+)%$/, (m) => `Przygotowuję… ${m[1]}%`],
  [/^Pasting into timeline…( \(\d+\/\d+\))?$/, (m) => `Wklejam na timeline…${m[1] ?? ""}`],
  [/^Done — (\d+) clips$/, (m) => `Gotowe — klipy: ${m[1]}`],
  [/^Done — (.+)$/, (m) => `Gotowe — ${m[1]}`],
  [/^(.+) · no sequence open$/, (m) => `${m[1]} · brak otwartej sekwencji`],
  [/^(.*)not found$/, (m) => `${m[1]}nie znaleziono`],
  [/^Couldn't start the service: (.*)$/s, (m) => `Nie udało się uruchomić usługi: ${m[1]}`],
  [/^no hardware AV1 encoder — converting on the CPU \(MPEG-4\)(.*)$/,
    (m) => `brak sprzętowego kodera AV1 — konwersja na CPU (MPEG-4)${m[1].replace("HEVC for Premiere", "HEVC dla Premiere")}`],
  [/^hardware AV1 encoder: (.*)$/,
    (m) => `sprzętowy koder AV1: ${m[1].replace("HEVC for Premiere", "HEVC dla Premiere")}`],
];
