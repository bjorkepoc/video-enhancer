using VideoEnhancer.Core;
using Microsoft.UI.Xaml.Media.Imaging;

namespace VideoEnhancer_Player;

internal sealed record LibraryVideoItem(string Title, string Path, string Subtitle, string? ThumbnailPath)
{
    public BitmapImage? ThumbnailSource => ThumbnailPath is null ? null : new BitmapImage(new Uri(ThumbnailPath));
}

internal sealed record ExportHistoryState
{
    public IReadOnlyList<ExportHistoryItem> Items { get; init; } = [];
}

internal sealed record ExportHistoryItem(
    string Name,
    string Source,
    string Output,
    string Status,
    DateTimeOffset CreatedAt);
