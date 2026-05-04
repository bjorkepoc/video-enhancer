using VideoEnhancer.Core;
using Microsoft.UI.Xaml.Media.Imaging;

namespace VideoEnhancer_Player;

internal sealed record LibraryVideoItem(MediaInfo Media, string Subtitle, string? ThumbnailPath)
{
    public string Title => System.IO.Path.GetFileNameWithoutExtension(Media.Path);

    public string Path => Media.Path;

    public BitmapImage? ThumbnailSource => ThumbnailPath is null ? null : new BitmapImage(new Uri(ThumbnailPath));
}

internal sealed record ExportHistoryItem(
    string Name,
    string Source,
    string Output,
    string Status,
    DateTimeOffset CreatedAt);
