# OAS frontend preview

This folder is a preview launcher for the real frontend. The page itself is served from:

`D:\OSAyys\control-center\frontend`

That means changes to `control-center\frontend\src\App.jsx` and `src\styles.css` are the same changes that the portable build will package later. This folder does not contain a second production UI implementation.

## Start

```powershell
Set-Location D:\OSAyys\frontend-preview
.\start-preview.ps1
```

Open `http://127.0.0.1:4173/`.

The launcher runs the real Vite frontend and a local mock Bridge on port `22368`. The mock Bridge provides preview-only accounts, tasks, settings, window choices, logs, and action responses. It does not connect to OAS Core, write production configuration, bind a real window, or start a task.

## Portable build

After the UI is accepted, package the same frontend with:

```powershell
Set-Location D:\OSAyys\control-center\desktop
.\build.ps1 -SkipNpmInstall
```

The output is `OAS-Control-Center-0.1.0-portable.exe` under `control-center\desktop\release`.

`mockup-reference.html` is the previous static visual reference only. It is not used by the preview server or the portable build.
