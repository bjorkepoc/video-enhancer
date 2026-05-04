namespace VideoEnhancer.Core;

public sealed record AppPaths
{
    public string RootDirectory { get; init; }
    public string SettingsPath { get; init; }
    public string LibraryPath { get; init; }
    public string ThumbnailDirectory { get; init; }

    public AppPaths(string? rootDirectory = null)
    {
        RootDirectory = rootDirectory ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "VideoEnhancerPlayer");
        SettingsPath = Path.Combine(RootDirectory, "settings.json");
        LibraryPath = Path.Combine(RootDirectory, "library.json");
        ThumbnailDirectory = Path.Combine(RootDirectory, "thumbnails");
    }

    public void EnsureCreated()
    {
        Directory.CreateDirectory(RootDirectory);
        Directory.CreateDirectory(ThumbnailDirectory);
    }
}
