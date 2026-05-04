using System.Diagnostics;
using System.Text;

namespace VideoEnhancer.Core;

public sealed class FfmpegJobRunner
{
    public async Task<int> RunAsync(
        EnhancementRequest request,
        TimeSpan? duration = null,
        IProgress<FfmpegProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        IReadOnlyList<string> command = FfmpegCommandBuilder.BuildCommand(request);
        List<string> arguments = command.Skip(1).ToList();
        arguments.InsertRange(2, ["-nostats", "-progress", "pipe:1"]);

        ProcessStartInfo startInfo = new()
        {
            FileName = command[0],
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        foreach (string argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using Process process = new() { StartInfo = startInfo, EnableRaisingEvents = true };
        StringBuilder stderr = new();
        FfmpegProgressParser parser = new(duration);

        process.Start();
        Task outputTask = Task.Run(async () =>
        {
            while (!process.StandardOutput.EndOfStream)
            {
                string? line = await process.StandardOutput.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is not null && parser.ParseLine(line) is { } parsed)
                {
                    progress?.Report(parsed);
                }
            }
        }, cancellationToken);
        Task errorTask = Task.Run(async () =>
        {
            while (!process.StandardError.EndOfStream)
            {
                string? line = await process.StandardError.ReadLineAsync(cancellationToken).ConfigureAwait(false);
                if (line is not null)
                {
                    stderr.AppendLine(line);
                }
            }
        }, cancellationToken);

        try
        {
            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            await Task.WhenAll(outputTask, errorTask).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
            }

            throw;
        }

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException($"FFmpeg failed with exit code {process.ExitCode}.{Environment.NewLine}{stderr}");
        }

        return process.ExitCode;
    }
}
