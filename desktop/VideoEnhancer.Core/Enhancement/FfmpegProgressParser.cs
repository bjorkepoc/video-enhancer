using System.Globalization;

namespace VideoEnhancer.Core;

public sealed class FfmpegProgressParser
{
    private readonly TimeSpan? _duration;
    private TimeSpan _outTime = TimeSpan.Zero;
    private double? _speed;
    private string? _state;

    public FfmpegProgressParser(TimeSpan? duration = null)
    {
        _duration = duration;
    }

    public FfmpegProgress? ParseLine(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            return null;
        }

        int separator = line.IndexOf('=');
        if (separator <= 0)
        {
            return null;
        }

        string key = line[..separator].Trim();
        string value = line[(separator + 1)..].Trim();

        switch (key)
        {
            case "out_time_ms" when long.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out long micros):
                _outTime = TimeSpan.FromMilliseconds(micros / 1000.0);
                return Snapshot();
            case "out_time" when TimeSpan.TryParse(value, CultureInfo.InvariantCulture, out TimeSpan outTime):
                _outTime = outTime;
                return Snapshot();
            case "speed":
                _speed = ParseSpeed(value);
                return Snapshot();
            case "progress":
                _state = value;
                return Snapshot();
            default:
                return null;
        }
    }

    private FfmpegProgress Snapshot()
    {
        double? percent = null;
        if (_duration is { TotalMilliseconds: > 0 })
        {
            percent = Math.Clamp(_outTime.TotalMilliseconds / _duration.Value.TotalMilliseconds * 100.0, 0, 100);
        }

        return new FfmpegProgress(_outTime, percent, _speed, _state);
    }

    private static double? ParseSpeed(string value)
    {
        string normalized = value.EndsWith('x') ? value[..^1] : value;
        return double.TryParse(normalized, NumberStyles.Float, CultureInfo.InvariantCulture, out double speed)
            ? speed
            : null;
    }
}

public sealed record FfmpegProgress(TimeSpan OutTime, double? Percent, double? Speed, string? State);
