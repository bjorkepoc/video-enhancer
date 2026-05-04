using VideoEnhancer.Core;

namespace VideoEnhancer.Core.Tests.Enhancement;

public sealed class FfmpegCommandBuilderTests
{
    [Fact]
    public void UltraCpuIncludesDenoiseInterpolateScaleAndSharpenInOrder()
    {
        EnhancementRequest request = SampleRequest with { Preset = "ultra" };

        IReadOnlyList<string> command = FfmpegCommandBuilder.BuildCommand(request, checkExecutable: false);
        string filters = ValueAfter(command, "-vf");

        Assert.True(filters.IndexOf("nlmeans=", StringComparison.Ordinal) < filters.IndexOf("minterpolate=", StringComparison.Ordinal));
        Assert.True(filters.IndexOf("minterpolate=", StringComparison.Ordinal) < filters.IndexOf("scale=", StringComparison.Ordinal));
        Assert.True(filters.IndexOf("scale=", StringComparison.Ordinal) < filters.IndexOf("unsharp=", StringComparison.Ordinal));
        Assert.Contains("nlmeans=s=1.0:p=7:r=15", filters);
        Assert.Contains("unsharp=5:5:0.65:5:5:0.0", filters);
    }

    [Fact]
    public void VulkanBackendUsesHardwareDeviceNlmeansVulkanAndLibplacebo()
    {
        EnhancementRequest request = SampleRequest with
        {
            Preset = "ultra",
            FilterBackend = "vulkan",
        };

        IReadOnlyList<string> command = FfmpegCommandBuilder.BuildCommand(request, checkExecutable: false);
        string filters = ValueAfter(command, "-vf");

        Assert.Equal("vulkan=ve:0", ValueAfter(command, "-init_hw_device"));
        Assert.Equal("ve", ValueAfter(command, "-filter_hw_device"));
        Assert.Contains("nlmeans_vulkan=s=1.0:p=7:r=15", filters);
        Assert.Contains("libplacebo=w=trunc(iw*2.0/2)*2:h=trunc(ih*2.0/2)*2", filters);
    }

    [Fact]
    public void NoInterpolateRemovesMinterpolate()
    {
        EnhancementRequest request = SampleRequest with { NoInterpolate = true };

        IReadOnlyList<string> command = FfmpegCommandBuilder.BuildCommand(request, checkExecutable: false);

        Assert.DoesNotContain("minterpolate", ValueAfter(command, "-vf"));
    }

    [Fact]
    public void H264NvencUsesVariableBitrateConstantQualityArgs()
    {
        EnhancementRequest request = SampleRequest with
        {
            VideoCodec = "h264_nvenc",
            EncoderPreset = "p7",
            Quality = 16,
        };

        IReadOnlyList<string> command = FfmpegCommandBuilder.BuildCommand(request, checkExecutable: false);

        Assert.Equal("h264_nvenc", ValueAfter(command, "-c:v"));
        Assert.Equal("p7", ValueAfter(command, "-preset"));
        Assert.Equal("vbr", ValueAfter(command, "-rc"));
        Assert.Equal("16", ValueAfter(command, "-cq:v"));
        Assert.Equal("0", ValueAfter(command, "-b:v"));
    }

    private static EnhancementRequest SampleRequest => new()
    {
        InputPath = @"C:\media\input.mp4",
        OutputPath = @"C:\media\output.mp4",
        FfmpegPath = "ffmpeg",
    };

    private static string ValueAfter(IReadOnlyList<string> command, string option)
    {
        int index = command.ToList().IndexOf(option);
        Assert.True(index >= 0, $"Missing {option} in {FfmpegCommandBuilder.FormatCommand(command)}");
        Assert.True(index + 1 < command.Count, $"Missing value for {option}");
        return command[index + 1];
    }
}
