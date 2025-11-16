from app.core import cache
from app.config import OUTPUTS
import subprocess
import logging
import os
import glob
from pathlib import Path

log = logging.getLogger(__name__)


def _find_script():
    # prefer env override
    env_path = os.environ.get('GENERATE_PROJECTIONS_SCRIPT')
    if env_path and Path(env_path).exists():
        return env_path
    # common location
    p = Path('scripts/generate_projections.py')
    if p.exists():
        return str(p)
    # fallback: pick latest scripts/generate_*.py
    files = sorted(glob.glob('scripts/generate_*.py'))
    if files:
        return files[-1]
    return None


def _find_latest(glob_pattern: str):
    files = sorted(glob.glob(glob_pattern))
    return files[-1] if files else None


def recompute_projections(timeout: int = 900):
    """Run the existing script to regenerate projections and copy/move outputs to canonical filenames.

    Improvements:
    - script path is configurable via GENERATE_PROJECTIONS_SCRIPT env var or auto-discovered
    - automatically set environment variables pointing to latest selected_events/pbp/qb/kicker files
    - run as a subprocess (blocking) but with a configurable timeout
    """
    log.info('Starting recompute_projections')
    script = _find_script()
    if not script:
        log.error('No generate_projections.py script found')
        return False

    # prepare environment with helpful variables pointing to latest inputs
    env = os.environ.copy()
    sel = _find_latest('data/odds_live/selected_events_*.json')
    if sel:
        env['SELECTED_EVENTS_FILE'] = str(sel)
        log.info('Using selected events file: %s', sel)
    pbp = _find_latest('nfl_data_2025_csv/pbp_*.csv')
    if pbp:
        env['PBP_PATH'] = str(pbp)
        log.info('Using PBP file: %s', pbp)
    qb = _find_latest('outputs/qb_stats*.csv')
    if qb:
        env['QB_PATH'] = str(qb)
        log.info('Using QB stats file: %s', qb)
    kicker = _find_latest('outputs/kicker_stats*.csv')
    if kicker:
        env['KICKER_PATH'] = str(kicker)
        log.info('Using kicker stats file: %s', kicker)

    # call script
    try:
        subprocess.run(['python3', script], check=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.exception('Recompute projections timed out after %s seconds', timeout)
        return False
    except Exception as e:
        log.exception('Recompute projections failed: %s', e)
        return False

    # find latest projections file and create a symlink or copy to canonical
    files = sorted(OUTPUTS.glob('projections_*.csv'))
    if files:
        latest = files[-1]
        canonical = OUTPUTS / 'projections_latest.csv'
        try:
            if canonical.exists() or canonical.is_symlink():
                canonical.unlink()
            canonical.symlink_to(latest.name)
        except Exception:
            # fallback to copy
            import shutil
            shutil.copy(latest, canonical)
    log.info('Recompute complete')
    return True
