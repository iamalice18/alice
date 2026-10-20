"""내레이션 배치 + 배경음악(내레이션이 나올 때 자동으로 줄어듦) 믹스."""
from __future__ import annotations

import subprocess
from pathlib import Path


def mix(narr: list[tuple[Path, float]], bgm: Path | None, total: float, cfg: dict, out: Path) -> Path | None:
    """narr: [(음성 파일, 시작 초)] → out(m4a). 소리가 하나도 없으면 None."""
    if not narr and not bgm:
        return None
    b = cfg["bgm"]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p, _ in narr:
        cmd += ["-i", str(p)]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
    parts = []
    T = f"{total:.3f}"
    if narr:
        for k, (_, start) in enumerate(narr):
            ms = int(start * 1000)
            parts.append(f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,adelay=delays={ms}:all=1[n{k}]")
        ins = "".join(f"[n{k}]" for k in range(len(narr)))
        parts.append(f"{ins}amix=inputs={len(narr)}:normalize=0:dropout_transition=0,apad=whole_dur={T},atrim=0:{T}[nar]")
    if bgm:
        fo = float(b.get("fade_out", 2.5))
        k = len(narr)
        parts.append(
            f"[{k}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{T},asetpts=N/SR/TB,"
            f"volume={b.get('volume', 0.22)},afade=t=in:d=1.2,afade=t=out:st={max(0, total - fo):.3f}:d={fo}[bg]"
        )
    if narr and bgm:
        if b.get("duck", True):
            parts.append("[nar]asplit=2[na][nk]")
            parts.append("[bg][nk]sidechaincompress=threshold=0.02:ratio=6:attack=30:release=600[bgd]")
            parts.append("[bgd][na]amix=inputs=2:normalize=0[out]")
        else:
            parts.append("[bg][nar]amix=inputs=2:normalize=0[out]")
    elif narr:
        parts.append("[nar]anull[out]")
    else:
        parts.append("[bg]anull[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(out)]
    subprocess.run(cmd, check=True)
    return out


def mux(video: Path, audio: Path | None, out: Path) -> None:
    if audio is None:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-c", "copy", str(out)], check=True)
        return
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out)], check=True)
