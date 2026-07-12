Set sh = CreateObject("WScript.Shell")
installDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
bat = installDir & "Run-PeechaSync.bat"
sh.Run "cmd /c """ & bat & """ internal", 0, False
