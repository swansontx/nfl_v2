from apscheduler.schedulers.background import BackgroundScheduler
from app.services.worker import recompute_projections
import logging

log = logging.getLogger(__name__)

sched = BackgroundScheduler()

# Example: run recompute every 15 minutes
# Use a named job store/trigger here; we rely on the caller to start the scheduler
sched.add_job(recompute_projections, 'interval', minutes=15, id='recompute_projections')


def start():
    if not sched.running:
        log.info('Starting scheduler...')
        sched.start()
    else:
        log.info('Scheduler already running')


def shutdown():
    if sched.running:
        log.info('Shutting down scheduler...')
        sched.shutdown()
    else:
        log.info('Scheduler already stopped')
