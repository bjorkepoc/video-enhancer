// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.

using Microsoft.UI.Xaml.Controls;
using VideoEnhancer.Core;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace VideoEnhancer_Player.Pages;

public sealed partial class SettingsPage : Page
{
    public SettingsPage()
    {
        InitializeComponent();
        Loaded += SettingsPage_Loaded;
    }

    private async void SettingsPage_Loaded(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        var settings = await AppServices.SettingsStore.LoadAsync();
        FfmpegPathBox.Text = settings.FfmpegPath;
        FfprobePathBox.Text = settings.FfprobePath;
        ScaleBox.Value = settings.DefaultScaleFactor;
        FpsBox.Value = settings.DefaultFps;
        QualityBox.Value = settings.DefaultQuality;
        SelectCombo(PresetBox, settings.DefaultPreset);
        SelectCombo(FilterBackendBox, settings.DefaultFilterBackend);
        SelectCombo(CodecBox, settings.DefaultVideoCodec);
    }

    private async void Save_Click(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        await AppServices.SettingsStore.SaveAsync(new AppSettings
        {
            FfmpegPath = string.IsNullOrWhiteSpace(FfmpegPathBox.Text) ? "ffmpeg" : FfmpegPathBox.Text,
            FfprobePath = string.IsNullOrWhiteSpace(FfprobePathBox.Text) ? "ffprobe" : FfprobePathBox.Text,
            DefaultPreset = ComboText(PresetBox),
            DefaultScaleFactor = NumberOrDefault(ScaleBox, 2.0),
            DefaultFps = Convert.ToInt32(NumberOrDefault(FpsBox, 60)),
            DefaultFilterBackend = ComboText(FilterBackendBox),
            DefaultVideoCodec = ComboText(CodecBox),
            DefaultQuality = Convert.ToInt32(NumberOrDefault(QualityBox, 16)),
        });

        SettingsInfo.Severity = InfoBarSeverity.Success;
        SettingsInfo.Title = "Saved";
        SettingsInfo.Message = "Local settings were written to AppData.";
        SettingsInfo.IsOpen = true;
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

    private static double NumberOrDefault(NumberBox numberBox, double fallback)
    {
        return double.IsFinite(numberBox.Value) && numberBox.Value > 0 ? numberBox.Value : fallback;
    }
}
