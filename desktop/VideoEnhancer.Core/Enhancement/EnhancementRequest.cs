namespace VideoEnhancer.Core;

public sealed record EnhancementRequest
{
    public string InputPath { get; init; } = "";
    public string OutputPath { get; init; } = "";
    public string Preset { get; init; } = "balanced";
    public double? ScaleFactor { get; init; }
    public int? Fps { get; init; }
    public bool NoUpscale { get; init; }
    public bool NoInterpolate { get; init; }
    public string VideoCodec { get; init; } = "libx264";
    public string? EncoderPreset { get; init; }
    public int? Quality { get; init; }
    public string FilterBackend { get; init; } = "cpu";
    public string? FilterDevice { get; init; }
    public bool Overwrite { get; init; }
    public string FfmpegPath { get; init; } = "ffmpeg";
}
