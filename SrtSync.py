#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SRT-Sync original DP + local-rate target-extra gap placement.

This keeps the original CbxAligner full DP token comparison.

Important correction:
    Target-only text from File 2 is not automatically merged into the next
    timed subtitle. If the target-only chunk appears before the matched text of
    a timed line, we first check the gap BEFORE that line.

Placement:
    - Estimate local ms/word from nearby timed subtitles in the timing SRT.
    - required_ms = word_count(extra_text) * local_ms_per_word.
    - Prefix extra text:
          check previous_end -> current_start
          if it fits, place it ending at current_start
          start = current_start - required_ms
    - Suffix extra text:
          check current_end -> next_start
          if it fits, place it starting at current_end

Line breaks and SRT block boundaries in File 2 are ignored as logic.
"""

import argparse
import html
import re
import sys
from pathlib import Path

from CbxAligner import CbxAligner
from CbxTokenizer import CbxToken


_TIME_LINE_RE = re.compile(
    r'^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s+-->\s+\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}.*$'
)
_TIME_TAG_RE = re.compile(r'<time\s+id="([^"]+)"\s+stamp="([^"]+)"\s*/>')
_STAMP_RE = re.compile(
    r'(?P<a>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s+-->\s+(?P<b>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})'
)


def looks_like_srt(text):
    return bool(_TIME_LINE_RE.search(text))


def clean_text(text):
    text = html.unescape(text or "")
    text = re.sub(r'</?(?:i|b|u|font|c|v|ruby|rt|rp)\b[^>]*>', ' ', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\{\\[^}]+\}', ' ', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t\f\v]+', ' ', text)
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)
    text = re.sub(r'([¿¡])\s+', r'\1', text)
    return text.strip()


def split_long_subtitle_line(text, wrap_chars=42):
    """Split a long subtitle into at most two visual SRT lines.

    Uses an actual newline, not a literal <br> or <b> tag. Most SRT players
    display this as two subtitle lines.
    """
    text = clean_text(text)
    if not wrap_chars or wrap_chars <= 0 or len(text) <= wrap_chars:
        return text

    words = text.split()
    if len(words) <= 1:
        return text

    target = len(text) / 2.0
    candidates = []

    for i in range(1, len(words)):
        left = ' '.join(words[:i])
        right = ' '.join(words[i:])
        if not left or not right:
            continue

        max_len = max(len(left), len(right))
        balance = abs(len(left) - len(right))
        overflow = max(0, max_len - wrap_chars)
        punct_bonus = -8 if left[-1:] in {',', '.', ';', ':', '?', '!'} else 0

        score = overflow * 20 + balance + abs(len(left) - target) + punct_bonus
        candidates.append((score, left, right))

    if not candidates:
        return text

    _, left, right = min(candidates, key=lambda x: x[0])
    return left + "\n" + right


def wrap_subtitle_text(text, wrap_chars=42):
    """Wrap final subtitle text into max two lines."""
    text = clean_text(text)
    return split_long_subtitle_line(text, wrap_chars=wrap_chars)


def has_text(text):
    return bool(re.search(r'[A-Za-z0-9]', clean_text(text)))


def word_count(text):
    return len(re.findall(r'[A-Za-z0-9]+', clean_text(text)))


def token_text(tokens):
    return clean_text(''.join(tokens))


def srt_to_continuous_text(srt_text):
    """Strip SRT numbers/timestamps and return continuous dialogue text.

    Deliberately ignores subtitle block breaks and visual line breaks.
    """
    text = srt_text.replace('\ufeff', '').replace('\r\n', '\n').replace('\r', '\n')
    pieces = []
    for block in re.split(r'\n\s*\n+', text.strip()):
        lines = [ln.strip() for ln in block.split('\n') if ln.strip()]
        if not lines:
            continue
        if re.fullmatch(r'\d+', lines[0]):
            lines = lines[1:]
        lines = [ln for ln in lines if not _TIME_LINE_RE.match(ln)]
        piece = clean_text(' '.join(lines))
        if has_text(piece):
            pieces.append(piece)
    return ' '.join(pieces)


def parse_source_text_by_id(srt_text):
    """Fallback text from timing SRT, only used if aligned target text is empty."""
    text = srt_text.replace('\ufeff', '').replace('\r\n', '\n').replace('\r', '\n')
    out = {}
    synthetic = 1
    for raw in re.split(r'\n\s*\n+', text.strip()):
        lines = [ln.strip() for ln in raw.split('\n') if ln.strip()]
        if not lines:
            continue
        block_id = str(synthetic)
        if re.fullmatch(r'\d+', lines[0]):
            block_id = lines[0]
            lines = lines[1:]
        body = []
        after_time = False
        for ln in lines:
            if _TIME_LINE_RE.match(ln):
                after_time = True
                continue
            if after_time:
                body.append(ln)
        line = clean_text(' '.join(body))
        if has_text(line):
            out[block_id] = line
        synthetic += 1
    return out


def parse_stamp_ms(stamp):
    stamp = html.unescape(stamp)
    m = _STAMP_RE.search(stamp)
    if not m:
        raise ValueError(f"Could not parse timestamp: {stamp!r}")

    def one(v):
        v = v.strip().replace(',', '.')
        hh, mm, rest = v.split(':')
        ss, frac = rest.split('.')
        frac = (frac + '000')[:3]
        return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000 + int(frac)

    return one(m.group('a')), one(m.group('b'))


def fmt_ms(ms):
    ms = max(0, int(round(ms)))
    hh, rem = divmod(ms, 3600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def make_stamp(start, end):
    if end <= start:
        end = start + 300
    return f"{fmt_ms(start)} --> {fmt_ms(end)}"


def median(values):
    values = sorted(values)
    if not values:
        return None
    n = len(values)
    mid = n // 2
    if n % 2:
        return values[mid]
    return 0.5 * (values[mid - 1] + values[mid])


class Segment:
    def __init__(self, block_id, stamp):
        self.block_id = block_id
        self.stamp = html.unescape(stamp)
        self.start, self.end = parse_stamp_ms(stamp)

        # Ordered items: ("base", [tokens]) or ("target_extra", [tokens]).
        self.items = []
        self.source_tokens = []
        self._target_extra_buf = []

    def duration_ms(self):
        return max(0, self.end - self.start)

    def flush_target_extra(self):
        if self._target_extra_buf:
            text = token_text(self._target_extra_buf)
            if has_text(text):
                self.items.append(("target_extra", list(self._target_extra_buf)))
            self._target_extra_buf = []

    def add_base_token(self, token):
        self.flush_target_extra()
        if self.items and self.items[-1][0] == "base":
            self.items[-1][1].append(token)
        else:
            self.items.append(("base", [token]))

    def add_pair(self, source_tok, target_tok):
        if source_tok is not None and source_tok.kind != CbxToken.TAG:
            self.source_tokens.append(source_tok.token)

        if source_tok is None and target_tok is not None:
            # Text present in File 2 but not in timing SRT.
            self._target_extra_buf.append(target_tok.token)
            return

        if target_tok is not None:
            self.add_base_token(target_tok.token)
        else:
            self.flush_target_extra()

    def finish(self):
        self.flush_target_extra()

    def source_text(self):
        return token_text(self.source_tokens)

    def source_word_count(self):
        return word_count(self.source_text())

    def base_indices(self):
        return [i for i, (kind, toks) in enumerate(self.items) if kind == "base" and has_text(token_text(toks))]

    def extra_items(self):
        out = []
        base_idxs = self.base_indices()
        first_base = min(base_idxs) if base_idxs else None
        last_base = max(base_idxs) if base_idxs else None

        for idx, (kind, toks) in enumerate(self.items):
            if kind != "target_extra":
                continue
            text = token_text(toks)
            if not has_text(text):
                continue

            if first_base is None:
                position = "orphan"
            elif idx < first_base:
                position = "prefix"
            elif idx > last_base:
                position = "suffix"
            else:
                position = "middle"
            out.append((idx, text, position))
        return out

    def base_text(self, promoted_indices=None):
        promoted_indices = promoted_indices or set()
        toks = []
        for idx, (kind, item_tokens) in enumerate(self.items):
            if kind == "target_extra" and idx in promoted_indices:
                continue
            toks.extend(item_tokens)
        return token_text(toks)


def local_ms_per_word(segments, idx, fallback_ms_per_token=280, window=6, min_ms=120, max_ms=900):
    """Estimate ms/word from nearby timing-SRT lines.

    Uses the timing donor itself, around the current line. Median is used so one
    weird very-short/very-long subtitle does not dominate.
    """
    rates = []
    lo = max(0, idx - window)
    hi = min(len(segments), idx + window + 1)

    for j in range(lo, hi):
        wc = segments[j].source_word_count()
        dur = segments[j].duration_ms()
        if wc <= 0 or dur < 250:
            continue
        rate = dur / wc
        if min_ms <= rate <= max_ms:
            rates.append(rate)

    val = median(rates)
    if val is None:
        val = fallback_ms_per_token

    # Clamp fallback/median to a sane subtitle speech range.
    val = max(min_ms, min(max_ms, float(val)))
    return val


def fit_chunks_in_gap(chunks, gap_start, gap_end, ms_per_word, anchor):
    """Fit chunks into gap.

    anchor='end':
        chunks are placed contiguously ending at gap_end. This is for text that
        appears before the current line, e.g. missing sentence should end at
        current_start and start as far back as its duration requires.

    anchor='start':
        chunks are placed contiguously starting at gap_start. This is for text
        that appears after the current line.
    """
    clean_chunks = []
    total_required = 0

    for idx, text in chunks:
        wc = word_count(text)
        required = max(300, int(round(wc * ms_per_word)))
        clean_chunks.append((idx, text, required))
        total_required += required

    available = gap_end - gap_start
    if not clean_chunks or available <= 0 or total_required > available:
        return set(), []

    events = []
    promoted = {idx for idx, _, _ in clean_chunks}

    if anchor == "end":
        cursor = gap_end
        for idx, text, required in reversed(clean_chunks):
            start = cursor - required
            end = cursor
            events.append((start, end, text))
            cursor = start
        events.reverse()
    else:
        cursor = gap_start
        for idx, text, required in clean_chunks:
            start = cursor
            end = cursor + required
            events.append((start, end, text))
            cursor = end

    return promoted, events


class SrtSync:
    def __init__(self):
        self.aligner = CbxAligner()

    def toXml(self, srt):
        xml = "\n" + srt + "\n"
        xml = re.sub(r'[\n\r]+', '\n', xml)
        xml = re.sub(r'&', '&amp;', xml)
        xml = re.sub(r'<', '&lt;', xml)
        xml = re.sub(r'>', '&gt;', xml)
        xml = re.sub(
            r'\n([0-9]+)\n([0-9]+:[0-9]+:[0-9]+[,.][0-9]+ --&gt; [0-9]+:[0-9]+:[0-9]+[,.][0-9]+[^\n]*)\n',
            r'<time id="\1" stamp="\2"/>',
            xml,
        )
        return xml

    def pairs_to_srt(
        self,
        pairs,
        fallback_by_id=None,
        gap_fill=True,
        min_gap_ms=700,
        fallback_ms_per_token=280,
        min_target_missing_words=3,
        local_rate_window=6,
        wrap_chars=42,
        show_progress=False,
    ):
        fallback_by_id = fallback_by_id or {}
        segments = []
        current = None

        for source_tok, target_tok in pairs:
            if source_tok is not None and source_tok.kind == CbxToken.TAG:
                m = _TIME_TAG_RE.match(source_tok.token)
                if m:
                    if current is not None:
                        current.finish()
                        segments.append(current)
                    current = Segment(m.group(1), m.group(2))
                    continue

            if current is not None:
                current.add_pair(source_tok, target_tok)

        if current is not None:
            current.finish()
            segments.append(current)

        events = []
        inserted = 0
        not_fit = 0
        fallback_count = 0
        placement_debug = []

        for i, seg in enumerate(segments):
            prev_end = segments[i - 1].end if i > 0 else None
            next_start = segments[i + 1].start if i + 1 < len(segments) else None

            local_rate = local_ms_per_word(
                segments,
                i,
                fallback_ms_per_token=fallback_ms_per_token,
                window=local_rate_window,
            )

            promoted = set()
            extra_events = []

            if gap_fill:
                extras = [
                    (idx, text, position)
                    for idx, text, position in seg.extra_items()
                    if word_count(text) >= min_target_missing_words
                ]

                prefix_like = [(idx, text) for idx, text, pos in extras if pos in ("prefix", "middle", "orphan")]
                suffix_like = [(idx, text) for idx, text, pos in extras if pos == "suffix"]

                # First: text that appears before this line's matched words
                # belongs in the gap BEFORE this line.
                if prefix_like and prev_end is not None and seg.start - prev_end >= min_gap_ms:
                    p, ev = fit_chunks_in_gap(
                        prefix_like,
                        prev_end,
                        seg.start,
                        local_rate,
                        anchor="end",
                    )
                    promoted.update(p)
                    extra_events.extend(ev)
                    for _, _, text in ev:
                        placement_debug.append((seg.block_id, "before", local_rate, text))

                # If prefix text did not fit before, try after only as fallback.
                remaining_prefix = [(idx, text) for idx, text in prefix_like if idx not in promoted]

                # Second: suffix text belongs in the gap AFTER this line.
                after_candidates = suffix_like + remaining_prefix
                if after_candidates and next_start is not None and next_start - seg.end >= min_gap_ms:
                    p, ev = fit_chunks_in_gap(
                        after_candidates,
                        seg.end,
                        next_start,
                        local_rate,
                        anchor="start",
                    )
                    promoted.update(p)
                    extra_events.extend(ev)
                    for _, _, text in ev:
                        placement_debug.append((seg.block_id, "after", local_rate, text))

                total_candidates = {(idx, text) for idx, text, _ in extras}
                not_fit += len([1 for idx, text in total_candidates if idx not in promoted])

            base = seg.base_text(promoted)
            if not has_text(base):
                base = fallback_by_id.get(seg.block_id, seg.source_text())
                fallback_count += 1

            if has_text(base):
                events.append((seg.start, seg.end, base, False))

            for start, end, text in extra_events:
                events.append((start, end, text, True))
                inserted += 1

        events.sort(key=lambda x: (x[0], x[1]))

        blocks = []
        for start, end, text, guessed in events:
            text = wrap_subtitle_text(text, wrap_chars=wrap_chars)
            if not has_text(text):
                continue
            blocks.append(f"{len(blocks)+1}\n{make_stamp(start, end)}\n{text}")

        if show_progress:
            print(f"Output blocks: {len(blocks)}", file=sys.stderr)
            if inserted:
                print(f"Inserted {inserted} target-only chunk(s) into nearby gaps using local ms/word.", file=sys.stderr)
            if not_fit:
                print(f"Kept {not_fit} target-only chunk(s) merged because they did not fit nearby gaps.", file=sys.stderr)
            if fallback_count:
                print(f"Fallback copied {fallback_count} block(s) because target text was empty there.", file=sys.stderr)

        return '\n\n'.join(blocks).strip()

    def sync(
        self,
        pathSrt,
        pathTxt,
        show_progress=False,
        trace=False,
        target_format="auto",
        output_path=None,
        print_output=True,
        gap_fill=True,
        min_gap_ms=700,
        ms_per_token=280,
        min_target_missing_words=3,
        local_rate_window=6,
        wrap_chars=42,
        progress_callback=None,
    ):
        self.pathSrt = pathSrt
        self.pathTxt = pathTxt

        if progress_callback:
            progress_callback(0.0, "Reading files...", None, None)

        with open(self.pathSrt, 'r', encoding='utf-8') as f:
            self.srt = f.read()

        with open(self.pathTxt, 'r', encoding='utf-8') as f:
            self.txt = f.read()

        if progress_callback:
            progress_callback(1.0, "Preparing text...", None, None)

        fmt = (target_format or "auto").lower()
        if fmt not in {"auto", "txt", "srt"}:
            raise ValueError("target_format must be auto, txt, or srt")

        target_is_srt = fmt == "srt" or (
            fmt == "auto" and (self.pathTxt.lower().endswith(".srt") or looks_like_srt(self.txt))
        )

        if target_is_srt:
            if show_progress:
                print("Second input is SRT: stripping timestamps and treating dialogue as continuous text.", file=sys.stderr)
            self.txt = srt_to_continuous_text(self.txt)

        self.xml = self.toXml(self.srt)

        if show_progress:
            print("Running original full-DP token alignment from CbxAligner.", file=sys.stderr)

        pairs = self.aligner.alignXml(
            self.xml,
            self.txt,
            progress_callback=progress_callback,
        )

        if trace:
            self.aligner.tracePairs(pairs)

        if progress_callback:
            progress_callback(99.0, "Writing synced subtitle...", None, None)

        self.synced = self.pairs_to_srt(
            pairs,
            fallback_by_id=parse_source_text_by_id(self.srt),
            gap_fill=gap_fill,
            min_gap_ms=min_gap_ms,
            fallback_ms_per_token=ms_per_token,
            min_target_missing_words=min_target_missing_words,
            local_rate_window=local_rate_window,
            wrap_chars=wrap_chars,
            show_progress=show_progress,
        )

        if print_output:
            print(self.synced)

        out_path = output_path
        if not out_path:
            out_path = str(Path(self.pathTxt).with_suffix(".synced.srt")) if self.pathTxt.lower().endswith(".srt") else self.pathTxt + ".srt"

        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(self.synced)

        if progress_callback:
            progress_callback(100.0, "Done.", None, None)

        print(f"\nWrote: {out_path}", file=sys.stderr)
        return out_path


def main():
    parser = argparse.ArgumentParser(description="Original SRT-Sync DP with local-rate target-extra gap placement.")
    parser.add_argument('pathSrt', type=str, help="Path to SRT file with good timestamps")
    parser.add_argument('pathTxt', type=str, help="Path to TXT/SRT file with current/better text")
    parser.add_argument('lng', type=str, help="language", nargs='?')
    parser.add_argument('--progress', action='store_true', help="print status lines")
    parser.add_argument('--trace', action='store_true', help="print original token pair trace; very verbose")
    parser.add_argument('--target-format', choices=['auto', 'txt', 'srt'], default='auto')
    parser.add_argument('--no-gap-fill', action='store_true', help="disable inserting target-only text into timing gaps")
    parser.add_argument('--min-gap-ms', type=int, default=700, help="minimum gap before insertion is considered")
    parser.add_argument('--ms-per-token', type=int, default=280, help="fallback milliseconds per word if local rate cannot be estimated")
    parser.add_argument('--min-target-missing-words', type=int, default=3, help="minimum words in a target-only chunk before trying to insert it")
    parser.add_argument('--local-rate-window', type=int, default=6, help="number of nearby timing-SRT blocks on each side used to estimate local ms/word")
    parser.add_argument('--wrap-chars', type=int, default=42, help="split long subtitle text into two lines around this many chars; 0 disables")
    parser.add_argument('--output', '-o', default=None)
    parser.add_argument('--no-print', action='store_true')
    args = parser.parse_args()

    SrtSync().sync(
        args.pathSrt,
        args.pathTxt,
        show_progress=args.progress,
        trace=args.trace,
        target_format=args.target_format,
        output_path=args.output,
        print_output=not args.no_print,
        gap_fill=not args.no_gap_fill,
        min_gap_ms=args.min_gap_ms,
        ms_per_token=args.ms_per_token,
        min_target_missing_words=args.min_target_missing_words,
        local_rate_window=args.local_rate_window,
        wrap_chars=args.wrap_chars,
    )


if __name__ == "__main__":
    main()
