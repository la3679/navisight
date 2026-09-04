"use client";

import * as Slider from "@radix-ui/react-slider";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/primitives";
import { formatTimestamp } from "@/lib/format";

/**
 * Historical replay controls.
 *
 * The vocabulary here is load-bearing. This is a **replay of an archived
 * day**, not a live feed, and the control labels, the readout, and the
 * accessible names all say so (ADR-0008).
 *
 * Each frame asks the API for every vessel's newest observation *at or before*
 * the selected instant. Nothing is interpolated: between two observations a
 * vessel simply stays where it was last seen, which is the truth of the data
 * rather than a smoothed fiction.
 */

/** Playback rates, in simulated minutes per real second. */
const SPEEDS = [5, 15, 60, 240] as const;

export function ReplayControls({
  coverageStart,
  coverageEnd,
  value,
  onChange,
  disabled,
}: {
  coverageStart: string;
  coverageEnd: string;
  /** Selected instant, or null for "latest known state". */
  value: string | null;
  onChange: (next: string | null) => void;
  disabled?: boolean;
}) {
  const startMs = React.useMemo(() => new Date(coverageStart).getTime(), [coverageStart]);
  const endMs = React.useMemo(() => new Date(coverageEnd).getTime(), [coverageEnd]);
  const totalMinutes = Math.max(1, Math.round((endMs - startMs) / 60_000));

  const [playing, setPlaying] = React.useState(false);
  const [speedIndex, setSpeedIndex] = React.useState(1);

  const currentMinute = value
    ? Math.round((new Date(value).getTime() - startMs) / 60_000)
    : totalMinutes;

  const setMinute = React.useCallback(
    (minute: number) => {
      const clamped = Math.max(0, Math.min(totalMinutes, minute));
      onChange(new Date(startMs + clamped * 60_000).toISOString());
    },
    [onChange, startMs, totalMinutes],
  );

  // Advance the clock while playing. Stops at the end rather than looping,
  // because a loop makes an archive look like a stream.
  React.useEffect(() => {
    if (!playing || disabled) return;
    const step = SPEEDS[speedIndex]!;
    const timer = setInterval(() => {
      const next = currentMinute + step;
      if (next >= totalMinutes) {
        setMinute(totalMinutes);
        setPlaying(false);
      } else {
        setMinute(next);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [playing, speedIndex, currentMinute, totalMinutes, setMinute, disabled]);

  const isLive = value === null;
  const displayed = isLive ? coverageEnd : value;

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-[var(--ns-border)] bg-[var(--ns-surface)] px-3 py-2">
      <div className="flex items-center gap-1">
        <Button
          size="icon"
          variant="ghost"
          disabled={disabled}
          onClick={() => setMinute(currentMinute - SPEEDS[speedIndex]!)}
          aria-label="Step backwards"
        >
          <SkipBack aria-hidden="true" />
        </Button>
        <Button
          size="icon"
          variant={playing ? "primary" : "secondary"}
          disabled={disabled}
          onClick={() => {
            if (isLive) setMinute(0);
            setPlaying((previous) => !previous);
          }}
          aria-label={playing ? "Pause replay" : "Play historical replay"}
        >
          {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
        </Button>
        <Button
          size="icon"
          variant="ghost"
          disabled={disabled}
          onClick={() => setMinute(currentMinute + SPEEDS[speedIndex]!)}
          aria-label="Step forwards"
        >
          <SkipForward aria-hidden="true" />
        </Button>
      </div>

      <div className="flex min-w-[200px] flex-1 items-center gap-3">
        <Slider.Root
          className="relative flex h-5 flex-1 touch-none select-none items-center"
          value={[currentMinute]}
          min={0}
          max={totalMinutes}
          step={1}
          disabled={disabled}
          onValueChange={([minute]) => {
            setPlaying(false);
            setMinute(minute ?? 0);
          }}
          aria-label="Replay position within the archived day"
        >
          <Slider.Track className="relative h-1 grow rounded-full bg-[var(--ns-border)]">
            <Slider.Range className="absolute h-full rounded-full bg-[var(--ns-accent)]" />
          </Slider.Track>
          <Slider.Thumb
            className="block size-4 rounded-full border-2 border-[var(--ns-bg)] bg-[var(--ns-accent)]
                       shadow focus-visible:outline-2 focus-visible:outline-offset-2
                       focus-visible:outline-[var(--ns-focus)]"
            aria-valuetext={formatTimestamp(displayed)}
          />
        </Slider.Root>

        <span
          className="min-w-[168px] shrink-0 font-[family-name:var(--font-mono)] text-[11px] tabular
                     text-[var(--ns-text-secondary)]"
          aria-live="off"
        >
          {formatTimestamp(displayed)}
        </span>
      </div>

      <div className="flex items-center gap-1">
        <span className="text-[11px] text-[var(--ns-text-muted)]">Rate</span>
        {SPEEDS.map((speed, index) => (
          <Button
            key={speed}
            size="sm"
            variant={index === speedIndex ? "primary" : "ghost"}
            aria-pressed={index === speedIndex}
            onClick={() => setSpeedIndex(index)}
            className="px-2"
          >
            {speed}×
          </Button>
        ))}
      </div>

      <Button
        size="sm"
        variant={isLive ? "primary" : "secondary"}
        disabled={disabled}
        onClick={() => {
          setPlaying(false);
          onChange(null);
        }}
        // "Latest observation", never "live".
        title="Show each vessel's newest observation in the dataset"
      >
        Latest
      </Button>
    </div>
  );
}
