"""Choose a whole clean observation, never construct new score pixels."""
from viewport_tracker import ViewportError


def select(track):
    usable = [r for r in track.observations if r.complete and not r.cursor_occluded
              and not r.obstruction_detected and r.original_crop]
    if not usable:
        error = ViewportError('no_clean_observation')
        error.observation = track.observations[-1]
        error.row_index = track.index
        raise error
    track.selected_observation = min(usable, key=lambda r: (-r.sharpness, r.timestamp))
    return track.selected_observation
