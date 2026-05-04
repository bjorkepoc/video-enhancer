using VideoEnhancer.Core;

namespace VideoEnhancer.Core.Tests.Enhancement;

public sealed class FfmpegProgressParserTests
{
    [Fact]
    public void ProgressParserCalculatesPercentFromOutTime()
    {
        FfmpegProgressParser parser = new(TimeSpan.FromSeconds(10));

        FfmpegProgress? progress = parser.ParseLine("out_time_ms=5000000");

        Assert.NotNull(progress);
        Assert.Equal(50, progress.Percent.GetValueOrDefault(), precision: 3);
        Assert.Equal(TimeSpan.FromSeconds(5), progress.OutTime);
    }
}
