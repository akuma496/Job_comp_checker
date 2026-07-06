from ingestion.ashby import AshbyIngestor
from ingestion.base import AtsIngestor
from ingestion.greenhouse import GreenhouseIngestor
from ingestion.lever import LeverIngestor

ATS_REGISTRY: dict[str, type[AtsIngestor]] = {
    "greenhouse": GreenhouseIngestor,
    "lever": LeverIngestor,
    "ashby": AshbyIngestor,
}
