"""
conftest.py — Configura o sys.path para que os imports funcionem corretamente
durante os testes sem precisar de instalação do pacote.
"""
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path
sys.path.insert(0, str(Path(__file__).parent))
