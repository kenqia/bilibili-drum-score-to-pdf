"""Choose a whole clean observation, never construct new score pixels."""
from viewport_tracker import ViewportError


def select(track):
    usable = [r for r in track.observations if r.complete and not r.cursor_occluded
              and not r.obstruction_detected and r.original_crop]
    if not usable:
        raise ViewportError('no_clean_observation')
    track.selected_observation = min(usable, key=lambda r: (-r.sharpness, r.timestamp))
    return track.selected_observation
