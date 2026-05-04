namespace VideoEnhancer.Core;

public sealed record MediaInfo
{
    public string Path { get; init; } = "";
    public TimeSpan? Duration { get; init; }
    public int? Width { get; init; }
    public int? Height { get; init; }
    public double? FramesPerSecond { get; init; }
    public string? VideoCodec { get; init; }
    public string? AudioCodec { get; init; }
    public long? BitRate { get; init; }
}
