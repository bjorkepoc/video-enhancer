namespace VideoEnhancer.Core;

public static class FfmpegLocator
{
    public static string? FindFfmpeg(string? preferredPath = null)
    {
        return FindExecutable("ffmpeg", preferredPath);
    }

    public static string? FindFfprobe(string? preferredPath = null)
    {
        return FindExecutable("ffprobe", preferredPath);
    }

    private static string? FindExecutable(string toolName, string? preferredPath)
    {
        string executableName = OperatingSystem.IsWindows() ? $"{toolName}.exe" : toolName;
        if (!string.IsNullOrWhiteSpace(preferredPath))
        {
            string candidate = preferredPath;
            if (File.Exists(candidate))
            {
                return Path.GetFullPath(candidate);
            }

            if (Path.GetFileName(candidate).Equals(toolName, StringComparison.OrdinalIgnoreCase) && OperatingSystem.IsWindows())
            {
                string withExtension = $"{candidate}.exe";
                if (File.Exists(withExtension))
                {
                    return Path.GetFullPath(withExtension);
                }
            }
        }

        foreach (string directory in PathEnvironmentDirectories())
        {
            string candidate = Path.Combine(directory, executableName);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return FindWingetGyanExecutable(executableName);
    }

    private static IEnumerable<string> PathEnvironmentDirectories()
    {
        string? path = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(path))
        {
            yield break;
        }

        foreach (string directory in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (Directory.Exists(directory))
            {
                yield return directory;
            }
        }
    }

    private static string? FindWingetGyanExecutable(string executableName)
    {
        if (!OperatingSystem.IsWindows())
        {
            return null;
        }

        string? localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            return null;
        }

        string packages = Path.Combine(localAppData, "Microsoft", "WinGet", "Packages");
        if (!Directory.Exists(packages))
        {
            return null;
        }

        try
        {
            return Directory.EnumerateFiles(packages, executableName, SearchOption.AllDirectories)
                .Where(path => path.Contains("Gyan.FFmpeg", StringComparison.OrdinalIgnoreCase))
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .FirstOrDefault();
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
    }
}
