using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace VideoEnhancer.Core;

public static class FfmpegCommandBuilder
{
    private const string FilterDeviceName = "ve";

    private static readonly IReadOnlyDictionary<string, PresetProfile> Presets = new Dictionary<string, PresetProfile>(StringComparer.OrdinalIgnoreCase)
    {
        ["fast"] = new(
            "fast",
            2.0,
            48,
            "bicubic",
            new Dictionary<string, string> { ["mi_mode"] = "blend" },
            "veryfast",
            23),
        ["balanced"] = new(
            "balanced",
            2.0,
            60,
            "lanczos",
            new Dictionary<string, string>
            {
                ["mi_mode"] = "mci",
                ["mc_mode"] = "obmc",
                ["me_mode"] = "bidir",
            },
            "medium",
            20),
        ["quality"] = new(
            "quality",
            2.0,
            60,
            "lanczos",
            new Dictionary<string, string>
            {
                ["mi_mode"] = "mci",
                ["mc_mode"] = "aobmc",
                ["me_mode"] = "bidir",
                ["vsbmc"] = "1",
            },
            "slow",
            18),
        ["ultra"] = new(
            "ultra",
            2.0,
            90,
            "lanczos",
            new Dictionary<string, string>
            {
                ["mi_mode"] = "mci",
                ["mc_mode"] = "aobmc",
                ["me_mode"] = "bidir",
                ["me"] = "umh",
                ["mb_size"] = "8",
                ["search_param"] = "48",
                ["vsbmc"] = "1",
                ["scd"] = "fdiff",
                ["scd_threshold"] = "10",
            },
            "slow",
            16,
            ["nlmeans=s=1.0:p=7:r=15"],
            ["unsharp=5:5:0.65:5:5:0.0"],
            InterpolateBeforeScale: true),
    };

    private static readonly IReadOnlyDictionary<string, EncoderProfile> Encoders = new Dictionary<string, EncoderProfile>(StringComparer.OrdinalIgnoreCase)
    {
        ["libx264"] = new("libx264", "software", "medium"),
        ["libx265"] = new("libx265", "software", "medium"),
        ["h264_nvenc"] = new("h264_nvenc", "nvenc", "p6"),
        ["hevc_nvenc"] = new("hevc_nvenc", "nvenc", "p6"),
        ["av1_nvenc"] = new("av1_nvenc", "nvenc", "p6"),
        ["h264_amf"] = new("h264_amf", "amf", "quality"),
        ["hevc_amf"] = new("hevc_amf", "amf", "quality"),
        ["av1_amf"] = new("av1_amf", "amf", "quality"),
        ["h264_qsv"] = new("h264_qsv", "qsv", "slow"),
        ["hevc_qsv"] = new("hevc_qsv", "qsv", "slow"),
        ["av1_qsv"] = new("av1_qsv", "qsv", "slow"),
    };

    private static readonly IReadOnlyDictionary<string, string?> FilterBackends = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
    {
        ["cpu"] = null,
        ["auto"] = null,
        ["cuda"] = "0",
        ["opencl"] = "0.0",
        ["vulkan"] = "0",
    };

    public static IReadOnlyList<string> BuildCommand(EnhancementRequest request, bool checkExecutable = true)
    {
        ArgumentNullException.ThrowIfNull(request);
        ValidateRequest(request);

        if (checkExecutable)
        {
            ValidatePaths(request);
        }

        PresetProfile preset = GetPreset(request.Preset);
        string ffmpeg = checkExecutable
            ? FfmpegLocator.FindFfmpeg(request.FfmpegPath) ?? throw new FileNotFoundException("FFmpeg was not found.", request.FfmpegPath)
            : request.FfmpegPath;
        string filterBackend = checkExecutable
            ? ResolveFilterBackend(ffmpeg, request)
            : ResolveFilterBackend(request.FilterBackend, request.VideoCodec);

        List<string> command =
        [
            ffmpeg,
            "-hide_banner",
            request.Overwrite ? "-y" : "-n",
        ];
        command.AddRange(BuildFilterDeviceArgs(filterBackend, request.FilterDevice));
        command.AddRange(
        [
            "-i",
            request.InputPath,
            "-vf",
            BuildVideoFilterChain(preset, request, filterBackend),
        ]);
        command.AddRange(BuildVideoEncoderArgs(preset, request));
        command.AddRange(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            request.OutputPath,
        ]);

