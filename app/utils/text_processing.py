import re
from typing import List, Tuple

FILE_MARKER_RE = re.compile(r'^--- File: (.+) ---$')

# Column-0 lines that start a new top-level section. "config" covers FortiOS
# (top-level "config ... end" blocks); "!" covers Cisco IOS/ASA section
# separators. Anything else stays attached to the current section.
SECTION_START_RE = re.compile(r'^(config\s|!)')


def chunk_text(text: str, size: int) -> List[str]:
    """
    Splits text into chunks, attempting to break at newline boundaries
    to maintain configuration integrity.
    """
    chunks = []
    start = 0
    while start < len(text):
        if start + size >= len(text):
            chunks.append(text[start:])
            break

        # Look for the last newline within the size limit
        end = text.rfind('\n', start, start + size)
        if end == -1 or end <= start:
            # Fallback to hard split if no newline found
            end = start + size

        chunks.append(text[start:end])
        start = end + 1
    return chunks


def split_concatenated_files(content: str) -> List[Tuple[str, str]]:
    """
    Splits the "--- File: <name> ---" concatenation produced by the analyze
    endpoint back into (filename, file_content) pairs. Content before the
    first marker (or the whole input if there are no markers) is returned
    under the empty-string filename.
    """
    files: List[Tuple[str, str]] = []
    current_name = ""
    current_lines: List[str] = []
    for line in content.split('\n'):
        marker = FILE_MARKER_RE.match(line)
        if marker:
            if current_lines and any(l.strip() for l in current_lines):
                files.append((current_name, '\n'.join(current_lines)))
            current_name = marker.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines and any(l.strip() for l in current_lines):
        files.append((current_name, '\n'.join(current_lines)))
    return files


def _split_into_sections(text: str) -> List[Tuple[int, str]]:
    """
    Splits config text into top-level sections at semantic boundaries
    (FortiOS "config ... end" blocks, Cisco "!" separators). Returns
    (start_line, section_text) pairs; start_line is 1-based within `text`.
    """
    sections: List[Tuple[int, str]] = []
    current: List[str] = []
    current_start = 1
    for lineno, line in enumerate(text.split('\n'), start=1):
        if SECTION_START_RE.match(line) and current:
            sections.append((current_start, '\n'.join(current)))
            current = []
            current_start = lineno
        current.append(line)
    if current:
        sections.append((current_start, '\n'.join(current)))
    return sections


def chunk_config_text(text: str, max_chars: int) -> List[Tuple[int, str]]:
    """
    Splits config text into chunks no larger than max_chars, breaking at
    top-level section boundaries so multi-line blocks (firewall policies,
    interfaces, address objects) are never split mid-block. A single section
    larger than max_chars falls back to newline-based splitting. Returns
    (start_line, chunk_text) pairs; start_line is 1-based within `text`.
    """
    chunks: List[Tuple[int, str]] = []
    pending: List[str] = []
    pending_start = 1
    pending_len = 0

    def flush():
        nonlocal pending, pending_len
        if pending:
            chunks.append((pending_start, '\n'.join(pending)))
            pending = []
            pending_len = 0

    for start_line, section in _split_into_sections(text):
        if pending_len and pending_len + len(section) + 1 > max_chars:
            flush()
        if not pending:
            pending_start = start_line

        if len(section) > max_chars:
            # Oversized single section: hard-split it by lines.
            flush()
            offset = start_line
            for sub in chunk_text(section, max_chars):
                chunks.append((offset, sub))
                offset += sub.count('\n') + 1
        else:
            pending.append(section)
            pending_len += len(section) + 1

    flush()
    return chunks
