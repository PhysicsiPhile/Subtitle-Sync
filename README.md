# SRT-Sync

Synchronize subtitle timestamps using an existing accurate transcription.

This tool takes timing from one subtitle file and text from another file, then produces a new `.srt` with both good timing and good text.

## Inputs and output

```text
Input 1: SRT with good timestamps and lower-quality text
Input 2: TXT with good text, or SRT with good text but bad timestamps
Output: SRT with good text and good timestamps
```

Typical use case:

```text
House.M.D.S08E12.10bit.x265.1080p.BluRay.Joy.srt
    good timing, weaker text

House M.D. - 8x12 - Chase.HDTV.LOL.en.srt
    better text, weaker timing

Output:
House M.D. - 8x12 - Chase.HDTV.LOL.en.synced.srt
    better text + good timing
```

## What this version adds

This build keeps the original SRT-Sync token-DP alignment idea, but adds a Windows-friendly GUI and practical subtitle cleanup.

Main features:

- compact drag-and-drop GUI
- optional Windows `.exe` build
- app logo/icon
- real 0–100 progress bar
- processed/left DP-cell counter
- support for second input as either `.txt` or `.srt`
- local-rate gap placement for sentences present in the second file but missing in the timing file
- final wrapping of long subtitle lines into two readable SRT lines

## How the sync works

The core alignment still follows the original algorithm:

```text
1. Convert timing SRT into XML-like text with timestamp markers.
2. Tokenize both inputs.
3. Run the original full dynamic-programming token alignment.
4. Transfer timing markers to the better text.
5. Write a synced SRT.
```

The original DP recurrence is preserved:

```python
cost0 = costs[x-1][y-1] + 0.99 * cost
cost1 = costs[x-1][y] + self.costT(toks1[x-1])
cost2 = costs[x][y-1] + self.costT(toks2[y-1])
```

## Extra sentence placement

Sometimes the second file contains a sentence that is missing from the timing-corrected SRT.

Example:

```text
Timing SRT:
00:11:57,000 --> 00:12:00,000
The matched line starts here.

Better-text SRT:
A missing sentence before it.
The matched line starts here.
```

In this case, the missing sentence should not be merged into the `00:11:57` subtitle.

This version does the following:

```text
1. Detect target-only text from the original DP alignment.
2. Check whether it appears before or after the matched text.
3. If it appears before the matched line, check the gap before that line.
4. Estimate local milliseconds per word from nearby timing-SRT blocks.
5. Place the missing sentence ending at the matched line's start time.
```

So if the matched line starts near:

```text
00:11:57
```

and the local speaking rate says the missing sentence needs about 12 seconds, it will be placed approximately as:

```text
00:11:45,000 --> 00:11:57,000
A missing sentence before it.
```

## Long-line wrapping

After synchronization, long subtitle lines are split into two visual SRT lines.

Example:

```srt
1
00:00:01,000 --> 00:00:04,000
This is a long subtitle line
split into two readable lines.
```

This uses a real newline inside the SRT block. It does not insert literal `<br>`, `<b>`, or `</b>` tags.

The split is chosen near the middle of the subtitle, preferring punctuation when possible.

## Running the GUI

On Windows, extract the package and run:

```bat
run_gui.bat
```

Then choose:

```text
1. Correct timing SRT
2. Better text SRT/TXT
3. Output synced SRT
```

You can either drag files into the rectangular boxes or click the boxes to browse.

## GUI options

```text
status
    Show status messages.

trace
    Print original token-pair trace.
    This is very verbose and usually should stay off.

gap ms
    Minimum real timing gap before missing text is inserted.
    Default: 700

fallback ms/word
    Fallback milliseconds per word if local speech rate cannot be estimated.
    Default: 280

min words
    Minimum number of words in target-only text before trying to create a new subtitle line.
    Default: 3

wrap
    Character target for splitting long subtitle text into two visual lines.
    Default: 42
    Use 0 to disable wrapping.

input 2
    auto, srt, or txt.
    auto is usually fine.
```

## Command-line usage

Basic usage:

```bat
python SrtSync.py timing.srt better_text.srt
```

With options:

```bat
python SrtSync.py timing.srt better_text.srt ^
  --progress ^
  --min-gap-ms 700 ^
  --ms-per-token 280 ^
  --min-target-missing-words 3 ^
  --local-rate-window 6 ^
  --wrap-chars 42 ^
  --output synced.srt
```

Disable gap insertion:

```bat
python SrtSync.py timing.srt better_text.srt --no-gap-fill
```

Disable line wrapping:

```bat
python SrtSync.py timing.srt better_text.srt --wrap-chars 0
```

Force second input format:

```bat
python SrtSync.py timing.srt better_text.srt --target-format srt
python SrtSync.py timing.srt better_text.txt --target-format txt
```

## Building the Windows EXE

Run:

```bat
build_FORCE_ICON.bat
```

The executable will be created at:

```text
dist\SRT-Sync.exe
```

If that fails, try:

```bat
build_FORCE_ICON_ONELINE.bat
```

## Drag-and-drop support

Drag-and-drop uses `tkinterdnd2`.

When running from source, install it with:

```bat
pip install tkinterdnd2
```

or run:

```bat
install_dragdrop.bat
```

When building the EXE using the included scripts, `tkinterdnd2` is bundled automatically.

## Transcribing audio

The original project also includes a transcription helper:

```bat
python transcribe.py data/KatyPerry-Firework.mp3 large
```

This creates:

```text
data/KatyPerry-Firework.mp3.srt
```

The transcription depends on Whisper and FFmpeg.

Install example:

```bash
pip install -U openai-whisper
sudo apt update && sudo apt install ffmpeg
```

## Original project links

Original Python version:

```text
https://github.com/EtienneAb3d/SRT-Sync
```

Java version:

```text
https://github.com/EtienneAb3d/WhisperTimeSync
```

WhisperHallu:

```text
https://github.com/EtienneAb3d/WhisperHallu
```

karaok-AI:

```text
https://github.com/EtienneAb3d/karaok-AI
```

ChatMate:

```text
https://github.com/EtienneAb3d/ChatMate
```

Commercial/industrial AI linguistic projects:

```text
https://cubaix.com
```

## Notes

This build is meant for practical subtitle cleanup where one source has better timing and another source has better text.

It is not a semantic translator. It aligns text using token-level dynamic programming, so very different paraphrases may still need manual checking.
