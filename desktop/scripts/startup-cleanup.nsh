; Unicode NSIS; fixed CafeFin value name, current-user only, no key creation.
; The subkey is a compile-time parameter solely so CI can use an isolated test key.
!macro CF_CLEANUP_OWNED_STARTUP RUN_SUBKEY
  System::Store "sF"
  StrCpy $0 0 ; transaction
  StrCpy $1 0 ; transacted key
  StrCpy $4 0 ; expected raw UTF16 buffer
  StrCpy $5 0 ; actual raw buffer
  StrCpy $6 '$\"$INSTDIR\${MAINBINARYNAME}.exe$\" --startup-v1'
  StrLen $3 $6
  IntCmp $3 260 0 0 cf_startup_cleanup
  IntOp $3 $3 + 1 ; include exactly one UTF16 NUL
  IntOp $2 $3 * 2
  System::Call 'KtmW32::CreateTransaction(p 0, p 0, i 0, i 0, i 0, i 5000, p 0) p.r0'
  StrCmp $0 -1 cf_startup_invalid_transaction
  StrCmp $0 0 cf_startup_cleanup
  ; KEY_QUERY_VALUE | KEY_SET_VALUE | KEY_WOW64_64KEY. HKCU Software is shared.
  System::Call 'Advapi32::RegOpenKeyTransactedW(p 0x80000001, w "${RUN_SUBKEY}", i 0, i 0x103, *p.r1, p r0, p 0) i.r9'
  StrCmp $9 0 cf_startup_opened
  StrCpy $1 0
  Goto cf_startup_cleanup
cf_startup_opened:
  System::Call 'Advapi32::RegQueryValueExW(p r1, w "CafeFin", p 0, *i.r7, p 0, *i.r8) i.r9'
  StrCmp $9 0 0 cf_startup_cleanup
  StrCmp $7 1 0 cf_startup_cleanup ; REG_SZ only, not REG_EXPAND_SZ
  StrCmp $8 $2 0 cf_startup_cleanup ; no missing/extra terminator or extra bytes
  System::Call '*(&w$3 r6) p.r4'
  StrCmp $4 0 cf_startup_cleanup
  System::Alloc $2
  Pop $5
  StrCmp $5 0 cf_startup_cleanup
  System::Call 'Advapi32::RegQueryValueExW(p r1, w "CafeFin", p 0, *i.r7, p r5, *i r8 .r8) i.r9'
  StrCmp $9 0 0 cf_startup_cleanup
  StrCmp $7 1 0 cf_startup_cleanup
  StrCmp $8 $2 0 cf_startup_cleanup
  ; Explicit lengths INCLUDE NUL; FALSE forbids case folding/linguistic equality.
  ; Never convert the untrusted raw value through an NSIS string buffer.
  System::Call 'Kernel32::CompareStringOrdinal(p r4, i r3, p r5, i r3, i 0) i.r9'
  StrCmp $9 2 0 cf_startup_cleanup
  System::Call 'Advapi32::RegDeleteValueW(p r1, w "CafeFin") i.r9'
  StrCmp $9 0 0 cf_startup_cleanup
  System::Call 'Advapi32::RegCloseKey(p r1) i.r9'
  StrCpy $1 0
  StrCmp $9 0 0 cf_startup_cleanup
  System::Call 'KtmW32::CommitTransaction(p r0) i.r9'
  StrCmp $9 1 0 cf_startup_cleanup
  StrCpy $6 "COMMITTED"
  Goto cf_startup_cleanup
cf_startup_invalid_transaction:
  StrCpy $0 0
cf_startup_cleanup:
  StrCmp $1 0 +2
    System::Call 'Advapi32::RegCloseKey(p r1)'
  StrCmp $0 0 cf_startup_free_buffers
  StrCmpS $6 "COMMITTED" +2
    System::Call 'KtmW32::RollbackTransaction(p r0)'
  System::Call 'Kernel32::CloseHandle(p r0)'
cf_startup_free_buffers:
  StrCmp $4 0 +2
    System::Free $4
  StrCmp $5 0 +2
    System::Free $5
  System::Store "fl"
!macroend
