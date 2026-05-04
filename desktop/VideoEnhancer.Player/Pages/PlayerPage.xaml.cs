using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage.Pickers;
using VideoEnhancer.Core;
using WinRT.Interop;

namespace VideoEnhancer_Player.Pages;

public sealed partial class PlayerPage : Page
{
    private readonly MediaPlayer _mediaPlayer = new();
    private readonly DispatcherTimer _timelineTimer = new();
    private readonly DispatcherTimer _stepTimer = new();
    private CancellationTokenSource? _enhanceCancellation;
    private MediaInfo? _currentMedia;
    private bool _isTimelineDragging;

    public PlayerPage()
    {
        InitializeComponent();
        PlayerElement.SetMediaPlayer(_mediaPlayer);
        _mediaPlayer.PlaybackSession.PlaybackStateChanged += PlaybackSession_PlaybackStateChanged;

        _timelineTimer.Interval = TimeSpan.FromMilliseconds(250);
        _timelineTimer.Tick += TimelineTimer_Tick;
        _timelineTimer.Start();

        _stepTimer.Tick += StepTimer_Tick;
        Loaded += PlayerPage_Loaded;
        Unloaded += PlayerPage_Unloaded;
    }

    private async void PlayerPage_Loaded(object sender, RoutedEventArgs e)
    {
        var settings = await AppServices.SettingsStore.LoadAsync();
        ApplySettings(settings);
    }

    private void PlayerPage_Unloaded(object sender, RoutedEventArgs e)
    {
        _stepTimer.Stop();
        _timelineTimer.Stop();
    }

