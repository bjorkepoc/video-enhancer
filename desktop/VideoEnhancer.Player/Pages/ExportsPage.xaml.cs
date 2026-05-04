using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace VideoEnhancer_Player.Pages;

public sealed partial class ExportsPage : Page
{
    public ExportsPage()
    {
        InitializeComponent();
        Loaded += ExportsPage_Loaded;
    }

    private void ExportsPage_Loaded(object sender, RoutedEventArgs e)
    {
        ExportsList.ItemsSource = AppServices.ExportHistory;
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
}
