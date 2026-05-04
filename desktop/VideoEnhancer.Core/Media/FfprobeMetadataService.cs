using System.Diagnostics;
using System.Globalization;
using System.Text.Json;

namespace VideoEnhancer.Core;

public sealed class FfprobeMetadataService
{
    public async Task<MediaInfo> GetMediaInfoAsync(
        string inputPath,
        string? ffprobePath = null,
        CancellationToken cancellationToken = default)
    {
        string executable = FfmpegLocator.FindFfprobe(ffprobePath)
            ?? throw new FileNotFoundException("ffprobe was not found.", ffprobePath ?? "ffprobe");

        ProcessStartInfo startInfo = new()
        {
            FileName = executable,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (string argument in new[]
        {
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            inputPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }

        using Process process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start ffprobe.");
        string json = await process.StandardOutput.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
        string error = await process.StandardError.ReadToEndAsync(cancellationToken).ConfigureAwait(false);
        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException($"ffprobe failed with exit code {process.ExitCode}.{Environment.NewLine}{error}");
        }

        return Parse(inputPath, json);
    }

    public static MediaInfo Parse(string inputPath, string json)
    {
        using JsonDocument document = JsonDocument.Parse(json);
        JsonElement root = document.RootElement;
        JsonElement? video = FindStream(root, "video");
        JsonElement? audio = FindStream(root, "audio");
        JsonElement? format = root.TryGetProperty("format", out JsonElement formatElement) ? formatElement : null;

        return new MediaInfo
        {
            Path = inputPath,
            Duration = ParseDuration(video) ?? ParseDuration(format),
            Width = GetInt(video, "width"),
            Height = GetInt(video, "height"),
            FramesPerSecond = ParseRate(GetString(video, "avg_frame_rate") ?? GetString(video, "r_frame_rate")),
            VideoCodec = GetString(video, "codec_name"),
            AudioCodec = GetString(audio, "codec_name"),
            BitRate = GetLong(format, "bit_rate") ?? GetLong(video, "bit_rate"),
        };
    }

    private static JsonElement? FindStream(JsonElement root, string codecType)
    {
        if (!root.TryGetProperty("streams", out JsonElement streams) || streams.ValueKind != JsonValueKind.Array)
        {
            return null;
        }

        foreach (JsonElement stream in streams.EnumerateArray())
        {
            if (GetString(stream, "codec_type") == codecType)
            {
                return stream;
            }
        }

        return null;
    }

    private static TimeSpan? ParseDuration(JsonElement? element)
    {
        string? value = GetString(element, "duration");
        return double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double seconds)
            ? TimeSpan.FromSeconds(seconds)
            : null;
    }

    private static double? ParseRate(string? value)
    {
        if (string.IsNullOrWhiteSpace(value) || value == "0/0")
        {
            return null;
        }

        string[] parts = value.Split('/');
        if (parts.Length == 2
            && double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out double numerator)
            && double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out double denominator)
            && denominator != 0)
        {
            return numerator / denominator;
        }

        return double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double parsed)
            ? parsed
            : null;
    }

    private static string? GetString(JsonElement? element, string property)
    {
        if (element is null || !element.Value.TryGetProperty(property, out JsonElement value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() : value.ToString();
    }

    private static int? GetInt(JsonElement? element, string property)
    {
        return element is not null
            && element.Value.TryGetProperty(property, out JsonElement value)
            && value.TryGetInt32(out int parsed)
            ? parsed
            : null;
    }

    private static long? GetLong(JsonElement? element, string property)
    {
        string? value = GetString(element, property);
        return long.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out long parsed)
            ? parsed
            : null;
    }
}
