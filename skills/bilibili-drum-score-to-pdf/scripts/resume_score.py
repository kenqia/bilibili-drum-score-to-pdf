"""Local persisted decisions; resume always replays the original video."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


class ResumeError(Exception):
    pass


def digest(path):
    hashed = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            hashed.update(block)
    return hashed.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, prefix='.progress-', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    temporary.replace(path)


def _image_references(value):
    """Yield owners and keys of local image references in a persisted result."""
    if isinstance(value, dict):
        for key, item in value.items():
            # Answer image paths point to user input, not persisted evidence.
            if key == 'decisions':
                continue
            if key in {'image', 'original_image'}:
                yield value, key
            else:
                yield from _image_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from _image_references(item)


def artifact_names(result):
    names = {owner[key] for owner, key in _image_references(result)}
    if result.get('pdf'):
        names.add(result['pdf'])
    if result.get('status') == 'success' and not result.get('pdf'):
        raise ValueError('Successful progress requires a PDF reference')
    return names


def artifact_path(output, name):
    """Reject absolute paths, traversal and linked artifacts before reading."""
    if not isinstance(name, str):
        raise ValueError
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative.suffix.lower() not in {'.png', '.pdf'}:
        raise ValueError
    path = output / relative
    if any((output / Path(*relative.parts[:index])).is_symlink() for index in range(1, len(relative.parts) + 1)):
        raise ValueError
    if not path.resolve().is_relative_to(output.resolve()) or not path.is_file():
        raise ValueError
    return path


def persist(result, source, output, decisions=None, origin=None):
    output = Path(output)
    if origin is not None:
        result['origin'] = origin
    if result['status'] in {'success', 'waiting'}:
        result['source'].update(original_path=str(Path(source).resolve()), fingerprint=digest(source))
        result['decisions'] = decisions or {}
        result['confirmation_count'] = len(result['decisions'])
        result['state'] = 'state.json'
    atomic_json(output / 'manifest.json', result)
    if result['status'] in {'success', 'waiting'}:
        artifacts = {name: digest(artifact_path(output, name)) for name in artifact_names(result)}
        atomic_json(output / 'state.json', {'artifacts': artifacts, 'schema_version': 2, 'manifest_sha256': digest(output / 'manifest.json'), 'source': {'path': result['source']['original_path'], 'sha256': result['source']['fingerprint']}, 'decisions': result['decisions']})
    return result


def load(output):
    from drum_score import probe_video, ConversionError
    output = Path(output)
    try:
        if (output / 'state.json').is_symlink() or (output / 'manifest.json').is_symlink():
            raise ValueError
        state = json.loads((output / 'state.json').read_text())
        manifest = json.loads((output / 'manifest.json').read_text())
        if not isinstance(state, dict) or not isinstance(manifest, dict) or not isinstance(state.get('artifacts'), dict) or not isinstance(state.get('decisions'), dict):
            raise ValueError
        if state['schema_version'] != 2 or digest(output / 'manifest.json') != state['manifest_sha256'] or state['source']['path'] != manifest['source']['original_path'] or state['source']['sha256'] != manifest['source']['fingerprint'] or state['decisions'] != manifest['decisions']:
            raise ValueError
        if set(state['artifacts']) != artifact_names(manifest):
            raise ValueError
        # A replay can replace the deliverable before committing its manifest.
        # The prior waiting generation must not silently accept that new PDF.
        if not manifest.get('pdf') and ((output / 'score.pdf').exists() or (output / 'score.pdf').is_symlink()):
            raise ValueError
        for name, expected in state['artifacts'].items():
            artifact = artifact_path(output, name)
            if digest(artifact) != expected:
                raise ValueError
        source = Path(state['source']['path'])
        # Validate a real playable video before hashing the persisted local path.
        probe_video(source)
        if digest(source) != state['source']['sha256']:
            raise ValueError
        for row in manifest.get('rows', []) + manifest.get('candidate_rows', []):
            image = (output / row['image']).resolve()
            if not image.is_relative_to(output.resolve()) or digest(image) != row['content_sha256']:
                raise ValueError
        for issue in manifest.get('issues', []):
            image = (output / issue['image']).resolve()
            if not image.is_relative_to(output.resolve()) or not image.is_file():
                raise ValueError
        return source, manifest, dict(state['decisions'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ConversionError):
        raise ResumeError('进度、PDF、证据或原视频已变更、损坏或不属于同一代结果。旧版缺少完整性记录的状态也不能继续；已保留原目录，请核查后在新的空目录重建。') from None


def validate_supplement(path, output, issue):
    from drum_score import analyze_frame, ConversionError
    from PIL import Image
    try:
        with Image.open(path) as image:
            analysis = analyze_frame(image)
            if len(analysis['groups']) != 1:
                raise ValueError
            bbox = analysis['bbox']
            top, bottom = analysis['row_bounds'][0]
            row = image.crop((bbox[0], bbox[1] + top, bbox[2], bbox[1] + bottom)).convert('RGB')
            from quality_score import assess, printable
            quality = assess(row, analysis['groups'][0]['spacing'])
            if quality['cursor_occluded']:
                raise ValueError
            name = 'images/supplement-' + issue['id'] + '.png'
            original = 'images/supplement-original-' + issue['id'] + '.png'
            row.save(Path(output) / original)
            printable(row).save(Path(output) / name)
            return {'id': 'supplement-' + issue['id'], 'image': name, 'original_image': original, 'quality': quality, 'timestamp': issue['timestamp'], 'bbox': [bbox[0], bbox[1] + top, bbox[2], bbox[1] + bottom], 'content_sha256': digest(Path(output) / name), 'supplement': {'source_sha256': digest(path), 'user_provided': True}, 'confirmed': True}
    except (OSError, ValueError, Image.DecompressionBombError, ConversionError):
        return None


def resume(output, answers=None):
    from drum_score import convert
    output = Path(output)
    source, saved, decisions = load(output)
    if answers is None:
        return saved
    try:
        supplied = json.loads(Path(answers).read_text())
        if not isinstance(supplied, dict):
            raise ValueError
        known = {issue['id']: issue for issue in saved.get('issues', [])}
        if not supplied:
            return saved
        for identifier, choice in supplied.items():
            if not isinstance(choice, dict):
                raise ValueError
            allowed_fields = {'action'}
            if choice.get('action') == 'supplement':
                allowed_fields.add('image')
            if choice.get('action') == 'confirm_overlap':
                allowed_fields.add('overlap')
            if set(choice) != allowed_fields:
                raise ValueError
            if identifier in decisions and choice == {key: value for key, value in decisions[identifier].items() if key != 'image_sha256'}:
                continue
            issue = known.get(identifier)
            if issue is None or not isinstance(choice, dict) or choice.get('action') not in issue['choices']:
                raise ValueError
            if choice['action'] == 'confirm_overlap' and (type(choice.get('overlap')) is not int or choice['overlap'] not in issue.get('overlap_candidates', [])):
                raise ValueError
            if choice['action'] == 'supplement':
                if not isinstance(choice.get('image'), str):
                    raise ValueError
                # Absolute local paths keep answers independent of cwd.
                choice = dict(choice, image=str(Path(choice['image']).resolve()))
            decisions[identifier] = choice
    except (OSError, ValueError, TypeError):
        result = dict(saved)
        result['answer_error'] = '回答未能明确解决当前疑点，请按编号选择提供的处理方式。原进度和已确认内容保持不变。'
        return result
    if decisions == saved.get('decisions', {}):
        return saved
    with tempfile.TemporaryDirectory(prefix='drum-resume-', dir=output.parent) as scratch:
        replay = Path(scratch)
        result = convert(source, replay, decisions=decisions)
        if result['status'] == 'failed':
            unchanged = dict(saved)
            unchanged['answer_error'] = '重放原视频失败，已保留原进度。请核查输入后继续。'
            return unchanged
        # Each replay keeps prior evidence untouched until the new manifest commits.
        generation = Path(tempfile.mkdtemp(prefix='replay-', dir=output))
        for folder in ('images', 'evidence'):
            if (replay / folder).exists():
                shutil.copytree(replay / folder, generation / folder)
        for owner, key in _image_references(result):
            owner[key] = generation.name + '/' + owner[key]
        if result.get('pdf'):
            temporary_pdf = generation / 'score.pdf'
            shutil.copy2(replay / result['pdf'], temporary_pdf)
            temporary_pdf.replace(output / result['pdf'])
        return persist(result, source, output, result.get('decisions', {}), saved.get('origin'))
