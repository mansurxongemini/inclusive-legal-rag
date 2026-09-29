#!/usr/bin/env python3
"""
Government Regulations Ingestion (Delegated to Universal Autonomous Engine).
Maintained for backwards-compatibility; delegates to src.ingestion.universal_engine.
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.universal_engine import CORE_REGULATIONS_REGISTRY, UniversalAutonomousEngine
from src.storage.hybrid_store import HybridStore
from src.clients.openrouter import OpenRouterClient


async def main():
    store = HybridStore()
    client = OpenRouterClient()
    engine = UniversalAutonomousEngine(store=store, client=client)
    print("Executing Regulations Ingestion via Universal Engine...")
    result = await engine.run_pipeline(CORE_REGULATIONS_REGISTRY)
    print(f"Regulations Ingestion Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
