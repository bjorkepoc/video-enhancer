using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using VideoEnhancer_Player.Pages;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace VideoEnhancer_Player;

public sealed partial class MainWindow : Window
{
    public event EventHandler<bool>? FullScreenChanged;

    public MainWindow()
    {
        InitializeComponent();

        Title = "Video Enhancer Player";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        AppWindow.SetIcon("Assets/AppIcon.ico");
        AppServices.MainWindow = this;
        NavFrame.CacheSize = 4;
        NavFrame.Navigate(typeof(PlayerPage));
    }

    public void NavigateToPlayer()
    {
        if (NavView.MenuItems
            .OfType<NavigationViewItem>()
            .FirstOrDefault(item => string.Equals(item.Tag?.ToString(), "player", StringComparison.OrdinalIgnoreCase)) is { } playerItem)
        {
            NavView.SelectedItem = playerItem;
        }

        NavFrame.Navigate(typeof(PlayerPage));
    }

    public bool IsFullScreen => AppWindow.Presenter.Kind == AppWindowPresenterKind.FullScreen;

    public bool ToggleFullScreen()
    {
        if (IsFullScreen)
        {
            ExitFullScreen();
        }
        else
        {
            EnterFullScreen();
        }

        return IsFullScreen;
    }

    public void ExitFullScreen()
    {
        if (!IsFullScreen)
        {
            return;
        }

        AppWindow.SetPresenter(AppWindowPresenterKind.Default);
        FullScreenChanged?.Invoke(this, false);
    }

    private void EnterFullScreen()
    {
        if (IsFullScreen)
        {
            return;
        }

        AppWindow.SetPresenter(AppWindowPresenterKind.FullScreen);
        FullScreenChanged?.Invoke(this, true);
    }

    private void TitleBar_PaneToggleRequested(TitleBar sender, object args)
    {
        NavView.IsPaneOpen = !NavView.IsPaneOpen;
    }

    private void TitleBar_BackRequested(TitleBar sender, object args)
    {
        NavFrame.GoBack();
    }

    private void ToggleFullScreenAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        ToggleFullScreen();
        args.Handled = true;
    }

    private void ExitFullScreenAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        if (IsFullScreen)
        {
            ExitFullScreen();
            args.Handled = true;
        }
    }

    private void NavView_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            NavFrame.Navigate(typeof(SettingsPage));
        }
        else if (args.SelectedItem is NavigationViewItem item)
        {
            switch (item.Tag)
            {
                case "player":
                    NavFrame.Navigate(typeof(PlayerPage));
                    break;
                case "library":
                    NavFrame.Navigate(typeof(LibraryPage));
                    break;
                case "exports":
                    NavFrame.Navigate(typeof(ExportsPage));
                    break;
                default:
                    throw new InvalidOperationException($"Unknown navigation item tag: {item.Tag}");
            }
        }
    }
}
