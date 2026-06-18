from typing import List
from app.models import ChunkBase

def chunk_text(text: str, chunk_size, overlap) -> List[ChunkBase] | None:
    """
    Descompone un texto en chunks con solapamiento.
    """
    if not text or len(text) == 0:
        return None
    
    chunks = []
    start = 0
    
    while start < len(text):
        # Toma chunk_size caracteres desde la posición actual
        end = start + chunk_size
        chunk_text = text[start:end]
        chunk_index = len(chunks) + 1
        chunk = ChunkBase(
            chunk_text=chunk_text,
            chunk_index=chunk_index
        )
        chunks.append(chunk)
        
        # Mueve el inicio para el siguiente chunk, considerando el overlap
        start += chunk_size - overlap
    
    return chunks


class ChunkingTextService:
    """Servicio para procesar y dividir contenido de correos en chunks."""
    
    def __init__(self, chunk_size: int = 800, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def chunk_email_body(self, body: str) -> List[ChunkBase] | None:
        """Descompone el body de un correo en chunks."""
        return chunk_text(body, self.chunk_size, self.overlap)