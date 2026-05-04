namespace VideoEnhancer.Core;

public sealed class MediaLibrary
{
    private readonly JsonFileStore<MediaLibraryState> _store;

    public MediaLibrary(JsonFileStore<MediaLibraryState> store)
    {
        _store = store;
    }

    public async Task<IReadOnlyList<MediaLibraryItem>> GetItemsAsync(CancellationToken cancellationToken = default)
    {
        MediaLibraryState state = await _store.LoadAsync(cancellationToken).ConfigureAwait(false);
        return state.Items;
    }

    public async Task AddOrUpdateAsync(MediaLibraryItem item, CancellationToken cancellationToken = default)
    {
        MediaLibraryState state = await _store.LoadAsync(cancellationToken).ConfigureAwait(false);
        List<MediaLibraryItem> items = state.Items
            .Where(existing => !existing.InputPath.Equals(item.InputPath, StringComparison.OrdinalIgnoreCase))
            .ToList();
        items.Insert(0, item);
        await _store.SaveAsync(new MediaLibraryState { Items = items }, cancellationToken).ConfigureAwait(false);
    }

    public async Task RemoveAsync(string inputPath, CancellationToken cancellationToken = default)
    {
        MediaLibraryState state = await _store.LoadAsync(cancellationToken).ConfigureAwait(false);
        MediaLibraryState updated = new()
        {
            Items = state.Items
                .Where(item => !item.InputPath.Equals(inputPath, StringComparison.OrdinalIgnoreCase))
                .ToArray(),
        };
        await _store.SaveAsync(updated, cancellationToken).ConfigureAwait(false);
    }
}

public sealed record MediaLibraryState
{
    public IReadOnlyList<MediaLibraryItem> Items { get; init; } = [];
}

public sealed record MediaLibraryItem
{
    public string InputPath { get; init; } = "";
    public string? OutputPath { get; init; }
    public string? ThumbnailPath { get; init; }
    public MediaInfo? MediaInfo { get; init; }
    public DateTimeOffset AddedAt { get; init; } = DateTimeOffset.UtcNow;
}
