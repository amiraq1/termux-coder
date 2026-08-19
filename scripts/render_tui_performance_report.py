import json
from pathlib import Path

import matplotlib.pyplot as plt

DATA = Path("/home/ubuntu/termux-coder/performance_report/tui_performance_data.json")
OUT = DATA.parent


def main() -> None:
    result = json.loads(DATA.read_text(encoding="utf-8"))
    samples = result["samples"]
    metadata = result["metadata"]

    times = [sample["elapsed_s"] for sample in samples]
    current = [sample["current_memory_mb"] for sample in samples]
    peak = [sample["peak_memory_mb"] for sample in samples]
    labels = [sample["phase"] for sample in samples]

    throughput_labels = []
    throughput = []
    for previous, sample in zip(samples, samples[1:]):
        delta_tokens = sample["estimated_tokens"] - previous["estimated_tokens"]
        delta_seconds = sample["elapsed_s"] - previous["elapsed_s"]
        if delta_tokens > 0 and delta_seconds > 0:
            throughput_labels.append(sample["phase"])
            throughput.append(delta_tokens / delta_seconds)

    plt.style.use("seaborn-v0_8-darkgrid")
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), constrained_layout=True)
    fig.suptitle("termux-coder TUI Stress Test Performance", fontsize=16, fontweight="bold")

    axes[0].plot(times, current, marker="o", linewidth=2, label="Current traced memory")
    axes[0].plot(times, peak, marker="o", linewidth=2, label="Peak traced memory")
    axes[0].set_title("Memory consumption over execution phases")
    axes[0].set_xlabel("Elapsed time (seconds)")
    axes[0].set_ylabel("Memory (MiB)")
    axes[0].legend(loc="best")
    axes[0].set_xlim(left=0)

    axes[1].bar(range(len(throughput)), throughput, color="#4c78a8")
    axes[1].set_title("Estimated token throughput per streaming batch")
    axes[1].set_xlabel("Streaming batch")
    axes[1].set_ylabel("Estimated tokens / second")
    axes[1].set_xticks(range(len(throughput)))
    axes[1].set_xticklabels([str(index + 1) for index in range(len(throughput))])

    chart_path = OUT / "tui_performance_overview.png"
    fig.savefig(chart_path, dpi=160)
    plt.close(fig)

    stage_indexes = [0, len(samples) // 2, len(samples) - 1]
    stage_labels = [labels[index] for index in stage_indexes]
    stage_memory = [peak[index] for index in stage_indexes]
    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    ax.bar(stage_labels, stage_memory, color=["#72b7b2", "#f2cf5b", "#e45756"])
    ax.set_title("Peak memory at representative checkpoints")
    ax.set_ylabel("Peak traced memory (MiB)")
    ax.tick_params(axis="x", rotation=20)
    stage_path = OUT / "tui_peak_memory_checkpoints.png"
    fig.savefig(stage_path, dpi=160)
    plt.close(fig)

    max_rate = max(throughput) if throughput else 0
    min_rate = min(throughput) if throughput else 0
    report = {
        "chart_overview": str(chart_path),
        "chart_checkpoints": str(stage_path),
        "estimated_token_throughput_min": round(min_rate, 2),
        "estimated_token_throughput_max": round(max_rate, 2),
        "estimated_token_throughput_mean": round(sum(throughput) / len(throughput), 2) if throughput else 0,
        "metadata": metadata,
        "summary": result["summary"],
    }
    (OUT / "tui_performance_analysis.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
