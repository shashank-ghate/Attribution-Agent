from app.config.settings import settings
from app.services.report_service import ReportService


report_service = ReportService(settings)


def get_report_service() -> ReportService:
    return report_service
