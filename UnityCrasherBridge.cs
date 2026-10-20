#if UNITY_EDITOR && UNITY_EDITOR_WIN
using System;
using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEngine;

// Editor-only test helper. Removing this file disables external crash requests.
[InitializeOnLoad]
internal static class UnityCrasherBridge
{
    [Serializable] private class Endpoint
    {
        public int pid;
        public double started;
        public string token;
    }
    [Serializable] private class Request
    {
        public string token;
        public double requested;
    }

    private static readonly string Folder = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UnityCrasher");
    private static readonly int Pid = Process.GetCurrentProcess().Id;
    private static readonly string Ready = Path.Combine(Folder, Pid + ".ready.json");
    private static readonly string Signal = Path.Combine(Folder, Pid + ".request.json");
    private static readonly Endpoint Identity = new Endpoint
    {
        pid = Pid,
        started = (Process.GetCurrentProcess().StartTime.ToUniversalTime() -
                   new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds,
        token = Guid.NewGuid().ToString("N")
    };
    private static double nextPoll;
    private static double nextHeartbeat;

    static UnityCrasherBridge()
    {
        try
        {
            Directory.CreateDirectory(Folder);
            File.Delete(Signal);
            Publish();
            EditorApplication.update += Update;
            AssemblyReloadEvents.beforeAssemblyReload += Cleanup;
            EditorApplication.quitting += Cleanup;
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    private static void Publish()
    {
        File.WriteAllText(Ready, JsonUtility.ToJson(Identity));
    }

    private static void Cleanup()
    {
        EditorApplication.update -= Update;
        try { File.Delete(Ready); File.Delete(Signal); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    private static void Update()
    {
        double now = EditorApplication.timeSinceStartup;
        if (now < nextPoll) return;
        nextPoll = now + 0.1;
        try
        {
            if (now >= nextHeartbeat) { Publish(); nextHeartbeat = now + 2; }
            if (!File.Exists(Signal)) return;
            Request request = JsonUtility.FromJson<Request>(File.ReadAllText(Signal));
            File.Delete(Signal);
            double utc = (DateTime.UtcNow -
                new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
            if (request == null || request.token != Identity.token ||
                utc - request.requested < 0 || utc - request.requested > 10) return;
            UnityEngine.Diagnostics.Utils.ForceCrash(
                UnityEngine.Diagnostics.ForcedCrashCategory.AccessViolation);
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (ArgumentException) { }
    }
}
#endif
