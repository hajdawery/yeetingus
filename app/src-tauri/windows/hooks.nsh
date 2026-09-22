; An orphaned yeetingus-service.exe (left by a force-killed app) keeps its
; exe locked, and the installer then leaves the OLD service in place next to
; a new app. Stop any running copy before files are written.
!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec 'taskkill /F /T /IM yeetingus-service.exe'
  Sleep 500
!macroend

; Same on uninstall: a running service would keep its folder locked.
!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /T /IM yeetingus-service.exe'
  Sleep 500
!macroend
