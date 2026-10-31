from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.scheduler.jobs import BillingJob, JobReport

__all__ = ["BillingJob", "JobReport", "create_scheduler"]


def create_scheduler(job: BillingJob, tz: ZoneInfo) -> AsyncIOScheduler:
    """Запускає джобу на початку кожної години (о 10:00 якраз настає момент списання)."""
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        job.run,
        trigger="cron",
        minute=0,
        id="billing",
        max_instances=1,
        coalesce=True,  # кілька пропущених запусків → один
        misfire_grace_time=30 * 60,
        replace_existing=True,
    )
    return scheduler
