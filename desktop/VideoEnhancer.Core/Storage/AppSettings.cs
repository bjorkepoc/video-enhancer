namespace VideoEnhancer.Core;

public sealed record AppSettings
{
    public string? FfmpegPath { get; init; }
    public string? FfprobePath { get; init; }
    public string DefaultPreset { get; init; } = "balanced";
    public string DefaultVideoCodec { get; init; } = "libx264";
    public string DefaultFilterBackend { get; init; } = "cpu";
    public double DefaultScaleFactor { get; init; } = 2.0;
    public int DefaultFps { get; init; } = 60;
    public int DefaultQuality { get; init; } = 16;
    public string? ExportDirectory { get; init; }
    public IReadOnlyList<string> RecentInputs { get; init; } = [];
}
