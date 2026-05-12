namespace VideoEnhancer.Core.Tests.Desktop;

public sealed class PlayerUiContractTests
{
    [Fact]
    public void VideoFullScreenDoesNotPromoteTheAppWindow()
    {
        string mainWindowCode = File.ReadAllText(ProjectFile("desktop", "VideoEnhancer.Player", "MainWindow.xaml.cs"));

        Assert.DoesNotContain("AppWindowPresenterKind.FullScreen", mainWindowCode);
        Assert.DoesNotContain("SetPresenter(AppWindowPresenterKind.FullScreen)", mainWindowCode);
    }

    [Fact]
    public void PlayerExposesVideoOnlyFullScreenAndZoomControls()
    {
        string playerXaml = File.ReadAllText(ProjectFile("desktop", "VideoEnhancer.Player", "Pages", "PlayerPage.xaml"));

        Assert.Contains("x:Name=\"PlayerLayout\"", playerXaml);
        Assert.Contains("x:Name=\"EnhancerPanel\"", playerXaml);
        Assert.Contains("x:Name=\"VideoShell\"", playerXaml);
        Assert.Contains("x:Name=\"ZoomInButton\"", playerXaml);
        Assert.Contains("x:Name=\"ZoomOutButton\"", playerXaml);
        Assert.Contains("x:Name=\"ResetZoomButton\"", playerXaml);
        Assert.Contains("AutomationProperties.Name=\"Zoom in\"", playerXaml);
        Assert.Contains("AutomationProperties.Name=\"Zoom out\"", playerXaml);
        Assert.Contains("AutomationProperties.Name=\"Reset zoom\"", playerXaml);
    }

    private static string ProjectFile(params string[] parts)
    {
        DirectoryInfo? directory = new(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml")))
        {
            directory = directory.Parent;
        }

        Assert.NotNull(directory);
        return Path.Combine([directory!.FullName, .. parts]);
    }
}
