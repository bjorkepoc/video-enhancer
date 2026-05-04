using System.Diagnostics;

namespace VideoEnhancer.Core;

public sealed class ThumbnailService
{
    public async Task CreateThumbnailAsync(
        string inputPath,
        string outputPath,
        TimeSpan? at = null,
        string? ffmpegPath = null,
        CancellationToken cancellationToken = default)
    {
        string executable = FfmpegLocator.FindFfmpeg(ffmpegPath)
            ?? throw new FileNotFoundException("FFmpeg was not found.", ffmpegPath ?? "ffmpeg");
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);

        ProcessStartInfo startInfo = new()
        {
            FileName = executable,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (string argument in new[]
        {
            "-hide_banner",
            "-y",
            "-ss",
            FormatTimestamp(at ?? TimeSpan.FromSeconds(1)),
            "-i",
            inputPath,
            "-frames:v",
            "1",
            outputPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }

        using Process process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start FFmpeg.");
        string error = await process.StandardError.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException($"FFmpeg thumbnail failed with exit code {process.ExitCode}.{Environment.NewLine}{error}");
        }
    }

    private static string FormatTimestamp(TimeSpan timestamp)
    {
        return timestamp.ToString(@"hh\:mm\:ss\.fff");
    }
}
