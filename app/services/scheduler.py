from apscheduler.schedulers.background import BackgroundScheduler
from app.services.worker import recompute_projections
import logging

log = logging.getLogger(__name__)

sched = BackgroundScheduler()

JOB_ID = 'recompute_projections'

# Do NOT register jobs at import time. Register when the scheduler is started so importing
# this module doesn't create side effects.


def start():
    if not sched.running:
        log.info('Starting scheduler...')
        # register job if not already present
        if not sched.get_job(JOB_ID):
            sched.add_job(recompute_projections, 'interval', minutes=15, id=JOB_ID)
        sched.start()
    else:
        log.info('Scheduler already running')


def shutdown():
    if sched.running:
        log.info('Shutting down scheduler...')
        try:
            # remove job cleanly
            job = sched.get_job(JOB_ID)
            if job:
                sched.remove_job(JOB_ID)
        except Exception:
            pass
        sched.shutdown()
    else:
        log.info('Scheduler already stopped')
