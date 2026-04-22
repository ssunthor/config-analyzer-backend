from typing import List

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
