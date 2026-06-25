Var IngestorAddToPath

${UnStrCase}
${UnStrLoc}

!macro NSIS_HOOK_PREINSTALL
  StrCpy $IngestorAddToPath 1
  ${If} $PassiveMode <> 1
  ${AndIfNot} ${Silent}
    MessageBox MB_ICONQUESTION|MB_YESNO|MB_DEFBUTTON1 "Add the Ingestor command line tool to your user PATH?$\r$\n$\r$\nThis lets new terminal sessions run 'ingestor'." IDYES +2 IDNO 0
      StrCpy $IngestorAddToPath 0
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ${If} $IngestorAddToPath = 1
    Push "$INSTDIR\binaries"
    Call IngestorAddUserPath
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  Push "$INSTDIR\binaries"
  Call un.IngestorRemoveUserPath
!macroend

Function IngestorAddUserPath
  Exch $0
  Push $1
  Push $2
  Push $3
  Push $4

  ReadRegStr $1 HKCU "Environment" "Path"
  ${If} $1 == ""
    WriteRegExpandStr HKCU "Environment" "Path" "$0"
    Goto ingestor_add_done
  ${EndIf}

  ${StrCase} $2 "$1" "L"
  ${StrCase} $3 "$0" "L"
  ${StrLoc} $4 ";$2;" ";$3;" ">"
  ${If} $4 == ""
    WriteRegExpandStr HKCU "Environment" "Path" "$1;$0"
  ${EndIf}

  ingestor_add_done:
    System::Call 'user32::SendMessageTimeoutW(i 0xffff, i 0x1A, i 0, w "Environment", i 0, i 5000, *i .r4)'
    Pop $4
    Pop $3
    Pop $2
    Pop $1
    Pop $0
FunctionEnd

Function un.IngestorRemoveUserPath
  Exch $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  Push $6
  Push $7

  ReadRegStr $1 HKCU "Environment" "Path"
  StrCpy $2 ""
  ${UnStrCase} $6 "$0" "L"

  un.ingestor_remove_loop:
    ${If} $1 == ""
      Goto un.ingestor_remove_write
    ${EndIf}

    ${UnStrLoc} $3 "$1" ";" ">"
    ${If} $3 == ""
      StrCpy $4 "$1"
      StrCpy $1 ""
    ${Else}
      StrCpy $4 "$1" $3
      IntOp $3 $3 + 1
      StrCpy $1 "$1" "" $3
    ${EndIf}

    ${If} $4 == ""
      Goto un.ingestor_remove_loop
    ${EndIf}

    ${UnStrCase} $7 "$4" "L"
    ${If} $7 == $6
      Goto un.ingestor_remove_loop
    ${EndIf}

    ${If} $2 == ""
      StrCpy $2 "$4"
    ${Else}
      StrCpy $2 "$2;$4"
    ${EndIf}
    Goto un.ingestor_remove_loop

  un.ingestor_remove_write:
    WriteRegExpandStr HKCU "Environment" "Path" "$2"
    System::Call 'user32::SendMessageTimeoutW(i 0xffff, i 0x1A, i 0, w "Environment", i 0, i 5000, *i .r5)'
    Pop $7
    Pop $6
    Pop $5
    Pop $4
    Pop $3
    Pop $2
    Pop $1
    Pop $0
FunctionEnd
