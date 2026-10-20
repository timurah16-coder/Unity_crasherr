# Unity Crasher

Windows tray utility for testing crashes in your own Unity Editor project.
Requires Windows 10+, Python 3.10+ and requirements.txt dependencies.

## Setup

Copy UnityCrasherBridge.cs into the project's Assets/Editor folder and allow Unity to compile.

Double-click start.cmd. First launch creates .venv and installs dependencies. A lightning icon appears in the tray. Duplicate launches silently keep the running instance.

Unity.exe processes are detected every two seconds. One process is selected automatically. With several processes, choose one in the tray menu. Press Num Lock to request a crash silently, without confirmation. Unsaved changes may be lost. Exit from the tray menu.

## Behavior

The Editor-only helper calls UnityEngine.Diagnostics.Utils.ForceCrash(ForcedCrashCategory.AccessViolation) on the Editor thread. This invokes Unity's own test crash mechanism, instead of a breakpoint. No specific crash dialog is guaranteed. Unity must finish compiling and be responsive enough to run Editor update callbacks.

The log records the request and process exit separately. If exit is not confirmed after five seconds, a warning is logged. A missing or stale bridge is an error. Process identity and a per-reload token prevent stale requests. Requests expire after ten seconds. Hotkey actions have no notifications.

Only Unity Editor projects with the helper are supported. For another project copy the helper into Assets/Editor. Removing it disables external crash requests. The helper is excluded from game builds.

Log: unity_crasher.log. Local bridge files: %LOCALAPPDATA%\UnityCrasher.

https://docs.unity3d.com/ScriptReference/Diagnostics.Utils.ForceCrash.html

## Manual setup

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe unity_crasher.py
```
