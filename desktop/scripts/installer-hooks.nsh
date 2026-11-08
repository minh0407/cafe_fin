; Tauri includes this BEFORE MAINBINARYNAME/UpdateMode are defined. Expand later.
!include "${__FILEDIR__}\startup-cleanup.nsh"

!macro NSIS_HOOK_POSTUNINSTALL
  ; An update removes/replaces files too; retain the user's startup opt-in there.
  StrCmp $UpdateMode 1 cf_startup_hook_done
  !insertmacro CF_CLEANUP_OWNED_STARTUP "Software\Microsoft\Windows\CurrentVersion\Run"
cf_startup_hook_done:
!macroend
