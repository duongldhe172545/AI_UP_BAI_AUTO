import os
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from worker import post_next_approved

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def job():
    try:
        result = post_next_approved()
        logging.info("job: %s", result.get("status"))
        if result.get("post_url"):
            logging.info("posted: %s", result["post_url"])
    except Exception as e:
        logging.exception("Job failed: %s", e)

def main():
    hour = int(os.getenv("SCHEDULE_HOUR", "8"))
    minute = int(os.getenv("SCHEDULE_MINUTE", "0"))
    tz = os.getenv("TIMEZONE", "Asia/Bangkok")
    sched = BlockingScheduler(timezone=tz)
    sched.add_job(job, CronTrigger(hour=hour, minute=minute))
    logging.info("Scheduler started (daily %02d:%02d). Ctrl+C to stop.", hour, minute)
    sched.start()

if __name__ == "__main__":
    main()
