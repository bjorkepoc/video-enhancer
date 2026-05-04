using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage.Pickers;
using VideoEnhancer.Core;
using WinRT.Interop;

namespace VideoEnhancer_Player.Pages;

public sealed partial class LibraryPage : Page
{
    private static readonly string[] VideoExtensions =
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
        ".m4v",
    };

    public LibraryPage()
    {
        InitializeComponent();
        Loaded += LibraryPage_Loaded;
    }

    private async void LibraryPage_Loaded(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
    }

    private async void AddVideo_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(AppServices.MainWindow));
        foreach (var extension in VideoExtensions)
        {
            picker.FileTypeFilter.Add(extension);
        }

        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            return;
        }

        await AddPathAsync(file.Path);
        await RefreshAsync();
    }

    private async void AddFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(AppServices.MainWindow));
        picker.FileTypeFilter.Add("*");
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
        {
            return;
        }

        var settings = await AppServices.SettingsStore.LoadAsync();
        foreach (var path in Directory.EnumerateFiles(folder.Path)
                     .Where(path => VideoExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase)))
        {
            try
            {
                await AddPathAsync(path, settings);
            }
            catch
            {
                // Keep scanning even when one file cannot be probed.
            }
        }

        await RefreshAsync();
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        await AppServices.LibraryStore.SaveAsync(new MediaLibraryState());
        await RefreshAsync();
    }

    private void Open_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string path })
        {
            AppServices.QueueVideoForPlayer(path);
            AppServices.MainWindow?.NavigateToPlayer();
        }
    }

    private void Reveal_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string path })
        {
            _ = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = "explorer.exe",
                ArgumentList = { "/select,", path },
                UseShellExecute = true,
            });
        }
    }

    private async Task RefreshAsync()
    {
        var items = await AppServices.Library.GetItemsAsync();
        VideosList.ItemsSource = items
            .Select(item => ToItem(item))
            .ToList();
    }

    private static LibraryVideoItem ToItem(MediaLibraryItem item)
    {
        var title = Path.GetFileNameWithoutExtension(item.InputPath);
        var subtitle = item.MediaInfo is { } media
            ? $"{media.Width}x{media.Height}  {media.FramesPerSecond:0.##} FPS  {FormatDuration(media.Duration ?? TimeSpan.Zero)}"
            : "Metadata unavailable";
        return new LibraryVideoItem(title, item.InputPath, subtitle, item.ThumbnailPath);
    }

    private static async Task AddPathAsync(string path, AppSettings? settings = null)
    {
        settings ??= await AppServices.SettingsStore.LoadAsync();
        var thumbnail = await CreateThumbnailAsync(path, settings);
        MediaInfo? media = null;
        try
        {
            media = await AppServices.Metadata.GetMediaInfoAsync(path, settings.FfprobePath);
        }
        catch
        {
            // Keep the file in the library even when metadata probing fails.
        }

        await AppServices.Library.AddOrUpdateAsync(new MediaLibraryItem
        {
            InputPath = path,
            OutputPath = BuildDefaultOutputPath(path),
            ThumbnailPath = thumbnail,
            MediaInfo = media,
        });
    }

    private static async Task<string?> CreateThumbnailAsync(string path, AppSettings? settings = null)
    {
        try
        {
            var thumbnailPath = Path.Combine(
                AppServices.Paths.ThumbnailDirectory,
                Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(path))) + ".jpg");
            settings ??= await AppServices.SettingsStore.LoadAsync();
            await AppServices.Thumbnails.CreateThumbnailAsync(path, thumbnailPath, ffmpegPath: settings.FfmpegPath);
            return thumbnailPath;
        }
        catch
        {
            return null;
        }
    }

    private static string FormatDuration(TimeSpan duration)
    {
        return duration.TotalHours >= 1 ? duration.ToString(@"hh\:mm\:ss") : duration.ToString(@"mm\:ss");
    }

    private static string BuildDefaultOutputPath(string inputPath)
    {
        var directory = Path.GetDirectoryName(inputPath) ?? ".";
        var name = Path.GetFileNameWithoutExtension(inputPath);
        return Path.Combine(directory, $"{name}_enhanced_gui.mp4");
    }
}
