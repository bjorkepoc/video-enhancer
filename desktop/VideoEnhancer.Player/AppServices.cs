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

    public static JsonFileStore<ExportHistoryState> ExportHistoryStore { get; } =
        new(Path.Combine(Paths.RootDirectory, "exports.json"));

    public static FfmpegJobRunner JobRunner { get; } = new();

    public static FfprobeMetadataService Metadata { get; } = new();

    public static ThumbnailService Thumbnails { get; } = new();

    public static ObservableCollection<ExportHistoryItem> ExportHistory { get; } = new();

    public static string? PendingVideoPath { get; private set; }

    public static void QueueVideoForPlayer(string path)
    {
        PendingVideoPath = path;
    }

    public static string? ConsumePendingVideoForPlayer()
    {
        string? path = PendingVideoPath;
        PendingVideoPath = null;
        return path;
    }

    public static async Task LoadExportHistoryAsync()
    {
        var state = await ExportHistoryStore.LoadAsync();
        ExportHistory.Clear();
        foreach (var item in state.Items.OrderByDescending(item => item.CreatedAt))
        {
            ExportHistory.Add(item);
        }
    }

    public static async Task SaveExportHistoryAsync()
    {
        await ExportHistoryStore.SaveAsync(new ExportHistoryState
        {
            Items = ExportHistory.ToArray(),
        });
    }

    public static async Task AddExportHistoryAsync(ExportHistoryItem item)
    {
        ExportHistory.Insert(0, item);
        await SaveExportHistoryAsync();
    }
}