    private async void OpenVideo_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        var hwnd = WindowNative.GetWindowHandle(AppServices.MainWindow);
        InitializeWithWindow.Initialize(picker, hwnd);
        picker.FileTypeFilter.Add(".mp4");
        picker.FileTypeFilter.Add(".mov");
        picker.FileTypeFilter.Add(".mkv");
        picker.FileTypeFilter.Add(".avi");
        picker.FileTypeFilter.Add(".webm");
        picker.FileTypeFilter.Add(".m4v");

        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            return;
        }

        await LoadVideoAsync(file.Path);
    }

    private async Task LoadVideoAsync(string path)
    {
        var settings = await AppServices.SettingsStore.LoadAsync();
        _currentMedia = await AppServices.Metadata.GetMediaInfoAsync(path, settings.FfprobePath);
        var thumbnail = await CreateThumbnailAsync(path, settings.FfmpegPath);
        await AppServices.Library.AddOrUpdateAsync(new MediaLibraryItem
        {
            InputPath = path,
            OutputPath = BuildDefaultOutputPath(path),
            ThumbnailPath = thumbnail,
            MediaInfo = _currentMedia,
        });

        _mediaPlayer.Source = MediaSource.CreateFromUri(new Uri(path));
        InputPathBox.Text = path;
        OutputPathBox.Text = BuildDefaultOutputPath(path);
        TimelineSlider.Maximum = Math.Max(1, (_currentMedia.Duration ?? TimeSpan.Zero).TotalSeconds);
        ShowInfo("Video loaded", $"{_currentMedia.Width}x{_currentMedia.Height}, {_currentMedia.FramesPerSecond:0.##} FPS");
    }

    private void PlayPause_Click(object sender, RoutedEventArgs e)
    {
        if (_mediaPlayer.PlaybackSession.PlaybackState == MediaPlaybackState.Playing)
        {
            _mediaPlayer.Pause();
        }
        else
        {
            _mediaPlayer.Play();
        }
    }

    private void FrameForward_Click(object sender, RoutedEventArgs e)
    {
        _mediaPlayer.Pause();
        _mediaPlayer.StepForwardOneFrame();
    }

    private void FrameBack_Click(object sender, RoutedEventArgs e)
    {
        _mediaPlayer.Pause();
        var fps = _currentMedia?.FramesPerSecond > 0 ? _currentMedia.FramesPerSecond.Value : 30;
        var back = TimeSpan.FromSeconds(1.0 / fps);
        var current = _mediaPlayer.PlaybackSession.Position;
        _mediaPlayer.PlaybackSession.Position = current > back ? current - back : TimeSpan.Zero;
    }

    private void SlowMode_Click(object sender, RoutedEventArgs e)
    {
        if (SlowModeButton.IsChecked == true)
        {
            _mediaPlayer.Pause();
            var fps = SelectedStepFps();
            _stepTimer.Interval = TimeSpan.FromSeconds(1.0 / fps);
            _stepTimer.Start();
        }
        else
        {
            _stepTimer.Stop();
        }
    }

    private void StepTimer_Tick(object? sender, object e)
    {
        _mediaPlayer.StepForwardOneFrame();
    }

    private void TimelineTimer_Tick(object? sender, object e)
    {
        if (_currentMedia is null || _isTimelineDragging)
        {
            return;
        }

        var position = _mediaPlayer.PlaybackSession.Position;
        TimelineSlider.Value = Math.Clamp(position.TotalSeconds, 0, TimelineSlider.Maximum);
        TimeText.Text = $"{FormatTime(position)} / {FormatTime(_currentMedia.Duration ?? TimeSpan.Zero)}";
    }

    private void TimelineSlider_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (_currentMedia is null || Math.Abs(_mediaPlayer.PlaybackSession.Position.TotalSeconds - e.NewValue) < 1)
        {
            return;
        }

        _isTimelineDragging = true;
        _mediaPlayer.PlaybackSession.Position = TimeSpan.FromSeconds(e.NewValue);
        _isTimelineDragging = false;
    }

    private async void DryRun_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var request = BuildRequest();
            var command = FfmpegCommandBuilder.FormatCommand(FfmpegCommandBuilder.BuildCommand(request, checkExecutable: false));
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = "FFmpeg dry run",
                Content = new TextBox
                {
                    Text = command,
                    IsReadOnly = true,
                    TextWrapping = TextWrapping.Wrap,
                    AcceptsReturn = true,
                    MinHeight = 260,
                },
                CloseButtonText = "Close",
            };
            await dialog.ShowAsync();
        }
        catch (Exception ex)
        {
            ShowError("Dry run failed", ex.Message);
        }
    }

    private async void Enhance_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var request = BuildRequest();
            await SaveCurrentSettingsAsync(request);
            _enhanceCancellation = new CancellationTokenSource();
            EnhanceProgress.Value = 0;
            EnhanceProgress.IsIndeterminate = false;
            ProgressText.Text = "Starting FFmpeg...";
            ShowInfo("Enhancing", "FFmpeg job is running locally.");

            var progress = new Progress<FfmpegProgress>(item =>
            {
                if (item.Percent is not null)
                {
                    EnhanceProgress.Value = item.Percent.Value;
                }

                ProgressText.Text = $"{item.Percent:0.0}%  {FormatTime(item.OutTime)}  {item.Speed:0.##}x";
            });

            await AppServices.JobRunner.RunAsync(
                request,
                _currentMedia?.Duration,
                progress,
                _enhanceCancellation.Token);

            EnhanceProgress.Value = 100;
            ProgressText.Text = request.OutputPath;
            ShowInfo("Export finished", request.OutputPath);
            AppServices.ExportHistory.Insert(0, new ExportHistoryItem(
                Path.GetFileName(request.OutputPath),
                request.InputPath,
                request.OutputPath,
                "Finished",
                DateTimeOffset.Now));
        }
        catch (OperationCanceledException)
        {
            ShowInfo("Cancelled", "The FFmpeg job was stopped.");
        }
        catch (Exception ex)
        {
            ShowError("Enhance failed", ex.Message);
        }
        finally
        {
            _enhanceCancellation?.Dispose();
            _enhanceCancellation = null;
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _enhanceCancellation?.Cancel();
    }

    private EnhancementRequest BuildRequest()
    {
        if (string.IsNullOrWhiteSpace(InputPathBox.Text))
        {
            throw new InvalidOperationException("Open a video before enhancing.");
        }

        if (string.IsNullOrWhiteSpace(OutputPathBox.Text))
        {
            throw new InvalidOperationException("Choose an output path.");
        }

        return new EnhancementRequest
        {
            InputPath = InputPathBox.Text,
            OutputPath = OutputPathBox.Text,
            Preset = ComboText(PresetBox),
            ScaleFactor = NumberOrDefault(ScaleBox, 2.0),
            Fps = Convert.ToInt32(NumberOrDefault(FpsBox, 60)),
            NoUpscale = NoUpscaleBox.IsChecked == true,
            NoInterpolate = NoInterpolateBox.IsChecked == true,
            VideoCodec = ComboText(CodecBox),
            EncoderPreset = string.IsNullOrWhiteSpace(EncoderPresetBox.Text) ? null : EncoderPresetBox.Text,
            Quality = Convert.ToInt32(NumberOrDefault(QualityBox, 16)),
            FilterBackend = ComboText(FilterBackendBox),
            Overwrite = OverwriteBox.IsChecked == true,
            FfmpegPath = ResolveConfiguredFfmpeg(),
        };
    }

    private async Task SaveCurrentSettingsAsync(EnhancementRequest request)
    {
        await AppServices.SettingsStore.SaveAsync(new AppSettings
        {
            FfmpegPath = request.FfmpegPath,
            DefaultPreset = request.Preset,
            DefaultScaleFactor = request.ScaleFactor ?? 2,
            DefaultFps = request.Fps ?? 60,
            DefaultFilterBackend = request.FilterBackend,
            DefaultVideoCodec = request.VideoCodec,
            DefaultQuality = request.Quality ?? 16,
            ExportDirectory = Path.GetDirectoryName(request.OutputPath) ?? string.Empty,
        });
    }

    private void ApplySettings(AppSettings settings)
    {
        SelectCombo(PresetBox, settings.DefaultPreset);
        SelectCombo(FilterBackendBox, settings.DefaultFilterBackend);
        SelectCombo(CodecBox, settings.DefaultVideoCodec);
        ScaleBox.Value = settings.DefaultScaleFactor;
        FpsBox.Value = settings.DefaultFps;
        QualityBox.Value = settings.DefaultQuality;
    }

    private static string ComboText(ComboBox comboBox)
    {
        return ((ComboBoxItem)comboBox.SelectedItem).Content?.ToString() ?? string.Empty;
    }

    private static void SelectCombo(ComboBox comboBox, string value)
    {
        foreach (var item in comboBox.Items.OfType<ComboBoxItem>())
        {
            if (string.Equals(item.Content?.ToString(), value, StringComparison.OrdinalIgnoreCase))
            {
                comboBox.SelectedItem = item;
                return;
            }
        }
    }

    private int SelectedStepFps()
    {
        return int.TryParse(((ComboBoxItem)StepFpsBox.SelectedItem).Tag?.ToString(), out var fps)
            ? fps
            : 1;
    }

    private static double NumberOrDefault(NumberBox numberBox, double fallback)
    {
        return double.IsFinite(numberBox.Value) && numberBox.Value > 0 ? numberBox.Value : fallback;
    }

    private static string ResolveConfiguredFfmpeg()
    {
        var settings = AppServices.SettingsStore.LoadAsync().GetAwaiter().GetResult();
        var preferred = string.IsNullOrWhiteSpace(settings.FfmpegPath) ? "ffmpeg" : settings.FfmpegPath;
        return FfmpegLocator.FindFfmpeg(preferred) ?? preferred ?? "ffmpeg";
    }

    private static async Task<string?> CreateThumbnailAsync(string path, string? ffmpegPath)
    {
        try
        {
            var thumbnailPath = Path.Combine(
                AppServices.Paths.ThumbnailDirectory,
                Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(path))) + ".jpg");
            await AppServices.Thumbnails.CreateThumbnailAsync(path, thumbnailPath, ffmpegPath: ffmpegPath);
            return thumbnailPath;
        }
        catch
        {
            return null;
        }
    }

    private static string BuildDefaultOutputPath(string inputPath)
    {
        var directory = Path.GetDirectoryName(inputPath) ?? ".";
        var name = Path.GetFileNameWithoutExtension(inputPath);
        return Path.Combine(directory, $"{name}_enhanced_gui.mp4");
    }

    private static string FormatTime(TimeSpan value)
    {
        return value.TotalHours >= 1 ? value.ToString(@"hh\:mm\:ss") : value.ToString(@"mm\:ss");
    }

    private void PlaybackSession_PlaybackStateChanged(MediaPlaybackSession sender, object args)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            PlayPauseButton.Label = sender.PlaybackState == MediaPlaybackState.Playing ? "Pause" : "Play";
            PlayPauseButton.Icon = new SymbolIcon(sender.PlaybackState == MediaPlaybackState.Playing ? Symbol.Pause : Symbol.Play);
        });
    }

    private void ShowInfo(string title, string message)
    {
        StatusInfo.Severity = InfoBarSeverity.Informational;
        StatusInfo.Title = title;
        StatusInfo.Message = message;
        StatusInfo.IsOpen = true;
    }

    private void ShowError(string title, string message)
    {
        StatusInfo.Severity = InfoBarSeverity.Error;
        StatusInfo.Title = title;
        StatusInfo.Message = message.Length > 600 ? message[..600] : message;
        StatusInfo.IsOpen = true;
    }
}
