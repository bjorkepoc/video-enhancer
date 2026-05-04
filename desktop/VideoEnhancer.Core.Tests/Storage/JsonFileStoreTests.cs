using VideoEnhancer.Core;

namespace VideoEnhancer.Core.Tests.Storage;

public sealed class JsonFileStoreTests
{
    [Fact]
    public async Task SaveAndLoadRoundTripsJson()
    {
        string path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName(), "settings.json");
        JsonFileStore<AppSettings> store = new(path);
        AppSettings settings = new()
        {
            FfmpegPath = @"C:\tools\ffmpeg.exe",
            FfprobePath = @"C:\tools\ffprobe.exe",
            DefaultPreset = "quality",
            RecentInputs = ["a.mp4", "b.mp4"],
        };

        await store.SaveAsync(settings);
        AppSettings loaded = await store.LoadAsync();

        Assert.Equal(settings.FfmpegPath, loaded.FfmpegPath);
        Assert.Equal(settings.FfprobePath, loaded.FfprobePath);
        Assert.Equal(settings.DefaultPreset, loaded.DefaultPreset);
        Assert.Equal(settings.RecentInputs, loaded.RecentInputs);
    }
}
