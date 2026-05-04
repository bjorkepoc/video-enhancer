using System.Collections.ObjectModel;
using VideoEnhancer.Core;

namespace VideoEnhancer_Player;

internal static class AppServices
{
    static AppServices()
    {
        Paths.EnsureCreated();
    }

    public static MainWindow? MainWindow { get; set; }

    public static AppPaths Paths { get; } = new();

    public static JsonFileStore<AppSettings> SettingsStore { get; } = new(Paths.SettingsPath);

    public static JsonFileStore<MediaLibraryState> LibraryStore { get; } = new(Paths.LibraryPath);

    public static MediaLibrary Library { get; } = new(LibraryStore);

    public static FfmpegJobRunner JobRunner { get; } = new();

    public static FfprobeMetadataService Metadata { get; } = new();

    public static ThumbnailService Thumbnails { get; } = new();

    public static ObservableCollection<ExportHistoryItem> ExportHistory { get; } = new();
}
