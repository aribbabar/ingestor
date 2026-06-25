!macro NSIS_HOOK_POSTINSTALL
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$dir = Join-Path ''$INSTDIR'' ''binaries''; $path = [Environment]::GetEnvironmentVariable(''Path'', ''User''); $parts = @($path -split '';'' | Where-Object { $_ }); if (-not ($parts | Where-Object { $_ -ieq $dir })) { $parts += $dir; [Environment]::SetEnvironmentVariable(''Path'', ($parts -join '';''), ''User'') }"'
  System::Call 'user32::SendMessageTimeoutW(i 0xffff, i 0x1A, i 0, w "Environment", i 0, i 5000, *i .r0)'
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$dir = Join-Path ''$INSTDIR'' ''binaries''; $path = [Environment]::GetEnvironmentVariable(''Path'', ''User''); $parts = @($path -split '';'' | Where-Object { $_ -and ($_ -ine $dir) }); [Environment]::SetEnvironmentVariable(''Path'', ($parts -join '';''), ''User'')"'
  System::Call 'user32::SendMessageTimeoutW(i 0xffff, i 0x1A, i 0, w "Environment", i 0, i 5000, *i .r0)'
!macroend
