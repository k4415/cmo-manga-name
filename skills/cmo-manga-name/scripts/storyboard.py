#!/usr/bin/env python3
"""4列セルの形式検証・TSV出力・読戻し照合。標準ライブラリのみ。2026-09-11"""
import argparse
import csv
import io
import json
import math
import re
import unicodedata
from pathlib import Path

HEADER = ['画像サイズ', '登場人物', 'セリフ「」　\n心の声（）　\nナレーションNA：\n効果音SE：　\n注釈 ：（本文の印は語の直前に ※ ）', 'コマ内容']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def spoken_body(line):
    """C列の発声可能な一行。SE・注釈・空行を暗黙に読み上げない。"""
    require(not line.startswith(('SE：', '注釈：')), 'audio_plan: SE・注釈は発声行に指定できません')
    if line.startswith('NA：'):
        return 'NA', line[3:]
    match = re.fullmatch(r'([^「」（）]+)(?:「(.+)」|（(.+)）)', line)
    require(match is not None, 'audio_plan: セリフ・心の声・NAだけを発声行に指定できます')
    return match.group(1), match.group(2) or match.group(3)


def spoken_count(body):
    # 注釈の参照印、空白、句読点を除外。英字・漢字は表記の文字数。
    body = re.sub(r'※[0-9０-９]{0,3}', '', body)
    return sum(not c.isspace() and not unicodedata.category(c).startswith('P') for c in body)


def speech_report(data):
    """任意のaudio_planだけを検証・計数する。旧補助フィールドは解釈しない。"""
    old_cuts = data.get('cuts')
    legacy = 'speech_groups' in data or (isinstance(old_cuts, list) and any(isinstance(c, dict) and 'voice' in c for c in old_cuts))
    if 'audio_plan' not in data:
        return {'status': 'unspecified', 'spoken_characters': None, 'legacy_fields_present': legacy,
                'note': 'audio_plan未指定。旧cuts.voice等やC列を自動で発声扱いしません。'}
    plan = data['audio_plan']
    require(isinstance(plan, dict) and type(plan.get('version')) is int and plan['version'] == 1,
            'audio_plan: versionは1が必要です')
    cuts = data.get('cuts')
    require(isinstance(cuts, list) and cuts, 'audio_plan: cutsが必要です')
    segments, groups = plan.get('segments'), plan.get('groups', [])
    require(isinstance(segments, list) and isinstance(groups, list), 'audio_plan: segments/groupsは配列です')
    seen, records, cursor = set(), [], 0
    group_map = {}
    for g in groups:
        require(isinstance(g, dict) and isinstance(g.get('id'), str) and g['id'].strip(), 'audio_plan: group idが必要です')
        require(g['id'] not in group_map and isinstance(g.get('body'), str) and g['body'].strip(), 'audio_plan: group idの重複または本文の不足')
        require(g.get('speaker') in data['characters'] + ['NA'], 'audio_plan: group話者が不正です')
        group_map[g['id']] = g
    for segment in segments:
        require(isinstance(segment, dict), 'audio_plan: segmentはオブジェクトです')
        cut, line = segment.get('cut'), segment.get('line')
        require(type(cut) is int and cursor <= cut <= len(cuts) and cut >= 1, 'audio_plan: cut番号が不正、または時間順ではありません')
        cursor = cut
        lines = data['rows'][cuts[cut-1]['image']-1][2].split('\n')
        require(type(line) is int and 1 <= line <= len(lines), 'audio_plan: C列の行番号が不正です')
        require((cut, line) not in seen, 'audio_plan: 同じcut/lineの発声が重複しています')
        seen.add((cut, line))
        speaker, body = spoken_body(lines[line-1])
        require(speaker in data['characters'] + ['NA'], 'audio_plan: 発声行の話者が不正です')
        group = segment.get('group')
        require(group is None or (isinstance(group, str) and group in group_map), 'audio_plan: 未定義のgroupです')
        if group is not None:
            require(group_map[group]['speaker'] == speaker, 'audio_plan: groupと発声行の話者が違います')
        records.append({'cut': cut, 'image': cuts[cut-1]['image'], 'line': line,
                        'speaker': speaker, 'body': body, 'group': group})
    for key, g in group_map.items():
        indexes = [i for i, r in enumerate(records) if r['group'] == key]
        require(bool(indexes), 'audio_plan: 発声のないgroupです')
        require(indexes == list(range(indexes[0], indexes[-1]+1)), 'audio_plan: groupの間に別の発言があります')
        selected = [records[i] for i in indexes]
        require(''.join(r['body'] for r in selected) == g['body'], 'audio_plan: group本文に欠落・重複・不一致があります')
        group_cuts = sorted(set(r['cut'] for r in selected))
        require(group_cuts == list(range(group_cuts[0], group_cuts[-1]+1)), 'audio_plan: 無音カットをまたぐ発言は別groupにしてください')
    per_cut = []
    for i, cut in enumerate(cuts, 1):
        selected = [r for r in records if r['cut'] == i]
        text = ''.join(r['body'] for r in selected)
        per_cut.append({'cut': i, 'image': cut['image'], 'start': cut['start'], 'end': cut['end'],
                        'spoken_characters': sum(spoken_count(r['body']) for r in selected), 'body_characters_with_punctuation': len(text)})
    per_image = []
    for i, row in enumerate(data['rows'], 1):
        # 同じ画像を再使用しても、一画像の発声文字量を重複加算しない。
        line_ids = sorted({r['line'] for r in records if r['image'] == i})
        bodies = [spoken_body(row[2].split('\n')[n-1])[1] for n in line_ids]
        text = ''.join(bodies)
        per_image.append({'image': i, 'spoken_characters': sum(spoken_count(body) for body in bodies),
                          'body_characters_with_punctuation': len(text)})
    return {'status': 'validated', 'spoken_characters': sum(c['spoken_characters'] for c in per_cut),
            'segments': records, 'per_cut': per_cut, 'per_image': per_image,
            'group_count': len(groups), 'audio_timing_tested': False,
            'legacy_fields_present': legacy,
            'legacy_note': '旧発声情報も存在します。集計はaudio_planのみを使用します。' if legacy else None,
            'count_rule': '発声指定行のみ。話者・空白・Unicode句読点・注釈参照印を除外。表記の文字数であり音声秒数ではない。'}


