# Chrono Trace Packaging

## Build flow

1. Build the frontend into `frontend/webdist`
2. Freeze `app.py` with PyInstaller using `packaging/chrono_trace.spec`
3. Build the installer with Inno Setup using `packaging/ChronoTrace.iss`

## One-command build

```powershell
.\packaging\build_release.ps1
```

## Optional WebView2 bootstrapper

If you want the installer to bootstrap WebView2 automatically when it is missing, place:

```text
packaging\third_party\MicrosoftEdgeWebview2Setup.exe
```

The Inno Setup script detects the file and wires it into the install flow automatically.