        return command;
    }

    public static IReadOnlyList<string> BuildArguments(EnhancementRequest request, bool checkExecutable = true)
    {
        return BuildCommand(request, checkExecutable).Skip(1).ToArray();
    }

    public static string FormatCommand(IEnumerable<string> command)
    {
        ArgumentNullException.ThrowIfNull(command);
        return string.Join(" ", command.Select(QuoteArgument));
    }

    public static IReadOnlyList<string> AvailablePresets => Presets.Keys.ToArray();

    public static IReadOnlyList<string> SupportedVideoCodecs => Encoders.Keys.ToArray();

    public static IReadOnlyList<string> SupportedFilterBackends => FilterBackends.Keys.ToArray();

    internal static string BuildVideoFilterChain(PresetProfile preset, EnhancementRequest request, string filterBackend)
    {
        double scaleFactor = request.ScaleFactor ?? preset.ScaleFactor;
        int fps = request.Fps ?? preset.TargetFps;
        (string widthExpr, string heightExpr) = EffectiveDimensions(scaleFactor, request.NoUpscale);
        List<string> filters = [];

        filters.AddRange(GpuPreScaleFilters(filterBackend, preset));

        string? interpolation = request.NoInterpolate ? null : InterpolationFilter(preset, fps);
        if (interpolation is not null && preset.InterpolateBeforeScale)
        {
            filters.Add(interpolation);
        }

        filters.AddRange(ScaleFilters(filterBackend, widthExpr, heightExpr, preset.ScaleFlags));
        filters.AddRange(PostScaleFilters(filterBackend, preset));

        if (interpolation is not null && !preset.InterpolateBeforeScale)
        {
            filters.Add(interpolation);
        }

        return string.Join(",", filters);
    }

    private static void ValidateRequest(EnhancementRequest request)
    {
        _ = GetPreset(request.Preset);
        _ = GetEncoder(request.VideoCodec);
        if (!FilterBackends.ContainsKey(request.FilterBackend))
        {
            throw new ArgumentException($"Unknown filter backend '{request.FilterBackend}'.", nameof(request));
        }

        if (request.ScaleFactor is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(request.ScaleFactor), "ScaleFactor must be greater than 0.");
        }

        if (request.Fps is <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(request.Fps), "Fps must be greater than 0.");
        }

        if (request.Quality is < 0 or > 51)
        {
            throw new ArgumentOutOfRangeException(nameof(request.Quality), "Quality must be between 0 and 51.");
        }
    }

    private static void ValidatePaths(EnhancementRequest request)
    {
        if (!File.Exists(request.InputPath))
        {
            throw new FileNotFoundException("Input video does not exist.", request.InputPath);
        }

        string? outputDirectory = Path.GetDirectoryName(Path.GetFullPath(request.OutputPath));
        if (!string.IsNullOrWhiteSpace(outputDirectory) && !Directory.Exists(outputDirectory))
        {
            throw new DirectoryNotFoundException($"Output directory does not exist: {outputDirectory}");
        }

        if (Directory.Exists(request.OutputPath))
        {
            throw new IOException($"Output path is a directory: {request.OutputPath}");
        }

        if (File.Exists(request.OutputPath) && !request.Overwrite)
        {
            throw new IOException($"Output file already exists: {request.OutputPath}");
        }

        if (Path.GetFullPath(request.InputPath).Equals(Path.GetFullPath(request.OutputPath), StringComparison.OrdinalIgnoreCase))
        {
            throw new IOException("Input and output must be different files.");
        }
    }

    private static PresetProfile GetPreset(string name)
    {
        if (Presets.TryGetValue(name, out PresetProfile? preset))
        {
            return preset;
        }

        throw new ArgumentException($"Unknown preset '{name}'.", nameof(name));
    }

    private static EncoderProfile GetEncoder(string codec)
    {
        if (Encoders.TryGetValue(codec, out EncoderProfile? encoder))
        {
            return encoder;
        }

        throw new ArgumentException($"Unknown video codec '{codec}'.", nameof(codec));
    }

    private static string ResolveFilterBackend(string requestedBackend, string videoCodec)
    {
        if (!requestedBackend.Equals("auto", StringComparison.OrdinalIgnoreCase))
        {
            return requestedBackend.ToLowerInvariant();
        }

        return GetEncoder(videoCodec).Family.Equals("nvenc", StringComparison.OrdinalIgnoreCase)
            ? "cuda"
            : "vulkan";
    }

    private static string ResolveFilterBackend(string ffmpegPath, EnhancementRequest request)
    {
        string requestedBackend = request.FilterBackend;
        PresetProfile preset = GetPreset(request.Preset);
        HashSet<string> filters = AvailableFilterNames(ffmpegPath);

        if (requestedBackend.Equals("auto", StringComparison.OrdinalIgnoreCase))
        {
            foreach (string candidate in PreferredBackends(request.VideoCodec))
            {
                if (RequiredFilters(candidate, preset).All(filters.Contains) && ProbeFilterBackend(ffmpegPath, candidate, request.FilterDevice))
                {
                    return candidate;
                }
            }

            return "cpu";
        }

        string resolved = requestedBackend.ToLowerInvariant();
        if (resolved == "cpu")
        {
            return resolved;
        }

        string[] missing = RequiredFilters(resolved, preset)
            .Where(filter => !filters.Contains(filter))
            .ToArray();
        if (missing.Length > 0)
        {
            throw new InvalidOperationException($"Filter backend '{resolved}' requires missing FFmpeg filters: {string.Join(", ", missing)}.");
        }

        if (!ProbeFilterBackend(ffmpegPath, resolved, request.FilterDevice))
        {
            throw new InvalidOperationException($"Filter backend '{resolved}' is present but failed a runtime probe.");
        }

        return resolved;
    }

    private static IEnumerable<string> PreferredBackends(string videoCodec)
    {
        return GetEncoder(videoCodec).Family.Equals("nvenc", StringComparison.OrdinalIgnoreCase)
            ? ["cuda", "vulkan", "opencl"]
            : ["vulkan", "opencl", "cuda"];
    }

    private static string[] RequiredFilters(string filterBackend, PresetProfile preset)
    {
        List<string> required = [];
        switch (filterBackend)
        {
            case "cuda":
                required.AddRange(["hwupload_cuda", "scale_cuda"]);
                if (preset.PreScaleFilters.Count > 0)
                {
                    required.Add("bilateral_cuda");
                }

                break;
            case "opencl":
                required.Add("hwupload");
                if (preset.PreScaleFilters.Count > 0)
                {
                    required.Add("nlmeans_opencl");
                }

                if (preset.PostScaleFilters.Count > 0)
                {
                    required.Add("unsharp_opencl");
                }

                break;
            case "vulkan":
                required.AddRange(["hwupload", "libplacebo"]);
                if (preset.PreScaleFilters.Count > 0)
                {
                    required.Add("nlmeans_vulkan");
                }

                break;
        }

        return required.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static HashSet<string> AvailableFilterNames(string ffmpegPath)
    {
        ProcessStartInfo startInfo = new()
        {
            FileName = ffmpegPath,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        startInfo.ArgumentList.Add("-hide_banner");
        startInfo.ArgumentList.Add("-filters");

        using Process process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start FFmpeg filter probe.");
        string output = process.StandardOutput.ReadToEnd() + Environment.NewLine + process.StandardError.ReadToEnd();
        process.WaitForExit();

        Regex filterLine = new(@"^\s*[TSC. ]{3}\s+([A-Za-z0-9_]+)\s+", RegexOptions.Compiled);
        return output
            .Split(Environment.NewLine)
            .Select(line => filterLine.Match(line))
            .Where(match => match.Success)
            .Select(match => match.Groups[1].Value)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static bool ProbeFilterBackend(string ffmpegPath, string filterBackend, string? filterDevice)
    {
        ProcessStartInfo startInfo = new()
        {
            FileName = ffmpegPath,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        foreach (string argument in BuildFilterDeviceArgs(filterBackend, filterDevice))
        {
            startInfo.ArgumentList.Add(argument);
        }

        foreach (string argument in new[]
        {
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=128x128:r=1:d=1",
            "-vf",
            ProbeFilterChain(filterBackend),
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        })
        {
            startInfo.ArgumentList.Add(argument);
        }

        using Process process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start FFmpeg backend probe.");
        if (!process.WaitForExit(20_000))
        {
            process.Kill(entireProcessTree: true);
            return false;
        }

        return process.ExitCode == 0;
    }

    private static string ProbeFilterChain(string filterBackend)
    {
        return filterBackend switch
        {
            "cuda" => "format=nv12,hwupload_cuda,bilateral_cuda=sigmaS=3:sigmaR=0.1:window_size=7,scale_cuda=w=128:h=128:interp_algo=lanczos,hwdownload,format=yuv420p",
            "opencl" => "format=yuv420p,hwupload,nlmeans_opencl=s=1.0:p=7:r=15,unsharp_opencl=lx=5:ly=5:la=0.65:cx=5:cy=5:ca=0.0,hwdownload,format=yuv420p",
            "vulkan" => "format=yuv420p,hwupload,nlmeans_vulkan=s=1.0:p=7:r=15,libplacebo=w=128:h=128:upscaler=ewa_lanczossharp:format=yuv420p,hwdownload,format=yuv420p",
            _ => throw new ArgumentException($"Cannot probe filter backend '{filterBackend}'.", nameof(filterBackend)),
        };
    }

    private static IEnumerable<string> BuildFilterDeviceArgs(string filterBackend, string? filterDevice)
    {
        if (filterBackend is "cpu" or "auto")
        {
            return [];
        }

        string? defaultDevice = FilterBackends[filterBackend];
        string? device = filterDevice ?? defaultDevice;
        return string.IsNullOrWhiteSpace(device)
            ? []
            : ["-init_hw_device", $"{filterBackend}={FilterDeviceName}:{device}", "-filter_hw_device", FilterDeviceName];
    }

    private static IEnumerable<string> BuildVideoEncoderArgs(PresetProfile preset, EnhancementRequest request)
    {
        EncoderProfile encoder = GetEncoder(request.VideoCodec);
        string effectivePreset = request.EncoderPreset
            ?? (encoder.Family == "software" ? preset.EncoderPreset : encoder.DefaultPreset);
        int quality = request.Quality ?? preset.Crf;

        List<string> args = ["-c:v", encoder.Codec];
        switch (encoder.Family)
        {
            case "software":
                args.AddRange(["-preset", effectivePreset, "-crf", quality.ToString(CultureInfo.InvariantCulture)]);
                break;
            case "nvenc":
                args.AddRange(["-preset", effectivePreset, "-rc", "vbr", "-cq:v", quality.ToString(CultureInfo.InvariantCulture), "-b:v", "0"]);
                break;
            case "amf":
                args.AddRange(["-quality", effectivePreset, "-rc", "qvbr", "-qvbr_quality_level", quality.ToString(CultureInfo.InvariantCulture)]);
                break;
            case "qsv":
                args.AddRange(["-preset", effectivePreset, "-global_quality", quality.ToString(CultureInfo.InvariantCulture)]);
                break;
            default:
                throw new InvalidOperationException($"Unsupported encoder family '{encoder.Family}'.");
        }

        return args;
    }

    private static (string Width, string Height) EffectiveDimensions(double scaleFactor, bool noUpscale)
    {
        string scale = scaleFactor.ToString("0.0###############", CultureInfo.InvariantCulture);
        return noUpscale
            ? ($"trunc(min(iw\\,iw*{scale})/2)*2", $"trunc(min(ih\\,ih*{scale})/2)*2")
            : ($"trunc(iw*{scale}/2)*2", $"trunc(ih*{scale}/2)*2");
    }

    private static string InterpolationFilter(PresetProfile preset, int fps)
    {
        IEnumerable<string> args = new[] { $"fps={fps.ToString(CultureInfo.InvariantCulture)}" }
            .Concat(preset.Interpolation.Select(pair => $"{pair.Key}={pair.Value}"));
        return $"minterpolate={string.Join(":", args)}";
    }

    private static IEnumerable<string> GpuPreScaleFilters(string backend, PresetProfile preset)
    {
        if (preset.PreScaleFilters.Count == 0)
        {
            return [];
        }

        return backend switch
        {
            "cuda" => ["format=nv12", "hwupload_cuda", "bilateral_cuda=sigmaS=3:sigmaR=0.1:window_size=7", "hwdownload", "format=yuv420p"],
            "opencl" => ["format=yuv420p", "hwupload", "nlmeans_opencl=s=1.0:p=7:r=15", "hwdownload", "format=yuv420p"],
            "vulkan" => ["format=yuv420p", "hwupload", "nlmeans_vulkan=s=1.0:p=7:r=15", "hwdownload", "format=yuv420p"],
            _ => preset.PreScaleFilters,
        };
    }

    private static IEnumerable<string> ScaleFilters(string backend, string widthExpr, string heightExpr, string scaleFlags)
    {
        return backend switch
        {
            "cuda" =>
            [
                "format=nv12",
                "hwupload_cuda",
                $"scale_cuda=w={widthExpr}:h={heightExpr}:interp_algo={(scaleFlags == "bicubic" ? "bicubic" : "lanczos")}",
                "hwdownload",
                "format=yuv420p",
            ],
            "vulkan" =>
            [
                "format=yuv420p",
                "hwupload",
                $"libplacebo=w={widthExpr}:h={heightExpr}:upscaler={(scaleFlags == "bicubic" ? "bicubic" : "ewa_lanczossharp")}:format=yuv420p",
                "hwdownload",
                "format=yuv420p",
            ],
            _ => [$"scale={widthExpr}:{heightExpr}:flags={scaleFlags}"],
        };
    }

    private static IEnumerable<string> PostScaleFilters(string backend, PresetProfile preset)
    {
        if (preset.PostScaleFilters.Count == 0)
        {
            return [];
        }

        return backend == "opencl"
            ? ["format=yuv420p", "hwupload", "unsharp_opencl=lx=5:ly=5:la=0.65:cx=5:cy=5:ca=0.0", "hwdownload", "format=yuv420p"]
            : preset.PostScaleFilters;
    }

    private static string QuoteArgument(string argument)
    {
        if (argument.Length == 0)
        {
            return "\"\"";
        }

        if (!argument.Any(char.IsWhiteSpace) && !argument.Contains('"'))
        {
            return argument;
        }

        StringBuilder builder = new();
        builder.Append('"');
        foreach (char character in argument)
        {
            if (character is '\\' or '"')
            {
                builder.Append('\\');
            }

            builder.Append(character);
        }

        builder.Append('"');
        return builder.ToString();
    }

    internal sealed record PresetProfile(
        string Name,
        double ScaleFactor,
        int TargetFps,
        string ScaleFlags,
        IReadOnlyDictionary<string, string> Interpolation,
        string EncoderPreset,
        int Crf,
        IReadOnlyList<string>? PreScaleFilters = null,
        IReadOnlyList<string>? PostScaleFilters = null,
        bool InterpolateBeforeScale = false)
    {
        public IReadOnlyList<string> PreScaleFilters { get; } = PreScaleFilters ?? [];
        public IReadOnlyList<string> PostScaleFilters { get; } = PostScaleFilters ?? [];
    }

    private sealed record EncoderProfile(string Codec, string Family, string DefaultPreset);
}