def validate(data):
    require(isinstance(data, dict), '正本はJSONオブジェクトが必要です')
    require(data.get('media') in ('article', 'short_video', 'other'), 'mediaはarticle / short_video / otherが必要です')
    rows, names, panels = data.get('rows'), data.get('characters'), data.get('panels')
    require(isinstance(rows, list) and rows, 'rowsは1画像以上必要です')
    require(isinstance(names, list) and all(isinstance(n, str) and n.strip() == n and n and not any(x in n for x in '\n\r\t・「」（）') for n in names), 'charactersは確定名配列です。空名・前後空白・改行・タブ・区切りの・や「」（）は使えません')
    require(len(set(names)) == len(names), '確定名が重複しています')
    require(isinstance(panels, list) and len(panels) == len(rows), 'panelsとrowsの件数が一致しません')
    header = data.get('header', HEADER)
    require(isinstance(header, list) and len(header) == 4 and all(isinstance(v, str) and v for v in header), 'headerは4つの文字列です')
    for index, (row, panel) in enumerate(zip(rows, panels), 1):
        label = f'画像{index}: '
        require(isinstance(row, list) and len(row) == 4 and all(isinstance(v, str) for v in row), label+'セルは4文字列が必要です')
        require(row[0] in ('縦長', '正方形', '横長'), label+'画像サイズが未対応です')
        require(row[3].strip(), label+'コマ内容が空です')
        people = row[1].split('・') if row[1] else []
        require(len(set(people)) == len(people) and all(p in names for p in people), label+'B列の人物名を設計と照合してください')
        require(isinstance(panel, dict), label+'panels要素はオブジェクトです')
        count, mapping = panel.get('count'), panel.get('text_map')
        require(type(count) is int and count > 0, label+'内部コマ数が不正です')
        require(isinstance(mapping, list) and len(mapping) == count and all(isinstance(x, list) for x in mapping), label+'内部コマごとのtext_mapが必要です')
        lines = row[2].split('\n') if row[2] else []
        offscreen = panel.get('offscreen_speakers', [])
        require(isinstance(offscreen, list) and all(isinstance(n, str) and n in names and n not in people for n in offscreen), label+'画像外話者の指定が不正です')
        note_lines, marked_lines = set(), set()
        for line_no, line in enumerate(lines, 1):
            if line.startswith(('NA：', 'SE：', '注釈：')):
                require(line.split('：', 1)[1].strip(), label+'空の文字要素があります')
            else:
                match = re.fullmatch(r'([^「」（）]+)(?:「(.+)」|（(.+)）)', line)
                require(match is not None, label+f'C列{line_no}行目の記法が未対応です')
                require(len(match.group(1).encode('utf-16-le')) // 2 <= 20, label+'取込の話者名は20文字以内が必要です。確定名の変更は確認してください')
                require(match.group(1) in people + offscreen, label+f'C列{line_no}行目の話者が未対応です')
            if line.startswith('注釈：'):
                note_lines.add(line_no)
            elif not line.startswith('SE：') and '※' in line:
                marked_lines.add(line_no)
        assigned = [line for group in mapping for line in group]
        require(all(type(v) is int for v in assigned) and sorted(assigned) == list(range(1, len(lines)+1)), label+'文字行のコマ割当が欠落・重複しています')
        annotations = panel.get('annotation_map', [])
        require(isinstance(annotations, list), label+'annotation_mapは配列です')
        covered_notes, covered_marks = [], set()
        body_mark_values, note_mark_values = set(), set()
        for line_no in marked_lines:
            body_mark_values.update(unicodedata.normalize('NFKC', m) for m in re.findall(r'※[0-9０-９]{0,3}', lines[line_no-1]))
        for annotation in annotations:
            require(isinstance(annotation, dict), label+'注釈対応が不正です')
            note, targets = annotation.get('note_line'), annotation.get('target_lines')
            require(type(note) is int and note in note_lines and isinstance(targets, list) and all(type(t) is int and t in marked_lines for t in targets), label+'注釈と本文の印を照合してください')
            prefix = re.match(r'(?:※[0-9０-９]{0,3}[・,、，\s]*)*', lines[note-1].split('：', 1)[1]).group(0)
            marks = {unicodedata.normalize('NFKC', m) for m in re.findall(r'※[0-9０-９]{0,3}', prefix)}
            require(bool(marks) == bool(targets), label+'本文対応の注釈は先頭に同じ※印、単独注釈は印なしにしてください')
            for target in targets:
                target_marks = {unicodedata.normalize('NFKC', m) for m in re.findall(r'※[0-9０-９]{0,3}', lines[target-1])}
                require(bool(marks & target_marks), label+'注釈と本文の※番号が一致しません')
            note_mark_values.update(marks)
            covered_notes.append(note)
            covered_marks.update(targets)
        require(sorted(covered_notes) == sorted(note_lines) and covered_marks == marked_lines, label+'注釈または本文の印の対応が不足しています')
        require(body_mark_values == note_mark_values, label+'本文と注釈の※番号に欠落があります')
    if data['media'] == 'short_video' or 'cuts' in data or 'duration_seconds' in data:
        duration, cuts = data.get('duration_seconds'), data.get('cuts')
        require(number(duration) and duration > 0 and isinstance(cuts, list) and cuts, '動画は全尺とcutsが必要です')
        cursor = 0
        used = set()
        for cut in cuts:
            require(isinstance(cut, dict), 'cutはオブジェクトです')
            start, end, image = cut.get('start'), cut.get('end'), cut.get('image')
            require(number(start) and number(end) and abs(start-cursor) < 1e-6 and end > start, 'カット時間に空白・重複・逆転があります')
            require(type(image) is int and 1 <= image <= len(rows), 'カットの画像番号が不正です')
            cursor = end
            used.add(image)
        require(abs(cursor-duration) < 1e-6, 'カット合計が全尺と一致しません')
        require(used == set(range(1, len(rows)+1)), '動画に未使用の画像があります')
    # 任意でも、付けられた発声プランは不整合のまま書き出さない。
    speech_report(data)
    return [header] + rows


def tsv_bytes(cells):
    for row in cells:
        for cell in row:
            require('\r' not in cell and '\x00' not in cell, 'CRまたはNULを含むセルがあります。正本の改行を確認してください')
            require(not cell.lstrip().startswith(('=', '+', '-', '@')), '数式化の懸念があります。RAW入力または文字列型XLSXを使用してください')
    stream = io.StringIO(newline='')
    csv.writer(stream, delimiter='\t', lineterminator='\n').writerows(cells)
    content = stream.getvalue()
    require(list(csv.reader(io.StringIO(content, newline=''), delimiter='\t')) == cells, 'TSV往復でセル値が変化しました')
    return content


def normalize_readback(actual):
    require(isinstance(actual, list) and all(isinstance(row, list) and len(row) <= 4 and all(isinstance(v, str) for v in row) for row in actual), '読戻しはA:Dの文字列セル配列が必要です')
    normalized = [row + [''] * (4-len(row)) for row in actual]
    while normalized and all(v == '' for v in normalized[-1]):
        normalized.pop()
    return normalized


def main():
    parser = argparse.ArgumentParser(description='漫画ネームの4列検証・TSV書出し（外部通信なし）')
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compare-cells', type=Path)
    parser.add_argument('--speech-report', type=Path, help='任意audio_planの検証・文字数を新規JSONへ出力（尺の実測ではない）')
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        cells = validate(data)
        report = speech_report(data)
        if args.compare_cells:
            actual = json.loads(args.compare_cells.read_text(encoding='utf-8'))
            require(normalize_readback(actual) == cells, '読戻しセルが正本と一致しません（末尾の旧原稿や欠落も確認）')
        destinations = [p.resolve() for p in (args.output, args.speech_report) if p is not None]
        require(len(set(destinations)) == len(destinations), 'TSVと発声レポートの出力先は別にしてください')
        require(all(not p.exists() for p in destinations), '出力先が既に存在します。新しい出力先を指定してください')
        if args.output:
            content = tsv_bytes(cells)
            with args.output.open('x', encoding='utf-8', newline='') as output:
                output.write(content)
        if args.speech_report:
            with args.speech_report.open('x', encoding='utf-8') as output:
                json.dump(report, output, ensure_ascii=False, indent=2)
                output.write('\n')
        print(json.dumps({'ok': True, 'images': len(cells)-1, 'columns': 4, 'tsv_written': bool(args.output), 'speech_report_written': bool(args.speech_report), 'speech_status': report['status'], 'cells_compared': bool(args.compare_cells), 'scope': '形式のみ。外部保存・生成・広告成果は未検証'}, ensure_ascii=False))
    except (ValueError, OSError, TypeError) as error:
        parser.exit(1, f'検証失敗: {error}\n')


if __name__ == '__main__':
    main()
